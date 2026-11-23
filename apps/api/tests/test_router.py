"""Unit tests for ModelBucketRouter and Provider waterfall logic."""

from types import SimpleNamespace

import pytest

from app.llm.providers import (
    ChatMessage,
    FakeProvider,
    ProviderError,
)
from app.llm.router import (
    LLMRouter,
    RoutedDelta,
    RouterEvent,
    StreamInterrupted,
)


@pytest.mark.asyncio
async def test_failover_on_429_before_first_delta():
    """Failover on 429 before first delta reaches the second provider, and logs it."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        fail_status_code=429,
        fail_after_n_deltas=0,
        error_message="Rate limit exceeded TPM",
    )
    p2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["Hello ", "world!"],
    )
    events_logged: list[RouterEvent] = []
    router = LLMRouter(providers=[p1, p2], on_event=events_logged.append)

    messages = [ChatMessage(role="user", content="Hi")]
    deltas: list[RoutedDelta] = []
    async for d in router.stream(messages):
        deltas.append(d)

    # Reached second provider
    assert [d.text for d in deltas] == ["Hello ", "world!"]
    assert all(
        d.provider == "groq" and d.model == "openai/gpt-oss-120b" for d in deltas
    )

    # Event log recorded try, failover, try, success
    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "failover", "try", "success"]
    assert router.events[0].model == "openai/gpt-oss-20b"
    assert router.events[1].model == "openai/gpt-oss-20b"
    assert router.events[1].status_code == 429
    assert router.events[2].model == "openai/gpt-oss-120b"
    assert router.events[3].model == "openai/gpt-oss-120b"
    assert events_logged == router.events


@pytest.mark.asyncio
async def test_503_from_gemini_fake_fails_over():
    """503 from Gemini fake fails over transparently to next provider."""
    p1 = FakeProvider(
        name="gemini",
        model="gemini-3.8-flash",
        fail_status_code=503,
        fail_after_n_deltas=0,
        error_message="Service Unavailable",
    )
    p2 = FakeProvider(
        name="gemini",
        model="gemini-3.5-flash-lite",
        deltas=["Gemini fallback response"],
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Explain variance")]
    deltas = [d async for d in router.stream(messages)]

    assert len(deltas) == 1
    assert deltas[0].text == "Gemini fallback response"
    assert deltas[0].model == "gemini-3.5-flash-lite"

    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "failover", "try", "success"]
    assert router.events[1].status_code == 503


@pytest.mark.asyncio
async def test_401_raises_immediately_no_second_provider_tried():
    """Hard 4xx error (non-429) raises immediately without trying next provider."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        fail_status_code=401,
        fail_after_n_deltas=0,
        error_message="Invalid API Key",
    )
    p2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["Should never be called"],
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Hello")]
    with pytest.raises(ProviderError) as exc_info:
        async for _ in router.stream(messages):
            pass

    assert exc_info.value.status_code == 401
    tried_models = [e.model for e in router.events if e.event_type == "try"]
    assert tried_models == ["openai/gpt-oss-20b"]
    assert not any(e.model == "openai/gpt-oss-120b" for e in router.events)


@pytest.mark.asyncio
async def test_failure_after_2_deltas_raises_stream_interrupted():
    """Failure mid-stream raises StreamInterrupted with partial text (no switch)."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        deltas=["Delta1 ", "Delta2 ", "Delta3 "],
        fail_status_code=500,
        fail_after_n_deltas=2,
        error_message="Connection drop mid-stream",
    )
    p2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["Duplicate lecture content if switched"],
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Teach step 1")]
    received: list[RoutedDelta] = []
    with pytest.raises(StreamInterrupted) as exc_info:
        async for delta in router.stream(messages):
            received.append(delta)

    assert [d.text for d in received] == ["Delta1 ", "Delta2 "]
    assert exc_info.value.partial_text == "Delta1 Delta2 "
    # Second provider was NOT invoked
    assert not any(e.model == "openai/gpt-oss-120b" for e in router.events)
    # Recorded interrupted event
    assert any(e.event_type == "interrupted" for e in router.events)


def test_unconfigured_providers_skipped():
    """Unconfigured providers (empty API keys or URLs) are skipped silently."""
    mock_settings = SimpleNamespace(
        GROQ_API_KEY="test_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GEMINI_API_KEY="",  # Unconfigured
        OLLAMA_BASE_URL="",  # Unconfigured
        LLM_REQUEST_TIMEOUT_S=60.0,
    )
    router = LLMRouter(settings_obj=mock_settings)
    providers = router.get_providers(size_hint="small")

    assert len(providers) == 3
    assert all(p.name == "groq" for p in providers)
    assert [p.model for p in providers] == [
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
    ]
    # Gemini and Ollama providers are absent
    assert not any(p.name == "gemini" for p in providers)
    assert not any(p.name == "ollama" for p in providers)


def test_large_hint_starts_at_gpt_oss_120b():
    """Large task-size hint starts at gpt-oss-120b instead of 20b."""
    mock_settings = SimpleNamespace(
        GROQ_API_KEY="test_groq_key",
        GROQ_BASE_URL="https://api.groq.com/openai/v1",
        GEMINI_API_KEY="test_gemini_key",
        OLLAMA_BASE_URL="http://localhost:11434",
        LLM_REQUEST_TIMEOUT_S=60.0,
    )
    router = LLMRouter(settings_obj=mock_settings)
    providers = router.get_providers(size_hint="large")

    models = [p.model for p in providers]
    # Starts at 120b, then qwen3.8-27b, then Gemini models, then Ollama
    assert models[0] == "openai/gpt-oss-120b"
    assert models[1] == "qwen/qwen3.8-27b"
    assert models[2] == "gemini-3.8-flash"
    assert models[3] == "gemini-3.5-flash-lite"
    assert models[4] == "qwen3.8-27b"  # ollama
    # gpt-oss-20b is not present in large bucket
    assert "openai/gpt-oss-20b" not in models


def test_custom_providers_large_hint_reordering():
    """Custom providers passed to LLMRouter respect the large hint starting at 120b."""
    p_20b = FakeProvider(name="groq", model="openai/gpt-oss-20b")
    p_120b = FakeProvider(name="groq", model="openai/gpt-oss-120b")
    p_gemini = FakeProvider(name="gemini", model="gemini-3.8-flash")

    router = LLMRouter(providers=[p_20b, p_120b, p_gemini])
    large_providers = router.get_providers(size_hint="large")

    models = [p.model for p in large_providers]
    assert models == ["openai/gpt-oss-120b", "gemini-3.8-flash"]
    assert "openai/gpt-oss-20b" not in models
