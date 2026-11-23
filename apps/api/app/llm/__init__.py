"""LLM routing, providers, and line-stream parser package."""

from app.llm.providers import (
    ChatMessage,
    ChatProvider,
    FakeProvider,
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    ProviderError,
)
from app.llm.router import (
    LLMRouter,
    RoutedDelta,
    RouterEvent,
    StreamInterrupted,
)
from app.llm.stream_parser import (
    ClearEvent,
    CtrlEvent,
    DiagramEvent,
    LatexEvent,
    LineStreamParser,
    ParsedEvent,
    PlotEvent,
    SayEvent,
    parse_stream,
)

__all__ = [
    "ChatMessage",
    "ChatProvider",
    "ClearEvent",
    "CtrlEvent",
    "DiagramEvent",
    "FakeProvider",
    "GeminiProvider",
    "GroqProvider",
    "LLMRouter",
    "LatexEvent",
    "LineStreamParser",
    "OllamaProvider",
    "ParsedEvent",
    "PlotEvent",
    "ProviderError",
    "RoutedDelta",
    "RouterEvent",
    "SayEvent",
    "StreamInterrupted",
    "parse_stream",
]
