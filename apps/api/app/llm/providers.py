"""LLM Provider clients: Groq, Gemini, Ollama, and FakeProvider for testing."""

import json
import os
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import settings


def _clean_no_proxy_ipv6() -> None:
    """Defensive cleaner for httpx IPv6 port parsing bug with no_proxy."""
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val:
            os.environ[var] = ",".join(
                p.strip() for p in val.split(",") if ":" not in p and p.strip()
            )


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


class ProviderError(Exception):
    """Raised when an LLM provider encounters an error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    def __str__(self) -> str:
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class ChatProvider(Protocol):
    """Protocol for streaming LLM chat providers."""

    name: str
    model: str

    def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        """Stream response deltas from the provider."""
        ...


class GroqProvider:
    """Groq Cloud streaming chat completions provider.

    Uses OpenAI-compatible endpoint with curl User-Agent to pass Cloudflare.
    """

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.name = "groq"
        self.model = model
        self.api_key = api_key if api_key is not None else settings.GROQ_API_KEY
        self.base_url = (
            base_url if base_url is not None else settings.GROQ_BASE_URL
        ).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else settings.LLM_REQUEST_TIMEOUT_S
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if not self.api_key:
            raise ProviderError("Groq API key not configured", status_code=401)

        _clean_no_proxy_ipv6()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "curl/8.5.0",  # Bypass Cloudflare error 1010
        }
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body_bytes = await resp.aread()
                        body_text = body_bytes.decode("utf-8", errors="replace")
                        raise ProviderError(
                            f"Groq API error ({resp.status_code}): {body_text}",
                            status_code=resp.status_code,
                        )

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            choices = chunk.get("choices", [])
                            if choices:
                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    yield content
                        except json.JSONDecodeError:
                            continue
        except ProviderError:
            raise
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Groq HTTP status error: {e}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            raise ProviderError(f"Groq network/timeout error: {e}") from e


class GeminiProvider:
    """Google Gemini streaming provider using streamGenerateContent with alt=sse."""

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.name = "gemini"
        self.model = model
        self.api_key = api_key if api_key is not None else settings.GEMINI_API_KEY
        self.timeout = (
            timeout if timeout is not None else settings.LLM_REQUEST_TIMEOUT_S
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if not self.api_key:
            raise ProviderError("Gemini API key not configured", status_code=401)

        _clean_no_proxy_ipv6()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:streamGenerateContent?alt=sse"
        )
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        contents: list[dict[str, Any]] = []
        system_instruction: dict[str, Any] | None = None
        for m in messages:
            if m.role == "system":
                system_instruction = {"parts": [{"text": m.content}]}
            else:
                role = "model" if m.role == "assistant" else "user"
                contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream(
                    "POST",
                    url,
                    headers=headers,
                    json=payload,
                ) as resp:
                    if resp.status_code != 200:
                        body_bytes = await resp.aread()
                        body_text = body_bytes.decode("utf-8", errors="replace")
                        raise ProviderError(
                            f"Gemini API error ({resp.status_code}): {body_text}",
                            status_code=resp.status_code,
                        )

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        try:
                            chunk = json.loads(data_str)
                            candidates = chunk.get("candidates", [])
                            if candidates:
                                cand_0 = candidates[0]
                                parts = cand_0.get("content", {}).get("parts", [])
                                for part in parts:
                                    text = part.get("text")
                                    if text:
                                        yield text
                        except json.JSONDecodeError:
                            continue
        except ProviderError:
            raise
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Gemini HTTP status error: {e}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            raise ProviderError(f"Gemini network/timeout error: {e}") from e


class OllamaProvider:
    """Local Ollama streaming chat provider."""

    def __init__(
        self,
        model: str = "qwen3.8-27b",
        base_url: str | None = None,
        timeout: float | None = None,
    ) -> None:
        self.name = "ollama"
        self.model = model
        self.base_url = (
            base_url if base_url is not None else settings.OLLAMA_BASE_URL
        ).rstrip("/")
        self.timeout = (
            timeout if timeout is not None else settings.LLM_REQUEST_TIMEOUT_S
        )

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if not self.base_url:
            raise ProviderError("Ollama base URL not configured", status_code=503)

        _clean_no_proxy_ipv6()
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                async with client.stream("POST", url, json=payload) as resp:
                    if resp.status_code != 200:
                        body_bytes = await resp.aread()
                        body_text = body_bytes.decode("utf-8", errors="replace")
                        raise ProviderError(
                            f"Ollama API error ({resp.status_code}): {body_text}",
                            status_code=resp.status_code,
                        )

                    async for line in resp.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            chunk = json.loads(line)
                            content = chunk.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except ProviderError:
            raise
        except httpx.HTTPStatusError as e:
            raise ProviderError(
                f"Ollama HTTP status error: {e}",
                status_code=e.response.status_code,
            ) from e
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as e:
            raise ProviderError(f"Ollama network/timeout error: {e}") from e


@dataclass
class FakeProvider:
    """Fake provider for unit testing with zero network requests."""

    name: str = "fake"
    model: str = "fake-model"
    deltas: list[str] = field(default_factory=list)
    fail_status_code: int | None = None
    fail_after_n_deltas: int | None = None
    error_message: str = "Simulated provider failure"
    response_fn: Callable[[list[ChatMessage]], list[str]] | None = None

    async def stream(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        if self.fail_after_n_deltas == 0:
            raise ProviderError(self.error_message, status_code=self.fail_status_code)

        if self.response_fn is not None:
            for delta in self.response_fn(messages):
                yield delta
            return

        for i, delta in enumerate(self.deltas):
            if self.fail_after_n_deltas is not None and i >= self.fail_after_n_deltas:
                raise ProviderError(
                    self.error_message, status_code=self.fail_status_code
                )
            yield delta

        if (
            self.fail_after_n_deltas is not None
            and len(self.deltas) >= self.fail_after_n_deltas
        ):
            raise ProviderError(self.error_message, status_code=self.fail_status_code)
