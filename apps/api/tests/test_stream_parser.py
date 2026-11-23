"""Adversarial tests for LineStreamParser (P3 Honest TDD Core Module)."""

from app.llm.stream_parser import (
    ClearEvent,
    CtrlEvent,
    DiagramEvent,
    LatexEvent,
    LineStreamParser,
    PlotEvent,
    SayEvent,
    parse_stream,
)


def test_directive_split_across_1_char_deltas():
    """Directive split across 1-char deltas buffers until newline."""
    parser = LineStreamParser()
    raw = "SAY: Hello world!\n"
    all_events = []
    for i, char in enumerate(raw):
        events = parser.feed(char)
        if i < len(raw) - 1:
            assert events == [], f"Premature event emission on char {i!r}: {char!r}"
        all_events.extend(events)

    assert all_events == [SayEvent(text="Hello world!")]


def test_crlf_endings():
    """CRLF line endings are parsed cleanly without leftover carriage returns."""
    text = "SAY: hello\r\nLATEX: x^2 + y^2 = r^2\r\nCLEAR:\r\n"
    events = parse_stream(text)
    assert events == [
        SayEvent(text="hello"),
        LatexEvent(latex="x^2 + y^2 = r^2"),
        ClearEvent(),
    ]


def test_unknown_prefix_lines_become_say():
    """Unknown directives or plain prose become SAY events (never crash)."""
    text = (
        "Note: this is very important for the exam\n"
        "Just a regular sentence with no prefix.\n"
        "EXPLAIN: some random prefix\n"
    )
    events = parse_stream(text)
    assert events == [
        SayEvent(text="Note: this is very important for the exam"),
        SayEvent(text="Just a regular sentence with no prefix."),
        SayEvent(text="EXPLAIN: some random prefix"),
    ]


def test_empty_lines_skipped():
    """Empty and whitespace-only lines are skipped."""
    text = "\n\n   \n\t  \r\nSAY: valid text\n\n   \n"
    events = parse_stream(text)
    assert events == [SayEvent(text="valid text")]


def test_invalid_json_degrades_to_ctrl_error():
    """Invalid JSON in PLOT, DIAGRAM, and CTRL degrades to CtrlEvent without raising."""
    text = "PLOT: {not valid json\nDIAGRAM: [unclosed array\nCTRL: broken payload\n"
    events = parse_stream(text)
    assert len(events) == 3
    assert events[0] == CtrlEvent(
        payload={"error": "invalid_json", "raw": "{not valid json"}
    )
    assert events[1] == CtrlEvent(
        payload={"error": "invalid_json", "raw": "[unclosed array"}
    )
    assert events[2] == CtrlEvent(
        payload={"error": "invalid_json", "raw": "broken payload"}
    )


def test_valid_json_payloads():
    """Valid JSON in PLOT, DIAGRAM, and CTRL is parsed into dictionary specs."""
    text = (
        'PLOT: {"fn": "x^2", "domain": [-2, 2]}\n'
        'DIAGRAM: {"type": "box", "label": "mass m"}\n'
        'CTRL: {"action": "micro_check", "concept": "variance"}\n'
    )
    events = parse_stream(text)
    assert events == [
        PlotEvent(spec={"fn": "x^2", "domain": [-2, 2]}),
        DiagramEvent(spec={"type": "box", "label": "mass m"}),
        CtrlEvent(payload={"action": "micro_check", "concept": "variance"}),
    ]


def test_10000_char_say_line_survives():
    """A 10,000-character SAY line survives completely intact."""
    huge_text = "a" * 10000
    line = f"SAY: {huge_text}\n"
    events = parse_stream(line)
    assert len(events) == 1
    assert isinstance(events[0], SayEvent)
    assert events[0].text == huge_text
    assert len(events[0].text) == 10000


def test_flush_emits_trailing_line_no_newline():
    """flush() emits buffered line when stream ends without a trailing newline."""
    parser = LineStreamParser()
    events1 = parser.feed("SAY: partial line without")
    assert events1 == []
    events2 = parser.feed(" newline")
    assert events2 == []
    flushed = parser.flush()
    assert flushed == [SayEvent(text="partial line without newline")]
    # Subsequent flush on empty buffer returns nothing
    assert parser.flush() == []


