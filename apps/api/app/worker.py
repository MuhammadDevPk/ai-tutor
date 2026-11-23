"""LiveKit Agents Worker process entrypoint for AI Video Tutor.

Run as an independent process:
    uv run python -m app.worker

Never run inside the FastAPI process.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from app.config import settings
from app.voice.session_agent import SAMPLES_PER_FRAME, SessionAgent
from app.voice.stt import GroqSTT
from app.voice.tts import KokoroTTS

logger = logging.getLogger("app.worker")


async def entrypoint(ctx: Any) -> None:
    """LiveKit Agents entrypoint invoked when a room job is assigned."""
    from livekit import rtc
    from livekit.agents import AutoSubscribe
    from livekit.agents.vad import VADEventType
    from livekit.plugins import silero

    logger.info("Connecting to LiveKit room %s", ctx.room.name)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    logger.info("Participant %s joined room %s", participant.identity, ctx.room.name)

    try:
        session_id = UUID(ctx.room.name)
    except ValueError:
        logger.error("Room name %s is not a valid UUID session ID", ctx.room.name)
        return

    # Create 24kHz mono AudioSource and publish track
    audio_source = rtc.AudioSource(sample_rate=24000, num_channels=1)
    track = rtc.LocalAudioTrack.create_audio_track("tutor-speech", audio_source)
    await ctx.room.local_participant.publish_track(track)

    from app.tutor.service import TutorService

    tts = KokoroTTS()
    stt = GroqSTT()
    tutor_service = TutorService()

    async def send_datachannel(event: Any) -> None:
        payload = (
            event.model_dump_json().encode("utf-8")
            if hasattr(event, "model_dump_json")
            else json.dumps(event).encode("utf-8")
        )
        await ctx.room.local_participant.publish_data(payload, reliable=True)

    async def send_audio_frame(frame_bytes: bytes) -> None:
        frame = rtc.AudioFrame(
            data=frame_bytes,
            sample_rate=24000,
            num_channels=1,
            samples_per_channel=SAMPLES_PER_FRAME,
        )
        await audio_source.capture_frame(frame)

    agent = SessionAgent(
        session_id=session_id,
        tutor_service=tutor_service,
        tts=tts,
        stt=stt,
        data_channel_sink=send_datachannel,
        audio_frame_sink=send_audio_frame,
    )
    await agent.initialize()

    # Silero VAD stream subscription
    vad = silero.VAD.load()
    background_tasks: set[asyncio.Task[Any]] = set()

    @ctx.room.on("track_subscribed")
    def on_track_subscribed(
        track: rtc.Track,
        publication: rtc.TrackPublication,
        participant: rtc.RemoteParticipant,
    ) -> None:
        if track.kind == rtc.TrackKind.KIND_AUDIO:
            audio_stream = rtc.AudioStream(track)

            async def process_student_audio() -> None:
                vad_stream = vad.stream()

                async def feed_audio() -> None:
                    try:
                        async for event in audio_stream:
                            vad_stream.push_frame(event.frame)
                    finally:
                        vad_stream.end_input()

                feed_task = asyncio.create_task(feed_audio())
                try:
                    async for vad_event in vad_stream:
                        if vad_event.type == VADEventType.START_OF_SPEECH:
                            agent.barge_in.on_vad_speech_start(
                                vad_event.timestamp * 1000.0
                            )
                        elif vad_event.type == VADEventType.INFERENCE_DONE:
                            if vad_event.speaking:
                                await agent.barge_in.on_vad_speech_tick(
                                    vad_event.timestamp * 1000.0
                                )
                        elif vad_event.type == VADEventType.END_OF_SPEECH:
                            pcm_data = b"".join(
                                f.data.tobytes() for f in vad_event.frames
                            )
                            await agent.barge_in.on_vad_speech_end(
                                vad_event.timestamp * 1000.0,
                                pcm_data,
                            )
                except Exception as exc:
                    logger.exception("Error in student audio processing: %s", exc)
                finally:
                    feed_task.cancel()
                    try:
                        await feed_task
                    except (asyncio.CancelledError, Exception):
                        pass

            task = asyncio.create_task(process_student_audio())
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)

    # Start initial lesson turn
    generator = tutor_service.handle_student_message(session_id, "")
    await agent.play_turn_events(generator)


def main() -> None:
    from livekit.agents import WorkerOptions, cli

    logging.basicConfig(level=logging.INFO)
    ws_url = settings.LIVEKIT_URL or "ws://localhost:7880"
    api_key = settings.LIVEKIT_API_KEY or "devkey"
    api_secret = settings.LIVEKIT_API_SECRET or "secret_key_at_least_16_chars_long"

    options = WorkerOptions(
        entrypoint_fnc=entrypoint,
        ws_url=ws_url,
        api_key=api_key,
        api_secret=api_secret,
    )
    cli.run_app(options)


if __name__ == "__main__":
    main()
