"""Spatial Layout Allocator for the 1280x720 Virtual Whiteboard (Phase 6 Core Module).

Manages virtual canvas 1280x720 across four non-overlapping zones:
- header: top strip for title / context
- derivation: left/center main column for step-by-step mathematical derivations
- visual: right panel for plots and geometric/block diagrams
- callout: bottom strip for micro-check questions, notes, or tips

Enforces:
- Table-driven LaTeX and visual element bounding box estimation.
- Non-overlapping placement within designated zones.
- Zone isolation (derivation ops never placed in visual zone, etc.).
- CLEAR_SLIDE trigger upon vertical capacity exhaustion.
- Semantic board summary (active labels + raw LaTeX/expressions only, <= 300 tokens,
  zero Excalidraw scene JSON keys).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.tutor.budget import (
    WHITEBOARD_SUMMARY_CEILING,
    CharsTokenCounter,
    truncate_text_to_tokens,
)

# Canvas dimensions
CANVAS_WIDTH: float = 1280.0
CANVAS_HEIGHT: float = 720.0


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in virtual canvas coordinates."""

    x: float
    y: float
    width: float
    height: float

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    def overlaps(self, other: Rect, margin: float = 0.0) -> bool:
        """Return True if this rectangle overlaps with another with optional margin."""
        return not (
            self.right + margin <= other.x
            or other.right + margin <= self.x
            or self.bottom + margin <= other.y
            or other.bottom + margin <= self.y
        )

    def contains(self, other: Rect) -> bool:
        """Return True if this rectangle completely encloses the other."""
        return (
            other.x >= self.x - 1e-6
            and other.y >= self.y - 1e-6
            and other.right <= self.right + 1e-6
            and other.bottom <= self.bottom + 1e-6
        )


# Four non-overlapping zones with 20px gutters and margins
ZONE_HEADER = Rect(x=40.0, y=20.0, width=1200.0, height=60.0)
ZONE_DERIVATION = Rect(x=40.0, y=100.0, width=740.0, height=480.0)
ZONE_VISUAL = Rect(x=800.0, y=100.0, width=440.0, height=480.0)
ZONE_CALLOUT = Rect(x=40.0, y=600.0, width=1200.0, height=100.0)

ZONES: dict[str, Rect] = {
    "header": ZONE_HEADER,
    "derivation": ZONE_DERIVATION,
    "visual": ZONE_VISUAL,
    "callout": ZONE_CALLOUT,
}


@dataclass(frozen=True)
class Placement:
    """Resolved placement for an element on the canvas."""

    x: float
    y: float
    width: float
    height: float
    zone: str
    op_id: str | None = None

    @property
    def rect(self) -> Rect:
        return Rect(x=self.x, y=self.y, width=self.width, height=self.height)


@dataclass(frozen=True)
class AllocationResult:
    """Result of an allocation request."""

    decision: Literal["PLACED", "CLEAR_SLIDE"]
    placement: Placement | None = None
    reason: str | None = None

    @property
    def is_placed(self) -> bool:
        return self.decision == "PLACED"

    @property
    def is_clear_slide(self) -> bool:
        return self.decision == "CLEAR_SLIDE"


@dataclass
class BoardOpInput:
    """Input representation for a board operation to allocate."""

    op_id: str
    op_type: str
    payload: dict[str, Any] | str = field(default_factory=dict)
    label: str = ""
    zone: str | None = None


@dataclass
class ActiveBoardItem:
    """Active board element tracked for summary and scene state."""

    op_id: str
    op_type: str
    label: str
    raw_content: str
    placement: Placement


def _extract_raw_expression(op_type: str, payload: dict[str, Any] | str) -> str:
    """Extract raw LaTeX or plot expression string from payload."""
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return str(payload)

    op_lower = op_type.lower()
    if op_lower == "latex":
        val = (
            payload.get("latex")
            or payload.get("raw")
            or payload.get("expression")
            or ""
        )
        return str(val)
    elif op_lower == "plot":
        spec_candidate = payload.get("spec") if isinstance(payload, dict) else None
        spec: dict[str, Any] = (
            spec_candidate
            if isinstance(spec_candidate, dict)
            else (payload if isinstance(payload, dict) else {})
        )
        fn = spec.get("fn") or spec.get("expression") or ""
        return f"plot({fn})" if fn else "plot"
    elif op_lower == "diagram":
        spec_candidate = payload.get("spec") if isinstance(payload, dict) else None
        spec = (
            spec_candidate
            if isinstance(spec_candidate, dict)
            else (payload if isinstance(payload, dict) else {})
        )
        dtype = spec.get("type") or "diagram"
        return f"diagram({dtype})"
    elif op_lower in ("header", "callout", "text"):
        return str(payload.get("text") or payload.get("title") or "")
    return ""


