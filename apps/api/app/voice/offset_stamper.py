"""PCM Offset Stamper & Epoch Guard — Phase 7 core module.

The OffsetStamper tracks cumulative 24kHz PCM samples per turn, stamps
board directives with exact playout_offset_ms, and emits AUDIO_SEGMENT_START.

The EpochGuard rejects stale-turn packets, deduplicates by op_id, and
reconciles unrendered ops for the Phase 4 resume_stack.

Rounding rule: playout_offset_ms = cumulative_samples // 24  (integer
division, i.e. floor).  24 = SAMPLE_RATE / 1000.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Union

from app.llm.stream_parser import ClearEvent, DiagramEvent, LatexEvent, PlotEvent
from app.schemas.events import AudioSegmentStartEvent, BoardOp
from app.voice.tts import SAMPLE_RATE, PCMCursor

# Samples per millisecond at 24 kHz.
_SAMPLES_PER_MS: int = SAMPLE_RATE // 1000  # 24


# ---------------------------------------------------------------------------
# StampResult — returned by OffsetStamper.stamp()
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class StampResult:
    """Result of stamping a directive with its playout offset."""

    op_id: str
    op_type: str
    playout_offset_ms: int
    turn_id: int
    payload: dict  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# OffsetStamper
# ---------------------------------------------------------------------------
DirectiveEvent = Union[LatexEvent, PlotEvent, DiagramEvent, ClearEvent]


class OffsetStamper:
    """Tracks cumulative 24 kHz PCM samples per turn_id.

    Reuses the Phase 5 PCMCursor as the single source of truth for sample
    accounting when provided. Every synthesized frame advances the cursor
    (including the 150 ms silence lead-in and filler clips, each tagged
    with its segment_id).

    ``stamp(directive)`` returns the exact ``playout_offset_ms`` at the
    instant the directive appears in the stream.
    """

    def __init__(self, turn_id: int = 0, cursor: PCMCursor | None = None) -> None:
        self.turn_id: int = turn_id
        self.cursor: PCMCursor = (
            cursor if cursor is not None else PCMCursor(turn_id=turn_id)
        )
        self._op_counter: int = 0

    # -- sample accounting (single source of truth) -------------------------

    def advance_samples(self, n: int) -> None:
        """Advance the cumulative sample count by *n* samples."""
        self.cursor.total_samples += n

    @property
    def cumulative_samples(self) -> int:
        return self.cursor.total_samples

    @property
    def offset_ms(self) -> int:
        """Current playout offset in ms (integer floor division)."""
        return self.cursor.total_samples // _SAMPLES_PER_MS

    # -- stamping directives -------------------------------------------------

    def stamp(self, directive: DirectiveEvent) -> StampResult:
        """Stamp a board directive with its playout offset.

        Returns a ``StampResult`` carrying ``{turn_id, op_id,
        playout_offset_ms, op_type, payload}``.

        ``op_id`` is scoped by turn_id to guarantee global uniqueness across
        turns, preventing client-side deduplication collisions.
        """
        self._op_counter += 1
        op_id = f"op_{self.turn_id}_{self._op_counter}"

        if isinstance(directive, LatexEvent):
            op_type = "latex"
            payload: dict = {"latex": directive.latex}  # type: ignore[type-arg]
        elif isinstance(directive, PlotEvent):
            op_type = "plot"
            payload = {"spec": directive.spec}
        elif isinstance(directive, DiagramEvent):
            op_type = "diagram"
            payload = {"spec": directive.spec}
        elif isinstance(directive, ClearEvent):
            op_type = "clear"
            payload = {}
        else:
            raise TypeError(f"Unsupported directive type: {type(directive)}")

        return StampResult(
            op_id=op_id,
            op_type=op_type,
            playout_offset_ms=self.cursor.total_samples // _SAMPLES_PER_MS,
            turn_id=self.turn_id,
            payload=payload,
        )

    # -- segment start events ------------------------------------------------

    def emit_segment_start(
        self, segment_id: Literal["filler", "response"]
    ) -> AudioSegmentStartEvent:
        """Return an AUDIO_SEGMENT_START event for the current turn."""
        return AudioSegmentStartEvent(
            turn_id=self.turn_id,
            segment_id=segment_id,
        )

    # -- turn lifecycle ------------------------------------------------------

    def reset(self, turn_id: int) -> None:
        """Reset for a new turn. Cumulative samples restart at 0."""
        self.turn_id = turn_id
        self.cursor.reset(turn_id)
        self._op_counter = 0


# ---------------------------------------------------------------------------
# EpochGuard
# ---------------------------------------------------------------------------


class EpochGuard:
    """Epoch & deduplication guard.

    * Rejects any schedule whose ``turn_id`` is below ``active_turn_id``.
    * Dedupes by ``op_id`` within a turn (a repeated ``op_id`` is
      scheduled once).
    * On INTERRUPT_FLUSH reconciliation, computes which scheduled ops were
      never rendered so the Phase 4 ``resume_stack`` re-schedules ONLY
      unrendered ops in original order.
    """

    def __init__(self, active_turn_id: int = 0) -> None:
        self.active_turn_id: int = active_turn_id
        self._seen_op_ids: set[str] = set()
        # Ordered list of accepted ops for reconciliation.
        self._accepted_ops: list[BoardOp] = []
        self._rendered_op_ids: set[str] = set()

    def accept(self, turn_id: int, op: BoardOp) -> bool:
        """Return ``True`` if this op should be scheduled; ``False`` to drop."""
        if turn_id < self.active_turn_id:
            return False
        if op.op_id in self._seen_op_ids:
            return False
        self._seen_op_ids.add(op.op_id)
        self._accepted_ops.append(op)
        return True

    def mark_rendered(self, op_id: str) -> None:
        """Record that an op was actually rendered on the board."""
        self._rendered_op_ids.add(op_id)

    def mark_rendered_up_to(self, op_id: str) -> None:
        """Mark op_id and all ops scheduled prior to it as rendered."""
        for op in self._accepted_ops:
            self._rendered_op_ids.add(op.op_id)
            if op.op_id == op_id:
                break

    def reconcile_unrendered(self, played_ms: int | None = None) -> list[BoardOp]:
        """Return unrendered ops in original schedule order.

        Used after INTERRUPT_FLUSH so the resume_stack re-schedules ONLY
        unrendered ops. If played_ms is provided, any op whose playout_offset_ms
        is <= played_ms is inferred to have already been rendered.
        """
        return [
            op
            for op in self._accepted_ops
            if op.op_id not in self._rendered_op_ids
            and (played_ms is None or op.playout_offset_ms > played_ms)
        ]

    def advance_turn(self, new_turn_id: int) -> None:
        """Advance to a new turn, clearing all tracking state."""
        self.active_turn_id = new_turn_id
        self._seen_op_ids.clear()
        self._accepted_ops.clear()
        self._rendered_op_ids.clear()
