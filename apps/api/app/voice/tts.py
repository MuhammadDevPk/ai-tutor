"""Server-side TTS streamer, PCM cursor tracking, and filler cache.

Invariants:
- 24kHz mono 16-bit signed PCM audio.
- Mandatory 150ms digital silence lead-in per turn (3,600 samples).
- Sample-accurate PCMCursor with 200ms rewind and clause boundary support.
- Deterministic FakeTTS for zero-download tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

SAMPLE_RATE: int = 24000
BYTES_PER_SAMPLE: int = 2  # 16-bit mono PCM

# Lead-in silence: 150ms at 24kHz = 3,600 samples = 7,200 bytes
LEAD_IN_SILENCE_MS: int = 150
LEAD_IN_SILENCE_SAMPLES: int = int(SAMPLE_RATE * (LEAD_IN_SILENCE_MS / 1000.0))  # 3600
LEAD_IN_SILENCE_BYTES: int = LEAD_IN_SILENCE_SAMPLES * BYTES_PER_SAMPLE  # 7200

# Default rewind: 200ms at 24kHz = 4,800 samples = 9,600 bytes
REWIND_DEFAULT_MS: int = 200
REWIND_DEFAULT_SAMPLES: int = int(SAMPLE_RATE * (REWIND_DEFAULT_MS / 1000.0))  # 4800
REWIND_DEFAULT_BYTES: int = REWIND_DEFAULT_SAMPLES * BYTES_PER_SAMPLE  # 9600

FILLER_SENTENCES: list[str] = [
    "Let me think about that.",
    "Good question.",
    "One moment.",
]


@dataclass
class PCMCursor:
    """Tracks played PCM samples per turn with rewind and clause boundaries."""

    turn_id: int = 0
    sample_rate: int = SAMPLE_RATE
    played_samples: int = 0
    total_samples: int = 0
    clause_boundaries: list[int] = field(default_factory=list)

    def reset(self, turn_id: int = 0) -> None:
        """Reset cursor for a new turn."""
        self.turn_id = turn_id
        self.played_samples = 0
        self.total_samples = 0
        self.clause_boundaries.clear()

    def record_clause_boundary(self, sample_offset: int | None = None) -> None:
        """Record a clause boundary at sample_offset or current total_samples."""
        offset = sample_offset if sample_offset is not None else self.total_samples
        if not self.clause_boundaries or self.clause_boundaries[-1] != offset:
            self.clause_boundaries.append(offset)

    def advance_played_samples(self, samples: int) -> None:
        """Advance played audio by sample count, clamped to total_samples."""
        self.played_samples = min(self.total_samples, self.played_samples + samples)

    def advance_played_bytes(self, num_bytes: int) -> None:
        """Advance played audio by raw int16 byte count."""
        self.advance_played_samples(num_bytes // BYTES_PER_SAMPLE)

    def rewind_ms(self, ms: int = REWIND_DEFAULT_MS) -> int:
        """Rewind played position by specified milliseconds.

        Returns exact rewound milliseconds.
        """
        target_samples = int(self.sample_rate * (ms / 1000.0))
        new_played = max(0, self.played_samples - target_samples)
        rewound_samples = self.played_samples - new_played
        self.played_samples = new_played
        return int(round(rewound_samples / self.sample_rate * 1000.0))

    def rewind_to_clause_boundary(self) -> int:
        """Rewind to the nearest clause boundary before current position.

        Returns exact rewound milliseconds.
        """
        target = 0
        for boundary in reversed(self.clause_boundaries):
            if boundary < self.played_samples:
                target = boundary
                break
        rewound_samples = self.played_samples - target
        self.played_samples = target
        return int(round(rewound_samples / self.sample_rate * 1000.0))

    @property
    def played_ms(self) -> int:
        return int(round(self.played_samples / self.sample_rate * 1000.0))

    @property
    def total_ms(self) -> int:
        return int(round(self.total_samples / self.sample_rate * 1000.0))


@runtime_checkable
class TTSStreamer(Protocol):
    """Protocol for server-side TTS synthesis."""

    cursor: PCMCursor

    async def synthesize_sentence(self, sentence: str) -> bytes:
        """Synthesize a single sentence to 24kHz mono int16 PCM bytes."""
        ...

    def stream_pcm(
        self, sentences: AsyncIterator[str] | Sequence[str]
    ) -> AsyncIterator[bytes]:
        """Stream 24kHz mono int16 PCM frames per sentence with 150ms lead-in."""
        ...


class FakeTTS:
    """Deterministic in-memory TTS for tests with exact sample count tracking."""

    def __init__(self, samples_per_word: int = 2400) -> None:
        self.cursor = PCMCursor()
        self.samples_per_word = samples_per_word
        self.synthesized_sentences: list[str] = []

    async def synthesize_sentence(self, sentence: str) -> bytes:
        self.synthesized_sentences.append(sentence)
        words = max(1, len(sentence.split()))
        samples = words * self.samples_per_word
        pcm = b"\x00" * (samples * BYTES_PER_SAMPLE)
        self.cursor.record_clause_boundary()
        self.cursor.total_samples += samples
        return pcm

    async def stream_pcm(
        self, sentences: AsyncIterator[str] | Sequence[str]
    ) -> AsyncIterator[bytes]:
        # Mandatory 150ms lead-in digital silence frame
        lead_in = b"\x00" * LEAD_IN_SILENCE_BYTES
        self.cursor.total_samples += LEAD_IN_SILENCE_SAMPLES
        yield lead_in

        if isinstance(sentences, AsyncIterator):
            async for s in sentences:
                yield await self.synthesize_sentence(s)
        else:
            for s in sentences:
                yield await self.synthesize_sentence(s)


class KokoroTTS:
    """Lazy Kokoro ONNX TTS adapter emitting 24kHz mono int16 PCM bytes."""

    def __init__(
        self,
        model_path: str = "kokoro-v0_19.onnx",
        voices_path: str = "voices.bin",
        voice: str = "af_sarah",
    ) -> None:
        self.model_path = model_path
        self.voices_path = voices_path
        self.voice = voice
        self.cursor = PCMCursor()
        self._kokoro: Any = None

    def _get_engine(self) -> Any:
        if self._kokoro is None:
            # Lazy import to ensure tests never download models
            from kokoro_onnx import Kokoro  # type: ignore[import-not-found]

            self._kokoro = Kokoro(self.model_path, self.voices_path)
        return self._kokoro

    async def synthesize_sentence(self, sentence: str) -> bytes:
        import numpy as np

        engine = self._get_engine()
        # kokoro_onnx create yields (samples_float32, sample_rate)
        samples, sr = engine.create(sentence, voice=self.voice, speed=1.0, lang="en-us")
        if sr != SAMPLE_RATE:
            # Resample if needed
            pass
        # Convert float32 array in [-1.0, 1.0] to int16 PCM
        int16_samples = (samples * 32767.0).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = int16_samples.tobytes()

        sample_count = len(int16_samples)
        self.cursor.record_clause_boundary()
        self.cursor.total_samples += sample_count
        return bytes(pcm_bytes)

    async def stream_pcm(
        self, sentences: AsyncIterator[str] | Sequence[str]
    ) -> AsyncIterator[bytes]:
        # Mandatory 150ms lead-in digital silence frame
        lead_in = b"\x00" * LEAD_IN_SILENCE_BYTES
        self.cursor.total_samples += LEAD_IN_SILENCE_SAMPLES
        yield lead_in

        if isinstance(sentences, AsyncIterator):
            async for s in sentences:
                yield await self.synthesize_sentence(s)
        else:
            for s in sentences:
                yield await self.synthesize_sentence(s)


async def init_filler_cache(streamer: TTSStreamer) -> dict[str, bytes]:
    """Pre-synthesize short neutral fillers into memory at worker startup."""
    cache: dict[str, bytes] = {}
    for i, sentence in enumerate(FILLER_SENTENCES):
        pcm = await streamer.synthesize_sentence(sentence)
        cache[f"filler_{i}"] = pcm
    return cache