def estimate_content_bbox(
    op_type: str,
    content: Any,
    target_zone: Rect | None = None,
) -> Rect:
    """Estimate the bounding box (width, height) for a given board operation.

    Table-driven heuristic:
    - Base single-line LaTeX: height ~48px, width ~12px/symbol.
    - Fractions (\\frac): +35px height per nesting depth.
    - Integrals (\\int), summations (\\sum), limits (\\lim): +32px height, +35px width.
    - Matrices (\\begin{pmatrix}): +30px height per row, +50px width per column.
    - Superscripts/Subscripts: +10px height if present.
    - Plots: fixed default 400x300.
    - Diagrams: fixed default 400x240.
    - Header: 1120x44.
    - Callout: 1000x60.
    """
    op_type_lower = op_type.lower()

    if op_type_lower == "latex":
        latex_str = ""
        if isinstance(content, str):
            latex_str = content
        elif isinstance(content, dict):
            val = (
                content.get("latex")
                or content.get("raw")
                or content.get("expression")
                or ""
            )
            latex_str = str(val)

        base_height = 48.0
        extra_height = 0.0

        # 1. Fractions: count and nesting check
        frac_matches = len(re.findall(r"\\(?:c|d)?frac", latex_str))
        if frac_matches > 0:
            extra_height += 35.0
            # Nested fractions (e.g. frac containing another frac)
            nested_fracs = len(
                re.findall(r"\\(?:c|d)?frac\{[^{}]*\\(?:c|d)?frac", latex_str)
            )
            if nested_fracs > 0:
                extra_height += 35.0 * nested_fracs
            elif frac_matches > 1:
                extra_height += 15.0 * (frac_matches - 1)

        # 2. Big operators: integrals, sums, products, limits
        big_ops = len(
            re.findall(
                r"\\(?:int|iint|iiint|oint|sum|prod|coprod|lim|bigcap|bigcup)",
                latex_str,
            )
        )
        if big_ops > 0:
            extra_height += 32.0

        # 3. Matrices / arrays / cases
        matrix_match = re.search(
            r"\\begin\{(?:pmatrix|bmatrix|vmatrix|Vmatrix|matrix|array|cases)\}"
            r"(.*?)\\end\{",
            latex_str,
            re.DOTALL,
        )
        matrix_cols = 1
        if matrix_match:
            matrix_body = matrix_match.group(1)
            rows = matrix_body.split(r"\\")
            num_rows = len(rows)
            extra_height += max(0, num_rows - 1) * 32.0
            for r in rows:
                cols = len(r.split("&"))
                if cols > matrix_cols:
                    matrix_cols = cols

        # 4. Superscripts & subscripts
        if re.search(r"[\^_]", latex_str) and frac_matches == 0 and big_ops == 0:
            extra_height += 10.0

        total_height = base_height + extra_height

        # Width estimation
        # Strip common LaTeX command names to measure symbol length
        clean_symbols = re.sub(r"\\[a-zA-Z]+", " ", latex_str)
        symbol_count = max(len(clean_symbols.strip()), 4)
        est_width = 40.0 + symbol_count * 13.0
        if big_ops > 0:
            est_width += 35.0 * big_ops
        if matrix_cols > 1:
            est_width += (matrix_cols - 1) * 55.0

        # Clamp width to sensible bounds for derivation zone
        max_allowed_width = (target_zone.width - 20.0) if target_zone else 700.0
        final_width = min(max(est_width, 140.0), max_allowed_width)

        return Rect(x=0.0, y=0.0, width=final_width, height=total_height)

    elif op_type_lower == "plot":
        # Check custom dimensions if provided
        width = 400.0
        height = 300.0
        if isinstance(content, dict):
            spec_candidate = content.get("spec")
            spec: dict[str, Any] = (
                spec_candidate if isinstance(spec_candidate, dict) else content
            )
            width = float(spec.get("width") or 400.0)
            height = float(spec.get("height") or 300.0)
        if target_zone:
            width = min(width, target_zone.width - 20.0)
            height = min(height, target_zone.height)
        return Rect(x=0.0, y=0.0, width=width, height=height)

    elif op_type_lower == "diagram":
        width = 400.0
        height = 240.0
        if isinstance(content, dict):
            spec_candidate = content.get("spec")
            spec = (
                spec_candidate if isinstance(spec_candidate, dict) else content
            )
            width = float(spec.get("width") or 400.0)
            height = float(spec.get("height") or 240.0)
        if target_zone:
            width = min(width, target_zone.width - 20.0)
            height = min(height, target_zone.height)
        return Rect(x=0.0, y=0.0, width=width, height=height)

    elif op_type_lower in ("header", "title"):
        return Rect(x=0.0, y=0.0, width=1120.0, height=44.0)

    elif op_type_lower in ("callout", "text"):
        return Rect(x=0.0, y=0.0, width=1000.0, height=60.0)

    return Rect(x=0.0, y=0.0, width=300.0, height=60.0)


