"""Line-delimited stream parser for LLM streaming directives.

Protocol lines:
  SAY: <text>
  LATEX: <latex>
  PLOT: <json>
  DIAGRAM: <json>
  CLEAR:
  CTRL: <json>
"""

import json
import re
from dataclasses import dataclass
from typing import Any, Union


def sanitize_say_text(text: str) -> str:
    """Sanitize SAY text to remove raw LaTeX delimiters and markup before TTS."""
    if not text:
        return ""
    # Strip $$...$$ or $...$
    cleaned = re.sub(r"\$\$(.*?)\$\$", r"\1", text)
    cleaned = re.sub(r"\$(.*?)\$", r"\1", cleaned)
    # Strip common stray backslash math commands if any leak through
    cleaned = re.sub(r"\\[a-zA-Z]+", "", cleaned)
    # Strip residual curly braces from stripped LaTeX commands
    cleaned = re.sub(r"[{}]", "", cleaned)
    # Strip accidental unclosed / stray $ delimiters before TTS
    cleaned = cleaned.replace("$", "")
    # Normalize multiple whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


@dataclass(frozen=True)
class SayEvent:
    text: str


@dataclass(frozen=True)
class LatexEvent:
    latex: str


@dataclass(frozen=True)
class PlotEvent:
    spec: dict[str, Any]


@dataclass(frozen=True)
class DiagramEvent:
    spec: dict[str, Any]


@dataclass(frozen=True)
class ClearEvent:
    pass


@dataclass(frozen=True)
class CtrlEvent:
    payload: dict[str, Any]


ParsedEvent = Union[
    SayEvent,
    LatexEvent,
    PlotEvent,
    DiagramEvent,
    ClearEvent,
    CtrlEvent,
]

KNOWN_DIRECTIVES = {"SAY", "LATEX", "PLOT", "DIAGRAM", "CLEAR", "CTRL"}


class LineStreamParser:
    """Incremental line-delimited stream parser with buffering."""

    def __init__(self) -> None:
        self._buffer: str = ""

    def _parse_line(self, raw_line: str) -> ParsedEvent | None:
        stripped = raw_line.strip()
        if not stripped:
            return None

        if ":" in stripped:
            prefix, _, payload = stripped.partition(":")
            prefix = prefix.strip()
            payload = payload.strip()

            if prefix in KNOWN_DIRECTIVES:
                if prefix == "SAY":
                    sanitized = sanitize_say_text(payload)
                    return SayEvent(text=sanitized) if sanitized else None
                elif prefix == "LATEX":
                    return LatexEvent(latex=payload) if payload else None
                elif prefix == "PLOT":
                    try:
                        spec = json.loads(payload)
                        if isinstance(spec, dict):
                            return PlotEvent(spec=spec)
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )
                    except Exception:
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )
                elif prefix == "DIAGRAM":
                    try:
                        spec = json.loads(payload)
                        if isinstance(spec, dict):
                            return DiagramEvent(spec=spec)
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )
                    except Exception:
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )
                elif prefix == "CLEAR":
                    return ClearEvent()
                elif prefix == "CTRL":
                    try:
                        ctrl_data = json.loads(payload)
                        if isinstance(ctrl_data, dict):
                            return CtrlEvent(payload=ctrl_data)
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )
                    except Exception:
                        return CtrlEvent(
                            payload={"error": "invalid_json", "raw": payload}
                        )

            # Prefix with colon not in KNOWN_DIRECTIVES: models drift; treat as SAY
            sanitized = sanitize_say_text(stripped)
            return SayEvent(text=sanitized) if sanitized else None

        # No colon in stripped line
        if stripped == "CLEAR":
            return ClearEvent()

        # Any other non-empty line treated as SAY
        sanitized = sanitize_say_text(stripped)
        return SayEvent(text=sanitized) if sanitized else None

    def feed(self, text_delta: str) -> list[ParsedEvent]:
        """Buffer text_delta and emit ParsedEvents for all complete lines."""
        if not text_delta:
            return []

        self._buffer += text_delta
        if "\n" not in self._buffer:
            return []

        parts = self._buffer.split("\n")
        self._buffer = parts[-1]
        completed_lines = parts[:-1]

        events: list[ParsedEvent] = []
        for line in completed_lines:
            line = line.rstrip("\r")
            event = self._parse_line(line)
            if event is not None:
                events.append(event)
        return events

    def flush(self) -> list[ParsedEvent]:
        """Emit any remaining buffered content as a final ParsedEvent."""
        remaining = self._buffer.rstrip("\r\n")
        self._buffer = ""
        if not remaining.strip():
            return []

        event = self._parse_line(remaining)
        if event is not None:
            return [event]
        return []


def parse_stream(text: str) -> list[ParsedEvent]:
    """Convenience function for whole-string parsing."""
    parser = LineStreamParser()
    events = parser.feed(text)
    events.extend(parser.flush())
    return events
