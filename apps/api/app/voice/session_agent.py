"""LiveKit Session Agent driving the voice loop for a tutor room.

Coordinates:
- Subscribing to student microphone track & running Silero VAD
- Feeding speech events to BargeInController
- Streaming FSM teaching events (SAY to TTS, board directives to DataChannel)
- Publishing 24kHz mono PCM audio frames to LiveKit AudioSource
- Decoupled from physical I/O so unit and integration tests run entirely with fakes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any
from uuid import UUID

from app.llm.stream_parser import (
    ClearEvent,
    CtrlEvent,
    DiagramEvent,
    LatexEvent,
    ParsedEvent,
    PlotEvent,
    SayEvent,
)
from app.schemas.events import (
    AudioSegmentStartEvent,
    BoardOp,
    BoardScheduleEvent,
    DataChannelEvent,
)
from app.tutor.fsm import StateEvent
from app.tutor.service import TutorService
from app.voice.barge_in import BargeInController
from app.voice.stt import STTClient
from app.voice.tts import (
    BYTES_PER_SAMPLE,
    LEAD_IN_SILENCE_BYTES,
    LEAD_IN_SILENCE_SAMPLES,
    SAMPLE_RATE,
    TTSStreamer,
    init_filler_cache,
)

logger = logging.getLogger(__name__)

# 20ms frame chunking at 24kHz mono 16-bit:
# 24,000 samples/sec * 0.020 sec = 480 samples = 960 bytes
FRAME_DURATION_MS: int = 20
SAMPLES_PER_FRAME: int = int(SAMPLE_RATE * (FRAME_DURATION_MS / 1000.0))  # 480
BYTES_PER_FRAME: int = SAMPLES_PER_FRAME * BYTES_PER_SAMPLE  # 960


class SessionAgent:
    """Voice session coordinator between LiveKit and TutorService."""

    def __init__(
        self,
        session_id: UUID,
        tutor_service: TutorService,
        tts: TTSStreamer,
        stt: STTClient,
        data_channel_sink: Callable[[DataChannelEvent], Any] | None = None,
        audio_frame_sink: Callable[[bytes], Any] | None = None,
    ) -> None:
        self.session_id = session_id
        self.tutor_service = tutor_service
        self.tts = tts
        self.stt = stt
        self.data_channel_sink = data_channel_sink
        self.audio_frame_sink = audio_frame_sink

        self.filler_cache: dict[str, bytes] = {}
        self.is_playing: bool = False
        self._playout_paused: bool = False
        self._current_task: asyncio.Task[None] | None = None
        self._op_counter: int = 0

        # Barge-in controller configured with hooks
        self.barge_in = BargeInController(
            stt=self.stt,
            cursor=self.tts.cursor,
            on_emit_event=self.emit_datachannel_event,
            on_cancel_in_flight=self.cancel_in_flight,
            on_pause_playout=self.pause_playout,
            on_resume_playout=self.resume_playout,
            on_interrupt_qa=self.on_student_interrupt_qa,
        )

    async def initialize(self) -> None:
        """Pre-warm filler cache."""
        self.filler_cache = await init_filler_cache(self.tts)

    async def emit_datachannel_event(self, event: DataChannelEvent) -> None:
        """Publish a DataChannel event to student client."""
        if self.data_channel_sink is not None:
            res = self.data_channel_sink(event)
            if asyncio.iscoroutine(res):
                await res

    def cancel_in_flight(self) -> None:
        """Cancel active LLM stream and audio playout immediately."""
        self.is_playing = False
        self._playout_paused = False
        curr = asyncio.current_task()
        if (
            self._current_task
            and not self._current_task.done()
            and self._current_task != curr
        ):
            self._current_task.cancel()

    def pause_playout(self) -> None:
        """Freeze playout pumping on Stage 1 soft-duck."""
        self._playout_paused = True

    def resume_playout(self, rewind_ms: int) -> None:
        """Unfreeze playout pumping on Stage 1 resume."""
        self._playout_paused = False

    async def on_student_interrupt_qa(self, question_text: str) -> None:
        """Dispatch student question to FSM INTERRUPT_QA path."""
        # Ensure any existing playout task is cancelled and awaited
        self.cancel_in_flight()
        if self._current_task and not self._current_task.done():
            try:
                await self._current_task
            except (asyncio.CancelledError, Exception):
                pass

        generator = self.tutor_service.handle_student_message(
            self.session_id, question_text
        )
        self._current_task = asyncio.create_task(self.play_turn_events(generator))
        try:
            await self._current_task
        except asyncio.CancelledError:
            pass

    async def pump_audio_pcm(self, pcm_data: bytes) -> None:
        """Chunk raw PCM bytes into 20ms frames and pump to audio frame sink."""
        offset = 0
        total_len = len(pcm_data)
        while offset < total_len and self.is_playing:
            # Playout pause check (soft duck)
            while self._playout_paused and self.is_playing:
                await asyncio.sleep(0.02)

            if not self.is_playing:
                break

            chunk = pcm_data[offset : offset + BYTES_PER_FRAME]
            if len(chunk) < BYTES_PER_FRAME:
                chunk = chunk + b"\x00" * (BYTES_PER_FRAME - len(chunk))

            if self.audio_frame_sink is not None:
                res = self.audio_frame_sink(chunk)
                if asyncio.iscoroutine(res):
                    await res

            self.tts.cursor.advance_played_bytes(len(chunk))
            offset += BYTES_PER_FRAME
            # 20ms real-time delay (or yield in tests)
            await asyncio.sleep(0.001)

    async def play_turn_events(
        self, event_stream: AsyncIterator[ParsedEvent | StateEvent]
    ) -> None:
        """Consume FSM events, queue board ops, synthesize speech, and pump audio."""
        if self._current_task is None or self._current_task.done():
            self._current_task = asyncio.current_task()

        self.is_playing = True
        self._playout_paused = False
        turn_id = self.barge_in.active_turn_id

        # Mandatory lead-in silence: 150ms
        self.barge_in.start_turn(turn_id)
        self.tts.cursor.total_samples += LEAD_IN_SILENCE_SAMPLES
        lead_in_pcm = b"\x00" * LEAD_IN_SILENCE_BYTES
        await self.pump_audio_pcm(lead_in_pcm)

        board_ops: list[BoardOp] = []
        first_say = True
        turn_start_s = self.barge_in.clock.time()

        async for ev in event_stream:
            if not self.is_playing:
                break

            if isinstance(ev, SayEvent):
                self.barge_in.unplayed_text.append(ev.text)
                pcm_bytes = await self.tts.synthesize_sentence(ev.text)
                if not self.is_playing:
                    break

                if first_say:
                    first_say = False
                    if (
                        self.barge_in.should_play_filler(turn_start_s)
                        and self.filler_cache
                    ):
                        # Synthesis exceeded 1,100ms: emit filler segment first
                        await self.emit_datachannel_event(
                            AudioSegmentStartEvent(
                                turn_id=turn_id, segment_id="filler"
                            )
                        )
                        filler_pcm = self.filler_cache.get("filler_0", b"")
                        if filler_pcm:
                            self.tts.cursor.total_samples += (
                                len(filler_pcm) // BYTES_PER_SAMPLE
                            )
                            await self.pump_audio_pcm(filler_pcm)

                    # Emit response segment
                    await self.emit_datachannel_event(
                        AudioSegmentStartEvent(turn_id=turn_id, segment_id="response")
                    )

                await self.pump_audio_pcm(pcm_bytes)
                if self.is_playing and ev.text in self.barge_in.unplayed_text:
                    self.barge_in.unplayed_text.remove(ev.text)

            elif isinstance(ev, (LatexEvent, PlotEvent, DiagramEvent, ClearEvent)):
                if first_say:
                    first_say = False
                    await self.emit_datachannel_event(
                        AudioSegmentStartEvent(turn_id=turn_id, segment_id="response")
                    )

                self._op_counter += 1
                op_type = (
                    "latex"
                    if isinstance(ev, LatexEvent)
                    else "plot"
                    if isinstance(ev, PlotEvent)
                    else "diagram"
                    if isinstance(ev, DiagramEvent)
                    else "clear"
                )
                payload: dict[str, Any] = {}
                if isinstance(ev, LatexEvent):
                    payload = {"latex": ev.latex}
                elif isinstance(ev, PlotEvent):
                    payload = {"spec": ev.spec}
                elif isinstance(ev, DiagramEvent):
                    payload = {"spec": ev.spec}
                elif isinstance(ev, ClearEvent):
                    payload = {}

                board_op = BoardOp(
                    op_id=f"op_{self._op_counter}",
                    op_type=op_type,
                    playout_offset_ms=self.tts.cursor.played_ms,
                    payload=payload,
                )
                board_ops.append(board_op)
                self.barge_in.unrendered_board_ops.append(board_op)

                # Emit BOARD_SCHEDULE immediately
                await self.emit_datachannel_event(
                    BoardScheduleEvent(
                        turn_id=turn_id,
                        layout_mode="standard",
                        operations=[board_op],
                    )
                )

            elif isinstance(ev, CtrlEvent):
                logger.debug("Tutor CtrlEvent received: %s", ev.payload)

        if first_say and self.is_playing:
            await self.emit_datachannel_event(
                AudioSegmentStartEvent(turn_id=turn_id, segment_id="response")
            )

        self.is_playing = False
