"""Speech-to-text (STT) client protocols and implementations.

Provides:
- STTResult: transcribed text and acoustic confidence metrics
- STTClient: protocol
- FakeSTT: deterministic test fake
- GroqSTT: Whisper Large v3 Turbo via Groq Cloud API
- LocalWhisperSTT: fallback interface
"""

from __future__ import annotations

import io
import wave
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import httpx

from app.config import settings


@dataclass(frozen=True)
class STTResult:
    text: str
    no_speech_prob: float = 0.0
    avg_logprob: float = 0.0


@runtime_checkable
class STTClient(Protocol):
    async def transcribe(self, pcm_bytes: bytes) -> STTResult:
        """Transcribe 24kHz mono 16-bit PCM bytes into text and confidence scores."""
        ...


class FakeSTT:
    """Deterministic STT client for unit and integration testing."""

    def __init__(self, default_result: STTResult | None = None) -> None:
        self.default_result = default_result or STTResult(
            text="okay", no_speech_prob=0.0, avg_logprob=0.0
        )
        self.results_queue: list[STTResult] = []
        self.call_count: int = 0
        self.received_audio: list[bytes] = []

    def queue_result(self, result: STTResult) -> None:
        self.results_queue.append(result)

    async def transcribe(self, pcm_bytes: bytes) -> STTResult:
        self.call_count += 1
        self.received_audio.append(pcm_bytes)
        if self.results_queue:
            return self.results_queue.pop(0)
        return self.default_result


class GroqSTT:
    """Whisper Large v3 Turbo transcription via Groq Cloud API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.api_key = api_key or settings.GROQ_API_KEY
        self.base_url = (base_url or settings.GROQ_BASE_URL).rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def transcribe(self, pcm_bytes: bytes) -> STTResult:
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is not configured")

        # Encode 24kHz 16-bit mono PCM into WAV container
        wav_buffer = io.BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(pcm_bytes)
        wav_bytes = wav_buffer.getvalue()

        url = f"{self.base_url}/audio/transcriptions"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
        data = {
            "model": "whisper-large-v3-turbo",
            "response_format": "verbose_json",
        }

        client = await self._get_client()
        resp = await client.post(url, headers=headers, files=files, data=data)
        resp.raise_for_status()
        payload = resp.json()

        text = payload.get("text", "")
        segments = payload.get("segments", [])
        no_speech_prob = 0.0
        avg_logprob = 0.0
        if segments and isinstance(segments, list):
            first_seg = segments[0]
            if isinstance(first_seg, dict):
                no_speech_prob = float(first_seg.get("no_speech_prob", 0.0))
                avg_logprob = float(first_seg.get("avg_logprob", 0.0))

        return STTResult(
            text=text,
            no_speech_prob=no_speech_prob,
            avg_logprob=avg_logprob,
        )


class LocalWhisperSTT:
    """Offline fallback STT using faster-whisper or local whisper model."""

    def __init__(self, model_size: str = "base") -> None:
        self.model_size = model_size
        self._model: Any = None

    def _get_model(self) -> Any:
        if self._model is None:
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]

            self._model = WhisperModel(
                self.model_size, device="cpu", compute_type="int8"
            )
        return self._model

    async def transcribe(self, pcm_bytes: bytes) -> STTResult:
        # Placeholder for local offline fallback
        return STTResult(text="", no_speech_prob=1.0, avg_logprob=-2.0)
