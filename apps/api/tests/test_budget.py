"""Tests for 4,000-token prompt budget assembler and token counters."""


from app.llm.providers import ChatMessage
from app.tutor.budget import (
    CONVERSATION_WINDOW_CEILING,
    DEFAULT_SYSTEM_PREFIX,
    PROMPT_BUDGET_CEILING,
    RAG_CHUNK_SINGLE_CEILING,
    RAG_CHUNKS_TOTAL_CEILING,
    RUNNING_SUMMARY_CEILING,
    SUBTOPIC_BRIEF_CEILING,
    SYSTEM_PREFIX_CEILING,
    TRUNCATION_MARKER,
    WHITEBOARD_SUMMARY_CEILING,
    CharsTokenCounter,
    PromptAssembler,
    truncate_rag_chunk,
)


def test_chars_token_counter():
    counter = CharsTokenCounter()
    assert counter.count_tokens("") == 0
    assert counter.count_tokens("a") == 1
    assert counter.count_tokens("abcd") == 1
    assert counter.count_tokens("abcde") == 2
    assert counter.count_tokens("a" * 400) == 100


def test_truncate_rag_chunk_sentence_boundary_and_marker():
    counter = CharsTokenCounter()
    # Create text with clear sentences that exceeds 300 tokens (1200 chars)
    sentence = "This is a clean sentence about descriptive statistics. "
    long_text = sentence * 40  # ~2200 chars => ~550 tokens

    truncated = truncate_rag_chunk(long_text, max_tokens=300, counter=counter)

    assert truncated.endswith(TRUNCATION_MARKER)
    assert counter.count_tokens(truncated) <= RAG_CHUNK_SINGLE_CEILING
    # Sentence boundary before marker
    prefix = truncated[: -len(TRUNCATION_MARKER)].strip()
    assert prefix.endswith(".")


def test_truncate_rag_chunk_under_budget_not_modified():
    counter = CharsTokenCounter()
    short_text = "Short text under 300 tokens."
    assert truncate_rag_chunk(short_text, max_tokens=300, counter=counter) == short_text


def test_default_system_prefix_contains_protocol_rules():
    assert "SAY:" in DEFAULT_SYSTEM_PREFIX
    assert "LATEX:" in DEFAULT_SYSTEM_PREFIX
    assert "PLOT:" in DEFAULT_SYSTEM_PREFIX
    assert "DIAGRAM:" in DEFAULT_SYSTEM_PREFIX
    assert "CLEAR:" in DEFAULT_SYSTEM_PREFIX
    assert "CTRL:" in DEFAULT_SYSTEM_PREFIX
    assert 'CTRL: {"action": "micro_check"}' in DEFAULT_SYSTEM_PREFIX
    assert "NEVER include raw LaTeX" in DEFAULT_SYSTEM_PREFIX


def test_maximally_stuffed_prompt_satisfies_all_ceilings():
    counter = CharsTokenCounter()
    assembler = PromptAssembler(counter=counter)

    # Feed giant strings (10,000+ chars each) into every section
    giant_prefix = "A" * 10000
    giant_brief = "B" * 10000
    giant_chunks = [
        "Chunk 1: " + ("C" * 5000),
        "Chunk 2: " + ("D" * 5000),
        "Chunk 3: " + ("E" * 5000),
        "Chunk 4: " + ("F" * 5000),
    ]
    giant_wb = "W" * 5000
    giant_turns = [
        ChatMessage(
            role="user" if i % 2 == 0 else "assistant",
            content=f"Turn {i}: " + ("T" * 2000),
        )
        for i in range(12)
    ]
    giant_summary = "S" * 5000

    assembled = assembler.assemble(
        system_prefix=giant_prefix,
        subtopic_title="Huge Subtopic",
        subtopic_brief=giant_brief,
        rag_chunks=giant_chunks,
        whiteboard_summary=giant_wb,
        conversation_turns=giant_turns,
        running_summary=giant_summary,
        remedial_analogy=True,
    )

    # Check each individual section ceiling
    breakdown = assembled.token_breakdown
    assert breakdown["system_prefix"] <= SYSTEM_PREFIX_CEILING
    assert breakdown["subtopic_brief"] <= SUBTOPIC_BRIEF_CEILING
    assert breakdown["rag_chunks"] <= RAG_CHUNKS_TOTAL_CEILING
    assert breakdown["whiteboard_summary"] <= WHITEBOARD_SUMMARY_CEILING
    assert breakdown["running_summary"] <= RUNNING_SUMMARY_CEILING
    assert breakdown["conversation_window_total"] <= CONVERSATION_WINDOW_CEILING

    # Top 3 chunks only (Chunk 4 discarded)
    assert len(assembled.rag_chunks) == 3
    for chunk in assembled.rag_chunks:
        assert counter.count_tokens(chunk) <= RAG_CHUNK_SINGLE_CEILING

    # Verbatim turns capped at 6
    assert len(assembled.conversation_turns) <= 6

    # Total prompt tokens <= 3,450
    assert assembled.total_tokens <= PROMPT_BUDGET_CEILING
    assert assembled.total_tokens <= 3450


def test_conversation_window_rolling_last_6_turns():
    counter = CharsTokenCounter()
    assembler = PromptAssembler(counter=counter)

    turns = [ChatMessage(role="user", content=f"turn_{i}") for i in range(10)]

    assembled = assembler.assemble(
        conversation_turns=turns,
        running_summary="Summary of turns 0 to 3",
    )

    # Verbatim turns contains exactly the last 6 turns (turns 4 to 9)
    assert len(assembled.conversation_turns) == 6
    expected_contents = [f"turn_{i}" for i in range(4, 10)]
    assert [t.content for t in assembled.conversation_turns] == expected_contents
