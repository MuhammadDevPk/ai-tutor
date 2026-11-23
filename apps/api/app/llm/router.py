"""Model-bucket LLM router with transparent failover and quota governance."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Callable

from app.config import settings
from app.llm.providers import (
    ChatMessage,
    ChatProvider,
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    ProviderError,
)


@dataclass(frozen=True)
class RoutedDelta:
    """A streaming text delta annotated with the producing provider and model."""

    text: str
    provider: str
    model: str


class StreamInterrupted(Exception):
    """Raised when a stream fails mid-stream after yielding one or more deltas.

    Per architectural invariants, failover mid-stream is prohibited to prevent
    duplicate lecture content.
    """

    def __init__(self, message: str, partial_text: str) -> None:
        super().__init__(message)
        self.message = message
        self.partial_text = partial_text

    def __str__(self) -> str:
        return f"{self.message} (partial_text_len={len(self.partial_text)})"


@dataclass
class RouterEvent:
    """Audit log entry recorded during LLM routing and failover."""

    event_type: str  # "try", "failover", "hard_fail", "interrupted", "success"
    provider: str
    model: str
    status_code: int | None = None
    error: str | None = None


SMALL_BUCKET_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "ollama",
]

LARGE_BUCKET_MODELS = [
    "openai/gpt-oss-120b",
    "qwen/qwen3.8-27b",
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "ollama",
]


class LLMRouter:
    """Waterfall model-bucket router with transparent pre-delta failover."""

    def __init__(
        self,
        providers: list[ChatProvider] | None = None,
        on_event: Callable[[RouterEvent], None] | None = None,
        settings_obj: Any = None,
    ) -> None:
        self.custom_providers = providers
        self.on_event = on_event
        self.events: list[RouterEvent] = []
        self._settings = settings_obj if settings_obj is not None else settings

    def _record_event(self, event: RouterEvent) -> None:
        self.events.append(event)
        if self.on_event is not None:
            self.on_event(event)

    def get_providers(self, size_hint: str = "small") -> list[ChatProvider]:
        """Return the active provider chain ordered for the requested task size hint."""
        if self.custom_providers is not None:
            if size_hint == "large":
                # If custom providers include known bucket models, adjust for large hint
                has_known = any(
                    p.model in LARGE_BUCKET_MODELS or p.model == "openai/gpt-oss-20b"
                    for p in self.custom_providers
                )
                if has_known:
                    filtered = [
                        p
                        for p in self.custom_providers
                        if p.model != "openai/gpt-oss-20b"
                    ]

                    def sort_key(p: ChatProvider) -> int:
                        try:
                            return LARGE_BUCKET_MODELS.index(p.model)
                        except ValueError:
                            return 999

                    return sorted(filtered, key=sort_key)
            return list(self.custom_providers)

        chain: list[ChatProvider] = []

        # Tier 1: Groq Cloud (single key, three independent model buckets)
        groq_key = getattr(self._settings, "GROQ_API_KEY", "")
        if groq_key:
            groq_url = getattr(
                self._settings, "GROQ_BASE_URL", "https://api.groq.com/openai/v1"
            )
            timeout = getattr(self._settings, "LLM_REQUEST_TIMEOUT_S", 60.0)
            if size_hint == "large":
                chain.append(
                    GroqProvider(
                        model="openai/gpt-oss-120b",
                        api_key=groq_key,
                        base_url=groq_url,
                        timeout=timeout,
                    )
                )
                chain.append(
                    GroqProvider(
                        model="qwen/qwen3.8-27b",
                        api_key=groq_key,
                        base_url=groq_url,
                        timeout=timeout,
                    )
                )
            else:
                chain.append(
                    GroqProvider(
                        model="openai/gpt-oss-20b",
                        api_key=groq_key,
                        base_url=groq_url,
                        timeout=timeout,
                    )
                )
                chain.append(
                    GroqProvider(
                        model="openai/gpt-oss-120b",
                        api_key=groq_key,
                        base_url=groq_url,
                        timeout=timeout,
                    )
                )
                chain.append(
                    GroqProvider(
                        model="qwen/qwen3.8-27b",
                        api_key=groq_key,
                        base_url=groq_url,
                        timeout=timeout,
                    )
                )

        # Tier 2: Google AI Studio (free tier)
        gemini_key = getattr(self._settings, "GEMINI_API_KEY", "")
        if gemini_key:
            timeout = getattr(self._settings, "LLM_REQUEST_TIMEOUT_S", 60.0)
            chain.append(
                GeminiProvider(
                    model="gemini-3.8-flash",
                    api_key=gemini_key,
                    timeout=timeout,
                )
            )
            chain.append(
                GeminiProvider(
                    model="gemini-3.5-flash-lite",
                    api_key=gemini_key,
                    timeout=timeout,
                )
            )

        # Tier 3: Local Ollama (offline emergency fallback)
        ollama_url = getattr(self._settings, "OLLAMA_BASE_URL", "")
        if ollama_url:
            timeout = getattr(self._settings, "LLM_REQUEST_TIMEOUT_S", 60.0)
            chain.append(
                OllamaProvider(
                    model="qwen3.8-27b",
                    base_url=ollama_url,
                    timeout=timeout,
                )
            )

        return chain

    async def stream(
        self,
        messages: list[ChatMessage],
        size_hint: str = "small",
    ) -> AsyncIterator[RoutedDelta]:
        """Stream response deltas from the highest priority healthy model bucket."""
        providers = self.get_providers(size_hint=size_hint)
        if not providers:
            raise ProviderError(
                "No LLM providers configured or available", status_code=503
            )

        last_error: Exception | None = None

        for provider in providers:
            self._record_event(
                RouterEvent(
                    event_type="try",
                    provider=provider.name,
                    model=provider.model,
                )
            )
            deltas_yielded = 0
            partial_text = ""

            try:
                async for delta in provider.stream(messages):
                    deltas_yielded += 1
                    partial_text += delta
                    yield RoutedDelta(
                        text=delta,
                        provider=provider.name,
                        model=provider.model,
                    )

                self._record_event(
                    RouterEvent(
                        event_type="success",
                        provider=provider.name,
                        model=provider.model,
                    )
                )
                return

            except Exception as exc:
                last_error = exc
                if deltas_yielded > 0:
                    # Failed after yielding at least one delta: do NOT switch
                    self._record_event(
                        RouterEvent(
                            event_type="interrupted",
                            provider=provider.name,
                            model=provider.model,
                            error=str(exc),
                        )
                    )
                    raise StreamInterrupted(
                        f"Stream interrupted from {provider.name}/{provider.model}: "
                        f"{exc}",
                        partial_text=partial_text,
                    ) from exc

                # Failed BEFORE yielding any delta
                status_code = getattr(exc, "status_code", None)

                # 4xx other than 429 is a hard error (no failover)
                if (
                    status_code is not None
                    and 400 <= status_code < 500
                    and status_code != 429
                ):
                    self._record_event(
                        RouterEvent(
                            event_type="hard_fail",
                            provider=provider.name,
                            model=provider.model,
                            status_code=status_code,
                            error=str(exc),
                        )
                    )
                    raise exc

                # Failover condition (429, 5xx including Gemini 503, timeouts, network)
                self._record_event(
                    RouterEvent(
                        event_type="failover",
                        provider=provider.name,
                        model=provider.model,
                        status_code=status_code,
                        error=str(exc),
                    )
                )
                continue

        if last_error is not None:
            if isinstance(last_error, ProviderError):
                raise last_error
            raise ProviderError(
                f"All providers exhausted: {last_error}"
            ) from last_error
        raise ProviderError("All providers exhausted")
