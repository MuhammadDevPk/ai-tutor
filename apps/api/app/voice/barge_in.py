"""Two-Stage Barge-In Controller decoupled from LiveKit WebRTC I/O.

Invariants:
- Stage 1 (Soft Duck): Sustained student speech >= 200ms emits PLAYOUT_PAUSE,
  freezes playout, but keeps LLM and board queue intact.
- STT + Backchannel Guard evaluation:
  - BACKCHANNEL / NOISE: Rewind PCM cursor 200ms (or clause boundary) and emit
    PLAYOUT_RESUME with exact rewind_ms.
  - REAL_QUESTION: Stage 2 commit — increment active_turn_id, cancel in-flight tasks,
    emit INTERRUPT_FLUSH, push unplayed text and unrendered ops onto resume_stack,
    and route to INTERRUPT_QA.
- Latency masking: On VAD end-of-speech emit AVATAR_CUE: thinking immediately;
  if TTS synthesis of first sentence > 1,100ms, play cached filler first.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Protocol

from app.schemas.events import (
    AvatarCueEvent,
    BoardOp,
    DataChannelEvent,
    InterruptFlushEvent,
    PlayoutPauseEvent,
    PlayoutResumeEvent,
)
from app.voice.backchannel_guard import GuardVerdict, classify
from app.voice.stt import STTClient
from app.voice.tts import PCMCursor


class ControllerState(str, Enum):
    IDLE = "IDLE"
    PLAYING = "PLAYING"
    SOFT_DUCKED = "SOFT_DUCKED"


class Clock(Protocol):
    def time(self) -> float:
        ...


class SystemClock:
    def time(self) -> float:
        return time.monotonic()


class FakeClock:
    """Controllable clock for deterministic latency masking tests."""

    def __init__(self, start_time: float = 0.0) -> None:
        self._current_time = start_time

    def time(self) -> float:
        return self._current_time

    def advance(self, seconds: float) -> None:
        self._current_time += seconds


class BargeInController:
    """State machine managing two-stage barge-in and latency masking."""

    def __init__(
        self,
        stt: STTClient,
        cursor: PCMCursor,
        clock: Clock | None = None,
        on_emit_event: (
            Callable[[DataChannelEvent], None | Awaitable[None]] | None
        ) = None,
        on_cancel_in_flight: Callable[[], None] | None = None,
        on_pause_playout: Callable[[], None] | None = None,
        on_resume_playout: Callable[[int], None] | None = None,
        on_interrupt_qa: Callable[[str], None | Awaitable[None]] | None = None,
    ) -> None:
        self.stt = stt
        self.cursor = cursor
        self.clock: Clock = clock if clock is not None else SystemClock()
        self.on_emit_event = on_emit_event
        self.on_cancel_in_flight = on_cancel_in_flight
        self.on_pause_playout = on_pause_playout
        self.on_resume_playout = on_resume_playout
        self.on_interrupt_qa = on_interrupt_qa

        self.state: ControllerState = ControllerState.IDLE
        self.active_turn_id: int = 0
        self.speech_start_ms: float | None = None

        self.unplayed_text: list[str] = []
        self.unrendered_board_ops: list[BoardOp] = []
        self.resume_stack: list[dict[str, Any]] = []

        self.emitted_events: list[DataChannelEvent] = []
        self.cancel_hooks_called: int = 0

    async def _emit(self, event: DataChannelEvent) -> None:
        self.emitted_events.append(event)
        if self.on_emit_event is not None:
            res = self.on_emit_event(event)
            if inspect.isawaitable(res):
                await res

    def start_turn(
        self,
        turn_id: int,
        unplayed_text: list[str] | None = None,
        unrendered_board_ops: list[BoardOp] | None = None,
    ) -> None:
        """Start a new teaching playout turn."""
        self.active_turn_id = turn_id
        self.state = ControllerState.PLAYING
        self.cursor.reset(turn_id)
        self.unplayed_text = list(unplayed_text or [])
        self.unrendered_board_ops = list(unrendered_board_ops or [])
        self.speech_start_ms = None

    def on_vad_speech_start(self, timestamp_ms: float) -> None:
        """Student microphone audio went above VAD energy gate."""
        self.speech_start_ms = timestamp_ms

    async def on_vad_speech_tick(self, timestamp_ms: float) -> None:
        """Periodic tick during speech to evaluate the 200ms soft-duck gate."""
        if self.state == ControllerState.PLAYING and self.speech_start_ms is not None:
            if (timestamp_ms - self.speech_start_ms) >= 200.0:
                # Stage 1: Soft Duck
                self.state = ControllerState.SOFT_DUCKED
                if self.on_pause_playout is not None:
                    self.on_pause_playout()
                pause_ev = PlayoutPauseEvent(turn_id=self.active_turn_id)
                await self._emit(pause_ev)

    async def on_vad_speech_end(
        self,
        timestamp_ms: float,
        audio_pcm: bytes,
    ) -> GuardVerdict:
        """Student speech ended; evaluate STT and execute Stage 1 or Stage 2."""
        self.speech_start_ms = None

        # Latency masking: emit AVATAR_CUE: thinking immediately
        await self._emit(AvatarCueEvent(cue="thinking"))

        # Transcribe student utterance
        stt_result = await self.stt.transcribe(audio_pcm)

        # Classify via Backchannel & Hallucination Guard
        verdict = classify(
            stt_result.text,
            no_speech_prob=stt_result.no_speech_prob,
            avg_logprob=stt_result.avg_logprob,
        )

        if verdict in (GuardVerdict.BACKCHANNEL, GuardVerdict.NOISE):
            # Backchannel or noise -> Soft duck recovery
            if self.state == ControllerState.SOFT_DUCKED:
                rewind_ms = self.cursor.rewind_ms(200)
                self.state = ControllerState.PLAYING
                if self.on_resume_playout is not None:
                    self.on_resume_playout(rewind_ms)
                resume_ev = PlayoutResumeEvent(
                    turn_id=self.active_turn_id,
                    rewind_ms=rewind_ms,
                )
                await self._emit(resume_ev)
                await self._emit(AvatarCueEvent(cue="speaking"))
            elif self.state == ControllerState.PLAYING:
                await self._emit(AvatarCueEvent(cue="speaking"))
            return verdict

        # REAL_QUESTION -> Stage 2 (Hard Commit)
        self.active_turn_id += 1
        self.state = ControllerState.IDLE

        # Cancel in-flight LLM/TTS tasks immediately
        self.cancel_hooks_called += 1
        if self.on_cancel_in_flight is not None:
            self.on_cancel_in_flight()

        # Emit INTERRUPT_FLUSH carrying the new_turn_id
        flush_ev = InterruptFlushEvent(new_turn_id=self.active_turn_id)
        await self._emit(flush_ev)

        # Push unplayed items and unrendered board ops to resume_stack
        ops_payload: list[dict[str, Any]] = [
            op.model_dump() if hasattr(op, "model_dump") else dict(op)  # type: ignore[arg-type]
            for op in self.unrendered_board_ops
        ]
        stack_frame: dict[str, Any] = {
            "turn_id": self.active_turn_id - 1,
            "unplayed_text": list(self.unplayed_text),
            "unrendered_board_ops": ops_payload,
            "played_ms": self.cursor.played_ms,
        }
        self.resume_stack.append(stack_frame)

        # Route to INTERRUPT_QA
        if self.on_interrupt_qa is not None:
            res = self.on_interrupt_qa(stt_result.text)
            if inspect.isawaitable(res):
                await res

        return verdict

    def should_play_filler(self, tts_start_time_s: float) -> bool:
        """Decide whether to play cached filler clip if TTS exceeds 1,100ms."""
        elapsed_ms = (self.clock.time() - tts_start_time_s) * 1000.0
        return elapsed_ms > 1100.0
