import pytest

from app.schemas.events import (
    AvatarCueEvent,
    BoardOp,
    InterruptFlushEvent,
    PlayoutPauseEvent,
    PlayoutResumeEvent,
)
from app.voice.backchannel_guard import GuardVerdict
from app.voice.barge_in import BargeInController, ControllerState, FakeClock
from app.voice.stt import FakeSTT, STTResult
from app.voice.tts import PCMCursor


@pytest.mark.asyncio
async def test_soft_duck_at_200ms_emits_pause_and_preserves_llm():
    stt = FakeSTT()
    cursor = PCMCursor(turn_id=1)
    clock = FakeClock()

    cancelled = False
    paused = False

    def on_cancel():
        nonlocal cancelled
        cancelled = True

    def on_pause():
        nonlocal paused
        paused = True

    controller = BargeInController(
        stt=stt,
        cursor=cursor,
        clock=clock,
        on_cancel_in_flight=on_cancel,
        on_pause_playout=on_pause,
    )

    controller.start_turn(turn_id=1)
    assert controller.state == ControllerState.PLAYING

    # Student starts speaking
    controller.on_vad_speech_start(1000.0)

    # Speech sustained for 150ms (< 200ms threshold)
    await controller.on_vad_speech_tick(1150.0)
    assert controller.state == ControllerState.PLAYING
    assert paused is False
    assert len(controller.emitted_events) == 0

    # Speech sustained for 200ms -> Soft Duck triggers!
    await controller.on_vad_speech_tick(1200.0)
    assert controller.state == ControllerState.SOFT_DUCKED
    assert paused is True
    assert cancelled is False  # LLM task is NOT cancelled during soft duck
    assert controller.cancel_hooks_called == 0

    assert len(controller.emitted_events) == 1
    pause_ev = controller.emitted_events[0]
    assert isinstance(pause_ev, PlayoutPauseEvent)
    assert pause_ev.turn_id == 1


@pytest.mark.asyncio
async def test_backchannel_resumes_playout_with_rewind():
    # STT returns filler: "okay"
    stt = FakeSTT(default_result=STTResult(text="okay", no_speech_prob=0.01))
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 24000
    cursor.played_samples = 12000  # 500ms

    resumed_ms: int | None = None

    def on_resume(ms: int):
        nonlocal resumed_ms
        resumed_ms = ms

    controller = BargeInController(
        stt=stt,
        cursor=cursor,
        on_resume_playout=on_resume,
    )
    controller.start_turn(turn_id=1)
    cursor.total_samples = 24000
    cursor.advance_played_samples(12000)  # 500ms played

    # Soft duck
    controller.on_vad_speech_start(1000.0)
    await controller.on_vad_speech_tick(1250.0)
    assert controller.state == ControllerState.SOFT_DUCKED

    # Student speech ends
    verdict = await controller.on_vad_speech_end(1500.0, b"\x00" * 4800)
    assert verdict == GuardVerdict.BACKCHANNEL

    # Resumed playout
    assert controller.state == ControllerState.PLAYING
    assert resumed_ms == 200
    assert cursor.played_samples == 7200  # 12000 - 4800 (200ms rewind)

    # Events emitted:
    # [PlayoutPause, AvatarCue(thinking), PlayoutResume(200ms), AvatarCue(speaking)]
    assert len(controller.emitted_events) == 4
    assert isinstance(controller.emitted_events[0], PlayoutPauseEvent)
    assert isinstance(controller.emitted_events[1], AvatarCueEvent)
    assert controller.emitted_events[1].cue == "thinking"
    assert isinstance(controller.emitted_events[2], PlayoutResumeEvent)
    assert controller.emitted_events[2].rewind_ms == 200
    assert isinstance(controller.emitted_events[3], AvatarCueEvent)
    assert controller.emitted_events[3].cue == "speaking"


@pytest.mark.asyncio
async def test_real_question_triggers_stage_2_commit():
    # STT returns a real substantive question
    stt = FakeSTT(
        default_result=STTResult(
            text="why does the denominator become zero?",
            no_speech_prob=0.01,
            avg_logprob=-0.1,
        )
    )
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 24000
    cursor.played_samples = 9600  # 400ms

    cancelled = False
    interrupt_question: str | None = None

    def on_cancel():
        nonlocal cancelled
        cancelled = True

    async def on_qa(text: str):
        nonlocal interrupt_question
        interrupt_question = text

    controller = BargeInController(
        stt=stt,
        cursor=cursor,
        on_cancel_in_flight=on_cancel,
        on_interrupt_qa=on_qa,
    )

    pending_text = ["This is the remaining sentence.", "And another one."]
    pending_ops = [
        BoardOp(op_id="op_1", op_type="latex", payload={"latex": "x^2"}),
        BoardOp(op_id="op_2", op_type="plot", payload={"fn": "sin(x)"}),
    ]

    controller.start_turn(
        turn_id=1,
        unplayed_text=pending_text,
        unrendered_board_ops=pending_ops,
    )
    cursor.total_samples = 24000
    cursor.advance_played_samples(9600)  # 400ms played

    # Soft duck
    controller.on_vad_speech_start(1000.0)
    await controller.on_vad_speech_tick(1220.0)
    assert controller.state == ControllerState.SOFT_DUCKED

    # End of speech with real question
    verdict = await controller.on_vad_speech_end(2000.0, b"\x00" * 9600)
    assert verdict == GuardVerdict.REAL_QUESTION

    # Stage 2 checks:
    # 1. Turn incremented
    assert controller.active_turn_id == 2
    # 2. Cancel hooks executed within the call
    assert cancelled is True
    assert controller.cancel_hooks_called == 1
    # 3. INTERRUPT_FLUSH emitted carrying new_turn_id
    flush_events = [
        e for e in controller.emitted_events if isinstance(e, InterruptFlushEvent)
    ]
    assert len(flush_events) == 1
    assert flush_events[0].new_turn_id == 2
    # 4. Resume stack holds unplayed items
    assert len(controller.resume_stack) == 1
    stack_frame = controller.resume_stack[0]
    assert stack_frame["turn_id"] == 1
    assert stack_frame["unplayed_text"] == pending_text
    assert len(stack_frame["unrendered_board_ops"]) == 2
    assert stack_frame["played_ms"] == 400
    # 5. Question routed to handler
    assert interrupt_question == "why does the denominator become zero?"


def test_latency_masking_filler_decision_with_clock():
    stt = FakeSTT()
    cursor = PCMCursor()
    clock = FakeClock(start_time=10.0)

    controller = BargeInController(stt=stt, cursor=cursor, clock=clock)

    tts_start = 10.0

    # 500ms elapsed -> should not play filler
    clock.advance(0.5)
    assert controller.should_play_filler(tts_start) is False

    # 1050ms elapsed -> still within 1100ms
    clock.advance(0.55)
    assert controller.should_play_filler(tts_start) is False

    # 1150ms elapsed -> exceeds 1100ms, should play filler!
    clock.advance(0.1)
    assert controller.should_play_filler(tts_start) is True