class SpatialAllocator:
    """Deterministic spatial layout allocator for the virtual whiteboard canvas."""

    def __init__(self, token_counter: CharsTokenCounter | None = None) -> None:
        self._active_placements: list[Placement] = []
        self._active_items: list[ActiveBoardItem] = []
        self._token_counter = token_counter or CharsTokenCounter()

    @property
    def active_placements(self) -> list[Placement]:
        """Return a shallow copy of active element placements on the current slide."""
        return list(self._active_placements)

    @property
    def active_items(self) -> list[ActiveBoardItem]:
        """Return a copy of active board items."""
        return list(self._active_items)

    def reset_slide(self) -> None:
        """Clear all active placements and items, resetting the slide capacity."""
        self._active_placements.clear()
        self._active_items.clear()

    def _resolve_target_zone(self, op: BoardOpInput) -> tuple[str, Rect]:
        """Resolve the designated target zone for a board operation."""
        if op.zone and op.zone.lower() in ZONES:
            zone_name = op.zone.lower()
            return zone_name, ZONES[zone_name]

        op_type = op.op_type.lower()
        if op_type in ("header", "title"):
            return "header", ZONE_HEADER
        elif op_type in ("plot", "diagram"):
            return "visual", ZONE_VISUAL
        elif op_type in ("callout", "text", "note"):
            return "callout", ZONE_CALLOUT
        else:
            # Default for latex and general derivation steps
            return "derivation", ZONE_DERIVATION

    def allocate(self, op: BoardOpInput | dict[str, Any] | Any) -> AllocationResult:
        """Allocate a free non-overlapping rectangle for a board op.

        If vertical capacity in the target zone is exhausted, returns CLEAR_SLIDE.
        """
        # Normalize input
        if isinstance(op, BoardOpInput):
            norm_op = op
        elif isinstance(op, dict):
            norm_op = BoardOpInput(
                op_id=str(op.get("op_id", "")),
                op_type=str(op.get("op_type", "latex")),
                payload=op.get("payload", {}),
                label=str(op.get("label", "")),
                zone=op.get("zone"),
            )
        else:
            # e.g. Pydantic BoardOp
            norm_op = BoardOpInput(
                op_id=getattr(op, "op_id", ""),
                op_type=getattr(op, "op_type", "latex"),
                payload=getattr(op, "payload", {}),
                label=getattr(op, "label", ""),
                zone=getattr(op, "zone", None),
            )

        if norm_op.op_type.lower() == "clear":
            self.reset_slide()
            return AllocationResult(
                decision="CLEAR_SLIDE", reason="Explicit clear op received"
            )

        zone_name, zone_rect = self._resolve_target_zone(norm_op)
        bbox = estimate_content_bbox(norm_op.op_type, norm_op.payload, zone_rect)

        # Find existing placements in the same zone
        zone_placements = [p for p in self._active_placements if p.zone == zone_name]

        # Inter-element vertical margin
        margin = 16.0

        if not zone_placements:
            candidate_y = zone_rect.y
        else:
            candidate_y = max(p.y + p.height for p in zone_placements) + margin

        candidate_x = zone_rect.x

        # Check vertical capacity
        if candidate_y + bbox.height > zone_rect.bottom + 1e-6:
            overflow_msg = (
                f"Vertical overflow in {zone_name} zone "
                f"({candidate_y + bbox.height:.1f} > {zone_rect.bottom:.1f})"
            )
            return AllocationResult(
                decision="CLEAR_SLIDE",
                reason=overflow_msg,
            )

        candidate_rect = Rect(
            x=candidate_x,
            y=candidate_y,
            width=bbox.width,
            height=bbox.height,
        )

        # Verify no overlap against any active placements on the slide
        for existing in self._active_placements:
            if candidate_rect.overlaps(existing.rect, margin=0.0):
                return AllocationResult(
                    decision="CLEAR_SLIDE",
                    reason=f"Unresolvable collision in zone {zone_name}",
                )

        # Successful placement
        placement = Placement(
            x=candidate_x,
            y=candidate_y,
            width=bbox.width,
            height=bbox.height,
            zone=zone_name,
            op_id=norm_op.op_id,
        )

        raw_content = _extract_raw_expression(norm_op.op_type, norm_op.payload)

        self._active_placements.append(placement)
        self._active_items.append(
            ActiveBoardItem(
                op_id=norm_op.op_id,
                op_type=norm_op.op_type,
                label=norm_op.label,
                raw_content=raw_content,
                placement=placement,
            )
        )

        return AllocationResult(decision="PLACED", placement=placement)

    def summary(self) -> str:
        """Produce the semantic summary of active whiteboard items.

        Returns:
            Formatted string of active elements' labels and raw expressions.
            Strictly <= 300 tokens (Phase 4 budget slot ceiling).
            Contains ZERO JSON scene keys.
        """
        if not self._active_items:
            return ""

        lines: list[str] = []
        for item in self._active_items:
            label = item.label.strip()
            content = item.raw_content.strip()
            if label and content:
                lines.append(f"[{label}]: {content}")
            elif content:
                lines.append(content)
            elif label:
                lines.append(f"[{label}]")

        full_summary = "\n".join(lines)

        # Truncate to Phase 4 300-token ceiling using standard helper
        truncated = truncate_text_to_tokens(
            full_summary,
            max_tokens=WHITEBOARD_SUMMARY_CEILING,
            counter=self._token_counter,
            marker=" [...]",
        )
        return truncated
