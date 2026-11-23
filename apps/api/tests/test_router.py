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


@pytest.mark.asyncio
async def test_empty_stream_fails_over_to_next_provider():
    """A provider returning 0 deltas fails over to next healthy provider."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        deltas=[],  # 0 deltas returned
    )
    p2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["Response after empty failover"],
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Explain variance")]
    deltas = [d.text async for d in router.stream(messages)]

    assert deltas == ["Response after empty failover"]
    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "failover", "try", "success"]
    assert "empty response" in (router.events[1].error or "").lower()


@pytest.mark.asyncio
async def test_all_providers_exhausted_raises_provider_error():
    """When all providers fail or return 429, ProviderError is raised."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        fail_status_code=429,
        fail_after_n_deltas=0,
    )
    p2 = FakeProvider(
        name="gemini",
        model="gemini-3.8-flash",
        fail_status_code=503,
        fail_after_n_deltas=0,
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Hello")]
    with pytest.raises(ProviderError):
        async for _ in router.stream(messages):
            pass

    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "failover", "try", "failover"]


@pytest.mark.asyncio
async def test_http_status_error_extracts_status_code_for_hard_fail():
    """An exception with response.status_code=403 triggers hard_fail immediately."""
    import httpx

    class FailingProvider:
        name = "mock"
        model = "mock-model"

        async def stream(self, messages):
            if False:
                yield ""
            req = httpx.Request(
                "POST", "https://api.groq.com/openai/v1/chat/completions"
            )
            resp = httpx.Response(403, request=req)
            raise httpx.HTTPStatusError("Forbidden", request=req, response=resp)

    p1 = FailingProvider()
    p2 = FakeProvider(
        name="groq", model="openai/gpt-oss-120b", deltas=["Never reached"]
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Hello")]
    with pytest.raises(httpx.HTTPStatusError):
        async for _ in router.stream(messages):
            pass

    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "hard_fail"]
    assert router.events[1].status_code == 403


@pytest.mark.asyncio
async def test_empty_deltas_do_not_block_failover():
    """Empty string deltas do not count toward emitted content; failover succeeds."""
    p1 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-20b",
        deltas=["", ""],  # only empty deltas
        fail_status_code=500,
        fail_after_n_deltas=1,
    )
    p2 = FakeProvider(
        name="groq",
        model="openai/gpt-oss-120b",
        deltas=["Real text after empty deltas"],
    )
    router = LLMRouter(providers=[p1, p2])

    messages = [ChatMessage(role="user", content="Hello")]
    deltas = [d.text async for d in router.stream(messages)]
    assert deltas == ["Real text after empty deltas"]
    event_types = [e.event_type for e in router.events]
    assert event_types == ["try", "failover", "try", "success"]


@pytest.mark.asyncio
async def test_groq_provider_sse_parsing_and_done():
    """GroqProvider parses both 'data: ' and 'data:' SSE lines and breaks on [DONE]."""
    import httpx

    from app.llm.providers import GroqProvider

    sse_body = (
        'data: {"choices": [{"delta": {"content": "Hello"}}]}\n\n'
        'data:{"choices": [{"delta": {"content": " world"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    def handler(request):
        return httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    provider = GroqProvider(model="openai/gpt-oss-20b", api_key="fake-key")

    # Monkeypatch AsyncClient to use mock transport
    orig_client = httpx.AsyncClient
    try:

        def mock_client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_client(*args, **kwargs)

        httpx.AsyncClient = mock_client_factory
        results = [
            d async for d in provider.stream([ChatMessage(role="user", content="Hi")])
        ]
        assert results == ["Hello", " world"]
    finally:
        httpx.AsyncClient = orig_client


@pytest.mark.asyncio
async def test_groq_provider_error_in_sse_raises():
    """GroqProvider raises ProviderError when error payload is received in SSE body."""
    import httpx

    from app.llm.providers import GroqProvider

    sse_body = (
        'data: {"error": {"message": "Rate limit exceeded", '
        '"code": "rate_limit_exceeded"}}\n\n'
    )

    def handler(request):
        return httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    provider = GroqProvider(model="openai/gpt-oss-20b", api_key="fake-key")

    orig_client = httpx.AsyncClient
    try:

        def mock_client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_client(*args, **kwargs)

        httpx.AsyncClient = mock_client_factory
        with pytest.raises(ProviderError) as exc_info:
            async for _ in provider.stream([ChatMessage(role="user", content="Hi")]):
                pass
        assert exc_info.value.status_code == 429
        assert "Rate limit exceeded" in exc_info.value.message
    finally:
        httpx.AsyncClient = orig_client


@pytest.mark.asyncio
async def test_gemini_provider_safety_block_raises():
    """GeminiProvider raises ProviderError(status_code=400) on SAFETY block."""
    import httpx

    from app.llm.providers import GeminiProvider

    sse_body = 'data: {"candidates": [{"finishReason": "SAFETY"}]}\n\n'

    def handler(request):
        return httpx.Response(
            200, text=sse_body, headers={"content-type": "text/event-stream"}
        )

    transport = httpx.MockTransport(handler)
    provider = GeminiProvider(model="gemini-3.8-flash", api_key="fake-key")

    orig_client = httpx.AsyncClient
    try:

        def mock_client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_client(*args, **kwargs)

        httpx.AsyncClient = mock_client_factory
        with pytest.raises(ProviderError) as exc_info:
            async for _ in provider.stream([ChatMessage(role="user", content="Hi")]):
                pass
        assert exc_info.value.status_code == 400
        assert "SAFETY" in exc_info.value.message
    finally:
        httpx.AsyncClient = orig_client


@pytest.mark.asyncio
async def test_ollama_provider_error_in_body_raises():
    """OllamaProvider raises ProviderError on error in response body."""
    import httpx

    from app.llm.providers import OllamaProvider

    body = '{"error": "model not found"}\n'

    def handler(request):
        return httpx.Response(
            200, text=body, headers={"content-type": "application/x-ndjson"}
        )

    transport = httpx.MockTransport(handler)
    provider = OllamaProvider(model="qwen3.8-27b", base_url="http://localhost:11434")

    orig_client = httpx.AsyncClient
    try:

        def mock_client_factory(*args, **kwargs):
            kwargs["transport"] = transport
            return orig_client(*args, **kwargs)

        httpx.AsyncClient = mock_client_factory
        with pytest.raises(ProviderError) as exc_info:
            async for _ in provider.stream([ChatMessage(role="user", content="Hi")]):
                pass
        assert exc_info.value.status_code == 500
        assert "model not found" in exc_info.value.message
    finally:
        httpx.AsyncClient = orig_client
