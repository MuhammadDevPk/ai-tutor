import pytest

from app.voice.tts import (
    BYTES_PER_SAMPLE,
    FILLER_SENTENCES,
    LEAD_IN_SILENCE_BYTES,
    LEAD_IN_SILENCE_MS,
    LEAD_IN_SILENCE_SAMPLES,
    REWIND_DEFAULT_BYTES,
    REWIND_DEFAULT_MS,
    REWIND_DEFAULT_SAMPLES,
    SAMPLE_RATE,
    FakeTTS,
    PCMCursor,
    init_filler_cache,
)


def test_audio_constants():
    assert SAMPLE_RATE == 24000
    assert BYTES_PER_SAMPLE == 2

    # 150ms lead-in: 24000 * 0.150 = 3600 samples = 7200 bytes
    assert LEAD_IN_SILENCE_MS == 150
    assert LEAD_IN_SILENCE_SAMPLES == 3600
    assert LEAD_IN_SILENCE_BYTES == 7200

    # 200ms rewind: 24000 * 0.200 = 4800 samples = 9600 bytes
    assert REWIND_DEFAULT_MS == 200
    assert REWIND_DEFAULT_SAMPLES == 4800
    assert REWIND_DEFAULT_BYTES == 9600


def test_cursor_advance_and_sample_tracking():
    cursor = PCMCursor(turn_id=1)
    assert cursor.played_samples == 0
    assert cursor.total_samples == 0

    cursor.total_samples = 10000
    cursor.advance_played_samples(2400)
    assert cursor.played_samples == 2400
    assert cursor.played_ms == 100

    cursor.advance_played_bytes(4800)  # 2400 samples
    assert cursor.played_samples == 4800
    assert cursor.played_ms == 200

    # Clamped to total_samples
    cursor.advance_played_samples(10000)
    assert cursor.played_samples == 10000


def test_cursor_200ms_rewind():
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 24000  # 1000ms
    cursor.played_samples = 12000  # 500ms

    # Rewind 200ms (4,800 samples)
    rewound_ms = cursor.rewind_ms(200)
    assert rewound_ms == 200
    assert cursor.played_samples == 7200  # 12000 - 4800
    assert cursor.played_ms == 300


def test_cursor_rewind_clamped_to_zero():
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 24000
    cursor.played_samples = 2400  # 100ms

    # Rewinding 200ms when only 100ms played should clamp to 0 and report 100ms
    rewound_ms = cursor.rewind_ms(200)
    assert rewound_ms == 100
    assert cursor.played_samples == 0
    assert cursor.played_ms == 0


def test_cursor_clause_boundary_rewind():
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 24000

    # Record boundaries at 0ms, 300ms (7200 samples), 700ms (16800 samples)
    cursor.record_clause_boundary(0)
    cursor.record_clause_boundary(7200)
    cursor.record_clause_boundary(16800)

    # Currently at 800ms (19200 samples)
    cursor.played_samples = 19200

    # Rewind to nearest clause boundary before 19200 -> should jump to 16800 (700ms)
    rewound_ms = cursor.rewind_to_clause_boundary()
    assert cursor.played_samples == 16800
    assert rewound_ms == 100  # 19200 - 16800 = 2400 samples = 100ms

    # Rewind again -> should jump to 7200 (300ms)
    rewound_ms_2 = cursor.rewind_to_clause_boundary()
    assert cursor.played_samples == 7200
    assert rewound_ms_2 == 400  # 16800 - 7200 = 9600 samples = 400ms


def test_cursor_reset():
    cursor = PCMCursor(turn_id=1)
    cursor.total_samples = 10000
    cursor.played_samples = 5000
    cursor.record_clause_boundary(2000)

    cursor.reset(turn_id=2)
    assert cursor.turn_id == 2
    assert cursor.played_samples == 0
    assert cursor.total_samples == 0
    assert cursor.clause_boundaries == []


@pytest.mark.asyncio
async def test_fake_tts_stream_pcm_lead_in_and_clauses():
    tts = FakeTTS(samples_per_word=2400)
    sentences = ["First sentence here.", "Second sentence follows."]

    frames = [f async for f in tts.stream_pcm(sentences)]

    # Frame 0 must be 150ms lead-in digital silence (7,200 bytes of zeros)
    assert len(frames) == 3
    assert len(frames[0]) == LEAD_IN_SILENCE_BYTES
    assert frames[0] == b"\x00" * LEAD_IN_SILENCE_BYTES

    # Frames 1 and 2 are synthesized sentences
    assert len(frames[1]) == 3 * 2400 * BYTES_PER_SAMPLE  # 3 words
    assert len(frames[2]) == 3 * 2400 * BYTES_PER_SAMPLE  # 3 words

    # Clause boundaries recorded
    assert len(tts.cursor.clause_boundaries) == 2


@pytest.mark.asyncio
async def test_init_filler_cache():
    tts = FakeTTS()
    cache = await init_filler_cache(tts)
    assert len(cache) == len(FILLER_SENTENCES)
    for i in range(len(FILLER_SENTENCES)):
        assert f"filler_{i}" in cache
        assert len(cache[f"filler_{i}"]) > 0
