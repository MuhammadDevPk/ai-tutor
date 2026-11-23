"""Tests for PCM Offset Stamper — P3 Core Module (playout clock scheduler).

Tests are written FIRST per P3 Honest TDD. They must fail for the right
reason (ImportError or AttributeError on the not-yet-written module) before
the implementation is authored.
"""

from __future__ import annotations

from app.llm.stream_parser import ClearEvent, DiagramEvent, LatexEvent, PlotEvent
from app.schemas.events import BoardOp
from app.voice.offset_stamper import EpochGuard, OffsetStamper
from app.voice.tts import LEAD_IN_SILENCE_SAMPLES, PCMCursor

# ---------------------------------------------------------------------------
# 1. OffsetStamper core tests
# ---------------------------------------------------------------------------


class TestOffsetStamperBasic:
    """Stamper tracks cumulative 24kHz PCM samples per turn_id."""

    def test_directive_before_any_audio_returns_zero_offset(self) -> None:
        """A directive stamped before any PCM yields playout_offset_ms = 0."""
        stamper = OffsetStamper(turn_id=1)
        result = stamper.stamp(LatexEvent(latex=r"E = mc^2"))
        assert result.playout_offset_ms == 0

    def test_lead_in_silence_counted(self) -> None:
        """150ms lead-in = 3,600 samples. Directive after lead-in = 150ms offset."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)  # 3600 samples
        result = stamper.stamp(LatexEvent(latex=r"\frac{a}{b}"))
        assert result.playout_offset_ms == 150

    def test_offset_after_mixed_audio(self) -> None:
        """Lead-in (3600) + 1 word of TTS (2400 samples at 100ms) = 250ms."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)  # 3600 -> 150ms
        stamper.advance_samples(2400)  # 100ms of speech
        result = stamper.stamp(PlotEvent(spec={"fn": "x^2"}))
        assert result.playout_offset_ms == 250

    def test_exact_sample_boundary_integer_rounding(self) -> None:
        """Offset = cumulative_samples / 24 (samples per ms), truncated to int.

        Integer division: 3601 samples / 24 = 150.041... -> 150 (floor).
        """
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(3601)
        result = stamper.stamp(LatexEvent(latex="x"))
        # 3601 // 24 = 150
        assert result.playout_offset_ms == 150

    def test_multiple_directives_between_sentences(self) -> None:
        """Two directives at the same sample position get the same offset."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)  # 150ms
        r1 = stamper.stamp(LatexEvent(latex="a"))
        r2 = stamper.stamp(LatexEvent(latex="b"))
        assert r1.playout_offset_ms == 150
        assert r2.playout_offset_ms == 150

    def test_directives_between_sentences_land_on_exact_boundaries(self) -> None:
        """After lead-in + sentence1, the directive offset accounts for both."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)  # 3600 -> 150ms
        stamper.advance_samples(24000)  # 1 second of speech -> 1150ms total
        r = stamper.stamp(DiagramEvent(spec={"type": "tree"}))
        assert r.playout_offset_ms == 1150

    def test_clear_directive_stamped(self) -> None:
        """CLEAR directives also get a valid offset."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)
        r = stamper.stamp(ClearEvent())
        assert r.playout_offset_ms == 150
        assert r.op_type == "clear"


class TestOffsetStamperTurnIsolation:
    """Per-turn counter isolation: a new turn_id restarts at 0."""

    def test_new_turn_resets_cumulative_samples(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)
        stamper.stamp(LatexEvent(latex="x"))  # 150ms

        stamper.reset(turn_id=2)
        result = stamper.stamp(LatexEvent(latex="y"))
        assert result.playout_offset_ms == 0

    def test_turn_id_propagated_to_board_op(self) -> None:
        stamper = OffsetStamper(turn_id=5)
        r = stamper.stamp(LatexEvent(latex="z"))
        assert r.turn_id == 5

    def test_cross_turn_op_id_uniqueness(self) -> None:
        """op_ids must never collide across turns to avoid frontend dedup drops."""
        stamper = OffsetStamper(turn_id=1)
        r1 = stamper.stamp(LatexEvent(latex="turn1_step1"))
        stamper.reset(turn_id=2)
        r2 = stamper.stamp(LatexEvent(latex="turn2_step1"))
        assert r1.op_id != r2.op_id

    def test_stamper_reuses_pcm_cursor(self) -> None:
        """OffsetStamper can reuse a single PCMCursor without duplicate counters."""
        cursor = PCMCursor(turn_id=3)
        stamper = OffsetStamper(turn_id=3, cursor=cursor)
        cursor.total_samples += 2400  # 100ms
        r = stamper.stamp(LatexEvent(latex="w"))
        assert r.playout_offset_ms == 100
        assert stamper.cumulative_samples == 2400
        assert stamper.offset_ms == 100


class TestOffsetStamperSegmentStart:
    """AUDIO_SEGMENT_START events for filler vs response."""

    def test_response_segment_start(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        ev = stamper.emit_segment_start("response")
        assert ev.segment_id == "response"
        assert ev.turn_id == 1

    def test_filler_segment_start(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        ev = stamper.emit_segment_start("filler")
        assert ev.segment_id == "filler"
        assert ev.turn_id == 1

    def test_filler_samples_counted(self) -> None:
        """Filler clip PCM samples advance the cumulative counter."""
        stamper = OffsetStamper(turn_id=1)
        stamper.advance_samples(LEAD_IN_SILENCE_SAMPLES)  # 150ms
        # Filler clip of 2400 samples (100ms)
        stamper.advance_samples(2400)
        result = stamper.stamp(LatexEvent(latex="q"))
        assert result.playout_offset_ms == 250


class TestOffsetStamperBoardSchedule:
    """stamp() returns a StampResult that can generate a BOARD_SCHEDULE."""

    def test_stamp_result_has_board_op_fields(self) -> None:
        stamper = OffsetStamper(turn_id=3)
        stamper.advance_samples(4800)  # 200ms
        r = stamper.stamp(LatexEvent(latex=r"\sum_{i=1}^n"))
        assert r.op_id.startswith("op_")
        assert r.op_type == "latex"
        assert r.playout_offset_ms == 200
        assert r.turn_id == 3
        assert r.payload == {"latex": r"\sum_{i=1}^n"}

    def test_op_id_monotonically_increases(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        r1 = stamper.stamp(LatexEvent(latex="a"))
        r2 = stamper.stamp(PlotEvent(spec={"fn": "sin(x)"}))
        # op_ids should be unique and monotonically increasing
        assert r1.op_id != r2.op_id

    def test_plot_payload(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        r = stamper.stamp(PlotEvent(spec={"fn": "x^2", "domain": [-5, 5]}))
        assert r.op_type == "plot"
        assert r.payload == {"spec": {"fn": "x^2", "domain": [-5, 5]}}

    def test_diagram_payload(self) -> None:
        stamper = OffsetStamper(turn_id=1)
        r = stamper.stamp(DiagramEvent(spec={"type": "tree", "nodes": 3}))
        assert r.op_type == "diagram"
        assert r.payload == {"spec": {"type": "tree", "nodes": 3}}


# ---------------------------------------------------------------------------
# 2. EpochGuard core tests
# ---------------------------------------------------------------------------


class TestEpochGuardStaleTurn:
    """Rejects any schedule/packet whose turn_id is below active_turn_id."""

    def test_reject_stale_turn_id(self) -> None:
        guard = EpochGuard(active_turn_id=5)
        op = BoardOp(op_id="op_1", op_type="latex", playout_offset_ms=100)
        assert guard.accept(turn_id=3, op=op) is False

    def test_accept_current_turn(self) -> None:
        guard = EpochGuard(active_turn_id=5)
        op = BoardOp(op_id="op_1", op_type="latex", playout_offset_ms=100)
        assert guard.accept(turn_id=5, op=op) is True


class TestEpochGuardDedup:
    """Dedupes by op_id within a turn (a repeated op_id is scheduled once)."""

    def test_duplicate_op_id_rejected(self) -> None:
        guard = EpochGuard(active_turn_id=1)
        op = BoardOp(op_id="op_42", op_type="latex", playout_offset_ms=200)
        assert guard.accept(turn_id=1, op=op) is True
        assert guard.accept(turn_id=1, op=op) is False  # duplicate

    def test_same_op_id_different_turn_allowed_after_advance(self) -> None:
        guard = EpochGuard(active_turn_id=1)
        op = BoardOp(op_id="op_42", op_type="latex", playout_offset_ms=200)
        guard.accept(turn_id=1, op=op)
        guard.advance_turn(2)
        assert guard.accept(turn_id=2, op=op) is True  # new turn, dedup reset


class TestEpochGuardInterruptReconciliation:
    """INTERRUPT_FLUSH reconciliation: compute unrendered ops."""

    def test_interrupt_after_step1_returns_unrendered_steps_2_to_4(self) -> None:
        guard = EpochGuard(active_turn_id=1)

        ops = [
            BoardOp(op_id="op_1", op_type="latex", playout_offset_ms=100),
            BoardOp(op_id="op_2", op_type="latex", playout_offset_ms=300),
            BoardOp(op_id="op_3", op_type="plot", playout_offset_ms=600),
            BoardOp(op_id="op_4", op_type="latex", playout_offset_ms=900),
        ]
        for op in ops:
            guard.accept(turn_id=1, op=op)

        # Only op_1 was rendered
        guard.mark_rendered("op_1")

        unrendered = guard.reconcile_unrendered()
        unrendered_ids = [op.op_id for op in unrendered]
        assert unrendered_ids == ["op_2", "op_3", "op_4"]

    def test_resume_with_nothing_unrendered(self) -> None:
        guard = EpochGuard(active_turn_id=1)
        ops = [
            BoardOp(op_id="op_1", op_type="latex", playout_offset_ms=100),
            BoardOp(op_id="op_2", op_type="latex", playout_offset_ms=300),
        ]
        for op in ops:
            guard.accept(turn_id=1, op=op)
        guard.mark_rendered("op_1")
        guard.mark_rendered("op_2")

        unrendered = guard.reconcile_unrendered()
        assert unrendered == []

    def test_unrendered_ops_in_original_order(self) -> None:
        guard = EpochGuard(active_turn_id=1)
        ops = [
            BoardOp(op_id="op_a", op_type="latex", playout_offset_ms=100),
            BoardOp(op_id="op_b", op_type="plot", playout_offset_ms=200),
            BoardOp(op_id="op_c", op_type="diagram", playout_offset_ms=300),
            BoardOp(op_id="op_d", op_type="latex", playout_offset_ms=400),
        ]
        for op in ops:
            guard.accept(turn_id=1, op=op)

        # Only op_a and op_c rendered (non-contiguous)
        guard.mark_rendered("op_a")
        guard.mark_rendered("op_c")

        unrendered = guard.reconcile_unrendered()
        ids = [op.op_id for op in unrendered]
        assert ids == ["op_b", "op_d"]  # original order preserved

    def test_epoch_guard_reconcile_with_played_ms(self) -> None:
        """Ops with playout_offset_ms <= played_ms are inferred to be rendered."""
        guard = EpochGuard(active_turn_id=1)
        ops = [
            BoardOp(op_id="op_1_1", op_type="latex", playout_offset_ms=100),
            BoardOp(op_id="op_1_2", op_type="latex", playout_offset_ms=300),
            BoardOp(op_id="op_1_3", op_type="plot", playout_offset_ms=600),
        ]
        for op in ops:
            guard.accept(turn_id=1, op=op)

        # Student interrupts at 350ms played: op_1_1 and op_1_2 are rendered
        unrendered = guard.reconcile_unrendered(played_ms=350)
        assert [op.op_id for op in unrendered] == ["op_1_3"]

    def test_epoch_guard_mark_rendered_up_to(self) -> None:
        """Marking rendered up to an op_id marks it and all preceding ops."""
        guard = EpochGuard(active_turn_id=1)
        ops = [
            BoardOp(op_id="op_1_1", op_type="latex", playout_offset_ms=100),
            BoardOp(op_id="op_1_2", op_type="latex", playout_offset_ms=300),
            BoardOp(op_id="op_1_3", op_type="plot", playout_offset_ms=600),
        ]
        for op in ops:
            guard.accept(turn_id=1, op=op)

        guard.mark_rendered_up_to("op_1_2")
        unrendered = guard.reconcile_unrendered()
        assert [op.op_id for op in unrendered] == ["op_1_3"]

    def test_advance_turn_clears_tracking(self) -> None:
        guard = EpochGuard(active_turn_id=1)
        op = BoardOp(op_id="op_1", op_type="latex", playout_offset_ms=100)
        guard.accept(turn_id=1, op=op)
        guard.mark_rendered("op_1")

        guard.advance_turn(2)
        # After turn advance, no ops tracked for new turn
        assert guard.reconcile_unrendered() == []
