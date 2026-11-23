"""Tests for SessionAgent: voice coordination, audio pumping, and barge-in."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

import pytest

from app.llm.stream_parser import LatexEvent, ParsedEvent, SayEvent
from app.schemas.events import (
    AudioSegmentStartEvent,
    AvatarCueEvent,
    BoardScheduleEvent,
    DataChannelEvent,
    InterruptFlushEvent,
    PlayoutPauseEvent,
    PlayoutResumeEvent,
)
from app.tutor.fsm import StateEvent
from app.voice.barge_in import FakeClock
from app.voice.session_agent import (
    BYTES_PER_FRAME,
    LEAD_IN_SILENCE_BYTES,
    SessionAgent,
)
from app.voice.stt import FakeSTT, STTResult
from app.voice.tts import FakeTTS


class DummyTutorService:
    """Mock TutorService for SessionAgent unit tests."""

    def __init__(self) -> None:
        self.handled_messages: list[str] = []
        self.next_stream: list[ParsedEvent | StateEvent] = []

    async def handle_student_message(
        self, session_id: Any, message: str
    ) -> AsyncIterator[ParsedEvent | StateEvent]:
        self.handled_messages.append(message)
        for ev in self.next_stream:
            yield ev


@pytest.mark.asyncio
async def test_session_agent_turn_playout_and_audio_pumping():
    session_id = uuid4()
    tutor_service = DummyTutorService()
    tts = FakeTTS(samples_per_word=2400)
    stt = FakeSTT()

    datachannel_events: list[DataChannelEvent] = []
    audio_frames: list[bytes] = []

    agent = SessionAgent(
        session_id=session_id,
        tutor_service=tutor_service,  # type: ignore[arg-type]
        tts=tts,
        stt=stt,
        data_channel_sink=lambda ev: datachannel_events.append(ev),
        audio_frame_sink=lambda chunk: audio_frames.append(chunk),
    )
    await agent.initialize()

    async def event_generator() -> AsyncIterator[ParsedEvent | StateEvent]:
        yield SayEvent(text="Hello welcome to physics.")
        yield LatexEvent(latex=r"E = mc^2")
        yield SayEvent(text="This is energy.")

    await agent.play_turn_events(event_generator())

    # 1. Lead-in silence was pumped: first 7,200 bytes (150ms)
    lead_in_frame_count = LEAD_IN_SILENCE_BYTES // BYTES_PER_FRAME
    assert len(audio_frames) >= lead_in_frame_count
    for i in range(lead_in_frame_count):
        assert audio_frames[i] == b"\x00" * BYTES_PER_FRAME

    # 2. Frame sizes are strictly 20ms chunks (960 bytes)
    for frame in audio_frames:
        assert len(frame) == BYTES_PER_FRAME

    # 3. AudioSegmentStartEvent response was emitted
    start_events = [
        e for e in datachannel_events if isinstance(e, AudioSegmentStartEvent)
    ]
    assert len(start_events) == 1
    assert start_events[0].segment_id == "response"
    assert start_events[0].turn_id == 0

    # 4. BoardScheduleEvent was emitted with valid playout_offset_ms >= 150ms
    board_events = [
        e for e in datachannel_events if isinstance(e, BoardScheduleEvent)
    ]
    assert len(board_events) == 1
    assert board_events[0].turn_id == 0
    assert len(board_events[0].operations) == 1
    op = board_events[0].operations[0]
    assert op.op_type == "latex"
    assert op.payload == {"latex": r"E = mc^2"}
    assert op.playout_offset_ms >= 150


@pytest.mark.asyncio
async def test_session_agent_latency_masking_plays_filler():
    session_id = uuid4()
    tutor_service = DummyTutorService()
    tts = FakeTTS()
    stt = FakeSTT()
    clock = FakeClock(start_time=0.0)

    datachannel_events: list[DataChannelEvent] = []
    audio_frames: list[bytes] = []

    agent = SessionAgent(
        session_id=session_id,
        tutor_service=tutor_service,  # type: ignore[arg-type]
        tts=tts,
        stt=stt,
        data_channel_sink=lambda ev: datachannel_events.append(ev),
        audio_frame_sink=lambda chunk: audio_frames.append(chunk),
    )
    agent.barge_in.clock = clock
    await agent.initialize()

    async def slow_event_generator() -> AsyncIterator[ParsedEvent | StateEvent]:
        # Advance clock to simulate 1,500ms TTFT/synthesis delay (>1,100ms)
        clock.advance(1.5)
        yield SayEvent(text="Here is the detailed explanation.")

    await agent.play_turn_events(slow_event_generator())

    # Should have emitted:
    # 1. AudioSegmentStartEvent(segment_id="filler")
    # 2. AudioSegmentStartEvent(segment_id="response")
    start_events = [
        e for e in datachannel_events if isinstance(e, AudioSegmentStartEvent)
    ]
    assert len(start_events) == 2
    assert start_events[0].segment_id == "filler"
    assert start_events[1].segment_id == "response"


@pytest.mark.asyncio
async def test_session_agent_soft_duck_and_backchannel_resume():
    session_id = uuid4()
    tutor_service = DummyTutorService()
    tts = FakeTTS(samples_per_word=12000)  # Long audio
    stt = FakeSTT(default_result=STTResult(text="okay", no_speech_prob=0.01))

    datachannel_events: list[DataChannelEvent] = []
    agent = SessionAgent(
        session_id=session_id,
        tutor_service=tutor_service,  # type: ignore[arg-type]
        tts=tts,
        stt=stt,
        data_channel_sink=lambda ev: datachannel_events.append(ev),
    )
    await agent.initialize()

    async def long_speech() -> AsyncIterator[ParsedEvent | StateEvent]:
        yield SayEvent(text="First sentence with lots of words.")

    # Run playout in background
    task = asyncio.create_task(agent.play_turn_events(long_speech()))
    await asyncio.sleep(0.01)

    # Student speaks for 250ms -> triggers soft duck
    agent.barge_in.on_vad_speech_start(1000.0)
    await agent.barge_in.on_vad_speech_tick(1250.0)
    assert agent._playout_paused is True

    # Student speech ends with "okay" (backchannel)
    verdict = await agent.barge_in.on_vad_speech_end(1400.0, b"\x00" * 4800)
    assert verdict.value == "BACKCHANNEL"

    # Playout resumed
    assert agent._playout_paused is False

    await task

    # Check event sequence
    pause_events = [e for e in datachannel_events if isinstance(e, PlayoutPauseEvent)]
    resume_events = [
        e for e in datachannel_events if isinstance(e, PlayoutResumeEvent)
    ]
    speaking_cues = [
        e
        for e in datachannel_events
        if isinstance(e, AvatarCueEvent) and e.cue == "speaking"
    ]
    assert len(pause_events) == 1
    assert len(resume_events) == 1
    assert len(speaking_cues) == 1


@pytest.mark.asyncio
async def test_session_agent_stage_2_interrupt_cancels_and_dispatches_qa():
    session_id = uuid4()
    tutor_service = DummyTutorService()
    tutor_service.next_stream = [SayEvent(text="This is the answer to your question.")]
    tts = FakeTTS(samples_per_word=12000)
    stt = FakeSTT(
        default_result=STTResult(
            text="why does the denominator become zero?",
            no_speech_prob=0.01,
            avg_logprob=-0.1,
        )
    )

    datachannel_events: list[DataChannelEvent] = []
    sentence1_started = asyncio.Event()

    def handle_datachannel_event(ev: DataChannelEvent) -> None:
        datachannel_events.append(ev)
        if isinstance(ev, AudioSegmentStartEvent) and ev.segment_id == "response":
            sentence1_started.set()

    agent = SessionAgent(
        session_id=session_id,
        tutor_service=tutor_service,  # type: ignore[arg-type]
        tts=tts,
        stt=stt,
        data_channel_sink=handle_datachannel_event,
    )
    await agent.initialize()

    async def initial_lecture() -> AsyncIterator[ParsedEvent | StateEvent]:
        yield SayEvent(text="Sentence 1 that will be interrupted.")
        yield SayEvent(text="Sentence 2 that should never play.")

    # Start initial lecture and wait deterministically for response playback to begin
    initial_task = asyncio.create_task(agent.play_turn_events(initial_lecture()))
    await asyncio.wait_for(sentence1_started.wait(), timeout=1.0)

    # Student asks real question
    agent.barge_in.on_vad_speech_start(1000.0)
    await agent.barge_in.on_vad_speech_tick(1250.0)
    verdict = await agent.barge_in.on_vad_speech_end(2000.0, b"\x00" * 9600)
    assert verdict.value == "REAL_QUESTION"

    # Stage 2 checks:
    # 1. Turn incremented
    assert agent.barge_in.active_turn_id == 1

    # 2. INTERRUPT_FLUSH emitted
    flush_events = [
        e for e in datachannel_events if isinstance(e, InterruptFlushEvent)
    ]
    assert len(flush_events) == 1
    assert flush_events[0].new_turn_id == 1

    # 3. Resume stack contains unplayed items
    assert len(agent.barge_in.resume_stack) == 1
    unplayed = agent.barge_in.resume_stack[0]["unplayed_text"]
    assert "Sentence 1 that will be interrupted." in unplayed

    # 4. Tutor service received question
    assert "why does the denominator become zero?" in tutor_service.handled_messages

    # Initial task finishes cleanly without raising
    try:
        await initial_task
    except asyncio.CancelledError:
        pass
