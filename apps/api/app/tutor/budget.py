"""4,000-token prompt budget assembler and token counters (P1/P4 invariant).

Enforces strict per-section ceilings summing to 3,450 prompt tokens,
leaving ~550 tokens completion headroom for the 4,000-token total cap.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from app.llm.providers import ChatMessage

# Hard budget ceilings (tokens)
SYSTEM_PREFIX_CEILING = 750
SUBTOPIC_BRIEF_CEILING = 500
RAG_CHUNKS_TOTAL_CEILING = 900
RAG_CHUNK_SINGLE_CEILING = 300
WHITEBOARD_SUMMARY_CEILING = 300
CONVERSATION_WINDOW_CEILING = 1000
RUNNING_SUMMARY_CEILING = 150
MAX_VERBATIM_TURNS = 6
PROMPT_BUDGET_CEILING = 3450
COMPLETION_HEADROOM = 550
TOTAL_CAP = 4000

TRUNCATION_MARKER = " [TRUNCATED]"

DEFAULT_SYSTEM_PREFIX = (
    "You are an expert AI Video Tutor teaching a university course step by step.\n"
    "Follow the strict newline-delimited line protocol on EVERY response:\n"
    "- SAY: Natural spoken explanation to the student. Speak warmly.\n"
    "  CRITICAL: Math is ONLY allowed inside LATEX: lines. "
    "NEVER include raw LaTeX ($$, \\frac, \\sum, \\sigma, etc.) inside SAY lines.\n"
    "- LATEX: Display math formulas or equations to be written on the whiteboard.\n"
    '- PLOT: JSON object for plotting e.g. PLOT: {"fn": "x^2", "domain": [-5, 5]}\n'
    '- DIAGRAM: JSON object for diagrams e.g. DIAGRAM: {"type": "box"}\n'
    "- CLEAR: Clear or advance the whiteboard slide.\n"
    "- CTRL: Tutoring workflow signals.\n"
    "  When asking a micro-check question to test understanding, end the turn with:\n"
    '  CTRL: {"action": "micro_check"}\n'
    "Keep explanations concise, engaging, and pedagogically sound."
)


class TokenCounter(Protocol):
    """Protocol for token counting estimators."""

    def count_tokens(self, text: str) -> int:
        """Return the estimated number of tokens in text."""
        ...


class CharsTokenCounter:
    """Chars/4 token estimator using ceiling rounding."""

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return math.ceil(len(text) / 4)


def truncate_text_to_tokens(
    text: str,
    max_tokens: int,
    counter: TokenCounter,
    marker: str = "",
) -> str:
    """Deterministically truncate text so counter.count_tokens(result) <= max_tokens."""
    if counter.count_tokens(text) <= max_tokens:
        return text

    marker_tokens = counter.count_tokens(marker) if marker else 0
    available_tokens = max(1, max_tokens - marker_tokens)
    target_chars = available_tokens * 4

    cut_text = text[:target_chars]
    result = f"{cut_text}{marker}"
    # Guard against counter edge-cases where ceil(len/4) is 1 token over
    while counter.count_tokens(result) > max_tokens and len(cut_text) > 0:
        cut_text = cut_text[:-4]
        result = f"{cut_text}{marker}"
    return result


def truncate_rag_chunk(
    chunk_text: str,
    max_tokens: int = RAG_CHUNK_SINGLE_CEILING,
    counter: TokenCounter | None = None,
    marker: str = TRUNCATION_MARKER,
) -> str:
    """Truncate a RAG chunk at a sentence boundary when possible and append marker.

    Guarantees counter.count_tokens(result) <= max_tokens.
    """
    if counter is None:
        counter = CharsTokenCounter()

    if counter.count_tokens(chunk_text) <= max_tokens:
        return chunk_text

    marker_tokens = counter.count_tokens(marker)
    available_tokens = max(1, max_tokens - marker_tokens)
    max_chars = available_tokens * 4

    candidate = chunk_text[:max_chars]

    # Attempt to cut at the last sentence boundary within candidate
    # Sentence boundaries: . ! ? followed by whitespace or double newlines
    matches = list(re.finditer(r"([.!?])(?:\s+|\n+|$)", candidate))
    if matches:
        # Pick last sentence boundary if reasonably long (>= 30% of max_chars)
        last_match = matches[-1]
        boundary_idx = last_match.end()
        if boundary_idx >= int(max_chars * 0.3):
            cut_text = candidate[:boundary_idx].rstrip()
            result = f"{cut_text}{marker}"
            while counter.count_tokens(result) > max_tokens and len(cut_text) > 0:
                cut_text = cut_text[:-4]
                result = f"{cut_text}{marker}"
            return result

    # Fallback to word boundary if no sentence boundary found
    word_boundary = candidate.rfind(" ")
    if word_boundary > int(max_chars * 0.5):
        cut_text = candidate[:word_boundary].rstrip()
    else:
        cut_text = candidate

    result = f"{cut_text}{marker}"
    while counter.count_tokens(result) > max_tokens and len(cut_text) > 0:
        cut_text = cut_text[:-4]
        result = f"{cut_text}{marker}"
    return result


@dataclass(frozen=True)
class AssembledPrompt:
    """Result of assembling a 4,000-token-budgeted prompt."""

    messages: list[ChatMessage]
    system_prefix: str
    subtopic_brief: str
    rag_chunks: list[str]
    whiteboard_summary: str
    conversation_turns: list[ChatMessage]
    running_summary: str
    token_breakdown: dict[str, int]
    total_tokens: int


class PromptAssembler:
    """Deterministic prompt assembler with hard per-section ceilings."""

    def __init__(self, counter: TokenCounter | None = None) -> None:
        self.counter: TokenCounter = (
            counter if counter is not None else CharsTokenCounter()
        )

    def assemble(
        self,
        subtopic_title: str = "",
        subtopic_brief: str = "",
        rag_chunks: Sequence[str | dict[str, Any]] | None = None,
        whiteboard_summary: str = "",
        conversation_turns: (
            Sequence[ChatMessage | dict[str, str]] | None
        ) = None,
        running_summary: str = "",
        system_prefix: str | None = None,
        remedial_analogy: bool = False,
        extra_instructions: str = "",
    ) -> AssembledPrompt:
        """Assemble a prompt enforcing all hard per-section ceilings.

        Asserts total prompt tokens <= 3,450.
        """
        # 1. System Prefix (<= 750 tokens)
        base_prefix = (
            system_prefix if system_prefix is not None else DEFAULT_SYSTEM_PREFIX
        )
        if remedial_analogy:
            base_prefix += (
                "\n\nNOTE: The student struggled with the previous micro-check. "
                "Use an intuitive real-world analogy and explain from first principles."
            )
        if extra_instructions:
            base_prefix += f"\n\n{extra_instructions.strip()}"

        prefix_clean = truncate_text_to_tokens(
            base_prefix, SYSTEM_PREFIX_CEILING, self.counter, marker=""
        )
        prefix_tokens = self.counter.count_tokens(prefix_clean)
        assert prefix_tokens <= SYSTEM_PREFIX_CEILING

        # 2. Subtopic Brief (<= 500 tokens)
        brief_full = ""
        if subtopic_title:
            brief_full += f"Active Subtopic: {subtopic_title}\n"
        if subtopic_brief:
            brief_full += f"Brief / Objectives: {subtopic_brief}"
        brief_full = brief_full.strip()

        brief_clean = truncate_text_to_tokens(
            brief_full, SUBTOPIC_BRIEF_CEILING, self.counter, marker=""
        )
        brief_tokens = self.counter.count_tokens(brief_clean)
        assert brief_tokens <= SUBTOPIC_BRIEF_CEILING

        # 3. Top-3 RAG chunks (<= 900 tokens total, each <= 300 tokens)
        processed_chunks: list[str] = []
        raw_chunks = rag_chunks or []
        # Take top 3 chunks only
        for raw in raw_chunks[:3]:
            if isinstance(raw, dict):
                text_content = (
                    raw.get("markdown", "") or raw.get("content", "") or str(raw)
                )
            else:
                text_content = str(raw)

            chunk_truncated = truncate_rag_chunk(
                text_content,
                max_tokens=RAG_CHUNK_SINGLE_CEILING,
                counter=self.counter,
                marker=TRUNCATION_MARKER,
            )
            processed_chunks.append(chunk_truncated)

        # Enforce total RAG ceiling of 900 tokens across all chunks
        total_rag_tokens = sum(self.counter.count_tokens(c) for c in processed_chunks)
        while total_rag_tokens > RAG_CHUNKS_TOTAL_CEILING and processed_chunks:
            # Cut from the last chunk
            last = processed_chunks.pop()
            excess = total_rag_tokens - RAG_CHUNKS_TOTAL_CEILING
            allowed = max(0, self.counter.count_tokens(last) - excess)
            if allowed > 10:
                truncated_last = truncate_rag_chunk(
                    last,
                    max_tokens=allowed,
                    counter=self.counter,
                    marker=TRUNCATION_MARKER,
                )
                processed_chunks.append(truncated_last)
            total_rag_tokens = sum(
                self.counter.count_tokens(c) for c in processed_chunks
            )

        rag_tokens = sum(self.counter.count_tokens(c) for c in processed_chunks)
        assert rag_tokens <= RAG_CHUNKS_TOTAL_CEILING

        # 4. Whiteboard Summary (<= 300 tokens)
        wb_clean = truncate_text_to_tokens(
            whiteboard_summary.strip(),
            WHITEBOARD_SUMMARY_CEILING,
            self.counter,
            marker="",
        )
        wb_tokens = self.counter.count_tokens(wb_clean)
        assert wb_tokens <= WHITEBOARD_SUMMARY_CEILING

        # 5. Conversation Window (<= 1,000 tokens)
        # Running summary capped at 150 tokens inside that budget
        clean_running_summary = ""
        summary_tokens = 0
        if running_summary.strip():
            clean_running_summary = truncate_text_to_tokens(
                running_summary.strip(),
                RUNNING_SUMMARY_CEILING,
                self.counter,
                marker="",
            )
            summary_tokens = self.counter.count_tokens(clean_running_summary)
            assert summary_tokens <= RUNNING_SUMMARY_CEILING

        # Rolling last 6 turns verbatim
        raw_turns = conversation_turns or []
        normalized_turns: list[ChatMessage] = []
        for turn in raw_turns:
            if isinstance(turn, ChatMessage):
                normalized_turns.append(turn)
            elif isinstance(turn, dict):
                normalized_turns.append(
                    ChatMessage(
                        role=turn.get("role", "user"),
                        content=turn.get("content", ""),
                    )
                )

        # Keep at most last 6 turns
        verbatim_turns = (
            normalized_turns[-MAX_VERBATIM_TURNS:] if normalized_turns else []
        )

        # Available budget for verbatim turns
        verbatim_budget = CONVERSATION_WINDOW_CEILING - summary_tokens

        # Check total tokens of verbatim turns
        def turns_token_count(turns: list[ChatMessage]) -> int:
            return sum(self.counter.count_tokens(t.content) for t in turns)

        while verbatim_turns and turns_token_count(verbatim_turns) > verbatim_budget:
            # Drop earliest turn in the window if it doesn't fit
            if len(verbatim_turns) > 1:
                verbatim_turns.pop(0)
            else:
                # Truncate the single remaining turn
                single = verbatim_turns[0]
                truncated_content = truncate_text_to_tokens(
                    single.content, verbatim_budget, self.counter, marker=" [...]"
                )
                verbatim_turns = [
                    ChatMessage(role=single.role, content=truncated_content)
                ]
                break

        conv_tokens = summary_tokens + turns_token_count(verbatim_turns)
        assert conv_tokens <= CONVERSATION_WINDOW_CEILING

        # Assemble messages for LLMRouter:
        # system_prefix, subtopic brief, RAG chunks, whiteboard summary
        context_parts = []
        if brief_clean:
            context_parts.append(f"=== SUBTOPIC CONTEXT ===\n{brief_clean}")
        if processed_chunks:
            chunks_text = "\n\n---\n\n".join(
                f"[Chunk {i + 1}]:\n{c}" for i, c in enumerate(processed_chunks)
            )
            context_parts.append(
                f"=== REFERENCE MATERIAL (LTREE SCOPED) ===\n{chunks_text}"
            )
        if wb_clean:
            context_parts.append(f"=== CURRENT WHITEBOARD STATE ===\n{wb_clean}")

        system_content = prefix_clean
        if context_parts:
            system_content += "\n\n" + "\n\n".join(context_parts)

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=system_content)
        ]

        if clean_running_summary:
            summary_msg = f"=== CONVERSATION SUMMARY ===\n{clean_running_summary}"
            messages.append(ChatMessage(role="system", content=summary_msg))

        messages.extend(verbatim_turns)

        token_breakdown = {
            "system_prefix": prefix_tokens,
            "subtopic_brief": brief_tokens,
            "rag_chunks": rag_tokens,
            "whiteboard_summary": wb_tokens,
            "running_summary": summary_tokens,
            "conversation_verbatim": turns_token_count(verbatim_turns),
            "conversation_window_total": conv_tokens,
        }

        # Total prompt tokens is sum of sections (note: structural headers like
        # "=== SUBTOPIC CONTEXT ===" add ~20-40 tokens not counted here; keep
        # the section ceilings conservative to absorb this overhead)
        total_tokens = (
            prefix_tokens + brief_tokens + rag_tokens + wb_tokens + conv_tokens
        )
        assert total_tokens <= PROMPT_BUDGET_CEILING, (
            f"Total tokens {total_tokens} exceeds {PROMPT_BUDGET_CEILING}"
        )

        return AssembledPrompt(
            messages=messages,
            system_prefix=prefix_clean,
            subtopic_brief=brief_clean,
            rag_chunks=processed_chunks,
            whiteboard_summary=wb_clean,
            conversation_turns=verbatim_turns,
            running_summary=clean_running_summary,
            token_breakdown=token_breakdown,
            total_tokens=total_tokens,
        )