def test_math_content_containing_colons_keeps_full_payload():
    """Math content containing colons keeps the full payload after the FIRST colon."""
    latex_with_colons = r"\frac{a:b}{c} + P(X=x : Y=y)"
    text = f"LATEX: {latex_with_colons}\n"
    events = parse_stream(text)
    assert len(events) == 1
    assert isinstance(events[0], LatexEvent)
    assert events[0].latex == latex_with_colons


def test_interleaved_directives_keep_order():
    """Interleaved stream directives are emitted in exact arrival order."""
    chunks = [
        "SAY: Step 1: Let's state Bayes' theorem.\n",
        "LATEX: P(A|B) = \\frac{P(B|A)P(A)}{P(B)}\n",
        'PLOT: {"expression": "1/(1+exp(-x))"}\n',
        "CLEAR:\n",
        'CTRL: {"action": "advance_subtopic", "target": "sta301.ch01.t02"}\n',
    ]
    parser = LineStreamParser()
    all_events = []
    for chunk in chunks:
        all_events.extend(parser.feed(chunk))
    all_events.extend(parser.flush())

    assert all_events == [
        SayEvent(text="Step 1: Let's state Bayes' theorem."),
        LatexEvent(latex=r"P(A|B) = \frac{P(B|A)P(A)}{P(B)}"),
        PlotEvent(spec={"expression": "1/(1+exp(-x))"}),
        ClearEvent(),
        CtrlEvent(payload={"action": "advance_subtopic", "target": "sta301.ch01.t02"}),
    ]


def test_directive_prefix_split_across_chunks():
    """Prefix split across chunk boundaries (e.g. 'LA' then 'TEX: ') parses properly."""
    parser = LineStreamParser()
    events = []
    events.extend(parser.feed("LA"))
    events.extend(parser.feed("TEX"))
    events.extend(parser.feed(": "))
    events.extend(parser.feed("E = mc^2\n"))
    assert events == [LatexEvent(latex="E = mc^2")]


def test_multiple_lines_in_single_delta():
    """Single delta containing multiple directives emits all events."""
    delta = "SAY: First line\nLATEX: \\alpha + \\beta\nCLEAR:\n"
    parser = LineStreamParser()
    events = parser.feed(delta)
    assert events == [
        SayEvent(text="First line"),
        LatexEvent(latex=r"\alpha + \beta"),
        ClearEvent(),
    ]


def test_say_line_sanitizes_math_delimiters_and_commands():
    """SAY lines strip $$...$$, $...$, and stray backslash commands before TTS."""
    text = (
        r"SAY: As seen in $x^2 + y^2 = 1$, the mean is \bar{x} and value is $$z$$."
        "\n"
    )
    events = parse_stream(text)
    assert len(events) == 1
    assert isinstance(events[0], SayEvent)
    assert events[0].text == "As seen in x^2 + y^2 = 1, the mean is x and value is z."


def test_unclosed_dollar_sign_stripped_from_say():
    """Unclosed or accidental dollar signs are stripped before TTS."""
    text = "SAY: Note that $x is greater than 0.\n"
    events = parse_stream(text)
    assert len(events) == 1
    assert events[0] == SayEvent(text="Note that x is greater than 0.")


def test_say_payload_containing_directive_keywords_and_colons():
    """A SAY payload containing colons and directive names is preserved intact."""
    text = "SAY: Remember: LATEX: is a directive, not plain text.\n"
    events = parse_stream(text)
    assert len(events) == 1
    assert events[0] == SayEvent(
        text="Remember: LATEX: is a directive, not plain text."
    )


def test_empty_directives_ignored():
    """Empty SAY and LATEX directives without payload emit no events."""
    text = "LATEX:\nSAY:\nLATEX:   \n"
    events = parse_stream(text)
    assert events == []


def test_split_crlf_across_deltas():
    """CRLF split across feed chunk boundaries is handled cleanly."""
    parser = LineStreamParser()
    events = []
    events.extend(parser.feed("SAY: first line\r"))
    assert events == []
    events.extend(parser.feed("\nSAY: second line\r\n"))
    assert events == [
        SayEvent(text="first line"),
        SayEvent(text="second line"),
    ]
