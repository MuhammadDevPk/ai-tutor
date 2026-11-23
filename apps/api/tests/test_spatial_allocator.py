"""Tests for the Spatial Layout Allocator (apps/api/app/board/allocator.py).

P3 Core Module Honest TDD:
- 1280x720 canvas with 4 non-overlapping zones: header, derivation, visual, callout.
- Bounding box estimation heuristic: base height per line, extra for fractions,
  integrals, matrices.
- Non-overlapping placement within target zones.
- Zone isolation (derivation ops in derivation zone, visual ops in visual zone).
- Capacity management: CLEAR_SLIDE decision when vertical capacity is full.
- Semantic summary: active element labels + raw LaTeX/expressions only,
  <= 300 tokens, zero JSON scene keys.
- Property test with fixed seed: zero pairwise overlaps across randomized op sequences.
- Deterministic repeatability.
"""

import random
from typing import Any

from app.board.allocator import (
    CANVAS_HEIGHT,
    CANVAS_WIDTH,
    ZONE_CALLOUT,
    ZONE_DERIVATION,
    ZONE_HEADER,
    ZONE_VISUAL,
    AllocationResult,
    BoardOpInput,
    Rect,
    SpatialAllocator,
    estimate_content_bbox,
)


def rects_overlap(r1: Rect, r2: Rect, margin: float = 0.0) -> bool:
    """Return True if two rectangles overlap with an optional tolerance margin."""
    return not (
        r1.x + r1.width + margin <= r2.x
        or r2.x + r2.width + margin <= r1.x
        or r1.y + r1.height + margin <= r2.y
        or r2.y + r2.height + margin <= r1.y
    )


def rect_contains(container: Rect, inner: Rect) -> bool:
    """Return True if inner rectangle is strictly within container bounds."""
    return (
        inner.x >= container.x - 1e-6
        and inner.y >= container.y - 1e-6
        and inner.x + inner.width <= container.x + container.width + 1e-6
        and inner.y + inner.height <= container.y + container.height + 1e-6
    )


class TestZoneGeometry:
    """Test virtual canvas 1280x720 and 4 non-overlapping zones."""

    def test_canvas_dimensions(self) -> None:
        assert CANVAS_WIDTH == 1280
        assert CANVAS_HEIGHT == 720

    def test_all_zones_within_canvas(self) -> None:
        canvas = Rect(x=0, y=0, width=CANVAS_WIDTH, height=CANVAS_HEIGHT)
        zones = [ZONE_HEADER, ZONE_DERIVATION, ZONE_VISUAL, ZONE_CALLOUT]
        for z in zones:
            assert rect_contains(canvas, z), f"Zone {z} exceeds canvas boundaries"

    def test_zones_mutually_non_overlapping(self) -> None:
        zones = [
            ("header", ZONE_HEADER),
            ("derivation", ZONE_DERIVATION),
            ("visual", ZONE_VISUAL),
            ("callout", ZONE_CALLOUT),
        ]
        for i in range(len(zones)):
            for j in range(i + 1, len(zones)):
                name1, z1 = zones[i]
                name2, z2 = zones[j]
                assert not rects_overlap(z1, z2), (
                    f"Zones '{name1}' and '{name2}' overlap!"
                )


class TestBboxEstimationHeuristic:
    """Test table-driven LaTeX and visual element bounding box estimation."""

    def test_base_single_line_latex(self) -> None:
        bbox = estimate_content_bbox("latex", "E = mc^2")
        assert bbox.width > 0
        assert bbox.height >= 40

    def test_tall_fraction_increases_height(self) -> None:
        base_bbox = estimate_content_bbox("latex", "a + b = c")
        frac_bbox = estimate_content_bbox("latex", r"\frac{a + b}{c - d} = x")
        assert frac_bbox.height > base_bbox.height
        assert frac_bbox.height >= base_bbox.height + 25

    def test_nested_fraction_increases_height_further(self) -> None:
        single_frac = estimate_content_bbox("latex", r"\frac{a}{b}")
        nested_frac = estimate_content_bbox(
            "latex", r"\frac{\frac{a}{b}}{\frac{c}{d}}"
        )
        assert nested_frac.height > single_frac.height

    def test_integral_with_limits_increases_height_and_width(self) -> None:
        base_bbox = estimate_content_bbox("latex", "f(x) dx")
        int_bbox = estimate_content_bbox("latex", r"\int_{0}^{\infty} e^{-x^2} dx")
        assert int_bbox.height > base_bbox.height
        assert int_bbox.width > base_bbox.width

    def test_summation_with_limits(self) -> None:
        base_bbox = estimate_content_bbox("latex", "k^2")
        sum_bbox = estimate_content_bbox("latex", r"\sum_{k=1}^{n} k^2")
        assert sum_bbox.height > base_bbox.height

    def test_matrix_scales_with_rows_and_cols(self) -> None:
        matrix_1x2 = estimate_content_bbox(
            "latex", r"\begin{pmatrix} a & b \end{pmatrix}"
        )
        matrix_3x3 = estimate_content_bbox(
            "latex",
            r"\begin{pmatrix} a & b & c \\ d & e & f \\ g & h & i \end{pmatrix}",
        )
        assert matrix_3x3.height > matrix_1x2.height + 40
        assert matrix_3x3.width > matrix_1x2.width

    def test_plot_and_diagram_defaults(self) -> None:
        plot_bbox = estimate_content_bbox("plot", {"fn": "x^2", "domain": [-5, 5]})
        diagram_bbox = estimate_content_bbox("diagram", {"type": "box"})
        assert plot_bbox.width > 200
        assert plot_bbox.height > 150
        assert diagram_bbox.width > 200
        assert diagram_bbox.height > 150

    def test_plot_with_nested_spec_payload(self) -> None:
        # LLM stream parser outputs PlotEvent(spec={"fn": "sin(x)", "domain": [-3, 3]})
        # which is wrapped into payload={"spec": ...}
        bbox = estimate_content_bbox(
            "plot", {"spec": {"fn": "sin(x)", "width": 380, "height": 280}}
        )
        assert bbox.width == 380
        assert bbox.height == 280

        allocator = SpatialAllocator()
        res = allocator.allocate(
            BoardOpInput(
                op_id="op_spec_plot",
                op_type="plot",
                payload={"spec": {"fn": "sin(x)"}},
                label="Sin Plot",
            )
        )
        assert res.decision == "PLACED"
        assert "plot(sin(x))" in allocator.summary()


class TestSpatialAllocation:
    """Test allocation, zone routing, collision prevention, and pagination."""

    def test_derivation_op_lands_in_derivation_zone(self) -> None:
        allocator = SpatialAllocator()
        res = allocator.allocate(
            BoardOpInput(
                op_id="op_1",
                op_type="latex",
                payload={"latex": r"f'(x) = \lim_{h \to 0} \frac{f(x+h) - f(x)}{h}"},
                label="Step 1: Derivative definition",
            )
        )
        assert res.decision == "PLACED"
        assert res.placement is not None
        assert res.placement.zone == "derivation"
        placed_rect = Rect(
            x=res.placement.x,
            y=res.placement.y,
            width=res.placement.width,
            height=res.placement.height,
        )
        assert rect_contains(ZONE_DERIVATION, placed_rect)
        # Isolation: not in visual zone
        assert not rects_overlap(placed_rect, ZONE_VISUAL)

    def test_visual_op_lands_in_visual_zone(self) -> None:
        allocator = SpatialAllocator()
        res = allocator.allocate(
            BoardOpInput(
                op_id="op_plot",
                op_type="plot",
                payload={"fn": "sin(x)", "domain": [-3.14, 3.14]},
                label="Sine plot",
            )
        )
        assert res.decision == "PLACED"
        assert res.placement is not None
        assert res.placement.zone == "visual"
        placed_rect = Rect(
            x=res.placement.x,
            y=res.placement.y,
            width=res.placement.width,
            height=res.placement.height,
        )
        assert rect_contains(ZONE_VISUAL, placed_rect)
        # Isolation: not in derivation zone
        assert not rects_overlap(placed_rect, ZONE_DERIVATION)

    def test_sequential_ops_do_not_overlap(self) -> None:
        allocator = SpatialAllocator()
        res1 = allocator.allocate(
            BoardOpInput(op_id="1", op_type="latex", payload={"latex": "A = B + C"})
        )
        res2 = allocator.allocate(
            BoardOpInput(op_id="2", op_type="latex", payload={"latex": "C = D + E"})
        )
        res3 = allocator.allocate(
            BoardOpInput(op_id="3", op_type="latex", payload={"latex": "E = mc^2"})
        )

        assert res1.decision == "PLACED" and res1.placement is not None
        assert res2.decision == "PLACED" and res2.placement is not None
        assert res3.decision == "PLACED" and res3.placement is not None

        r1 = Rect(
            res1.placement.x,
            res1.placement.y,
            res1.placement.width,
            res1.placement.height,
        )
        r2 = Rect(
            res2.placement.x,
            res2.placement.y,
            res2.placement.width,
            res2.placement.height,
        )
        r3 = Rect(
            res3.placement.x,
            res3.placement.y,
            res3.placement.width,
            res3.placement.height,
        )

        assert not rects_overlap(r1, r2)
        assert not rects_overlap(r2, r3)
        assert not rects_overlap(r1, r3)

    def test_vertical_overflow_triggers_clear_slide(self) -> None:
        allocator = SpatialAllocator()
        placed_count = 0
        last_res: AllocationResult | None = None

        # Derivation zone has finite vertical height (480px).
        # Feed enough tall equations until it overflows.
        latex_payload = {
            "latex": r"\frac{d}{dx}\left(\int_0^x e^{-t^2} dt\right) = e^{-x^2}"
        }
        for i in range(20):
            res = allocator.allocate(
                BoardOpInput(
                    op_id=f"eq_{i}",
                    op_type="latex",
                    payload=latex_payload,
                    label=f"Step {i}",
                )
            )
            last_res = res
            if res.decision == "CLEAR_SLIDE":
                break
            placed_count += 1

        assert last_res is not None
        assert last_res.decision == "CLEAR_SLIDE"
        assert last_res.placement is None
        assert placed_count > 0  # It placed some before overflowing

    def test_reset_slide_clears_capacity(self) -> None:
        allocator = SpatialAllocator()
        # Fill capacity until CLEAR_SLIDE
        for i in range(25):
            res = allocator.allocate(
                BoardOpInput(
                    op_id=f"eq_{i}",
                    op_type="latex",
                    payload={"latex": r"\frac{a}{b}"},
                )
            )
            if res.decision == "CLEAR_SLIDE":
                break

        assert (
            allocator.allocate(
                BoardOpInput(
                    op_id="overflow", op_type="latex", payload={"latex": "x=1"}
                )
            ).decision
            == "CLEAR_SLIDE"
        )

        allocator.reset_slide()

        # Should place successfully now
        res_after_reset = allocator.allocate(
            BoardOpInput(op_id="fresh_1", op_type="latex", payload={"latex": "x=1"})
        )
        assert res_after_reset.decision == "PLACED"
        assert res_after_reset.placement is not None
        assert res_after_reset.placement.y == ZONE_DERIVATION.y

    def test_deterministic_repeatability(self) -> None:
        ops = [
            BoardOpInput(op_id="1", op_type="header", payload={"text": "Lecture 1"}),
            BoardOpInput(op_id="2", op_type="latex", payload={"latex": r"\int x dx"}),
            BoardOpInput(op_id="3", op_type="plot", payload={"fn": "x^2"}),
            BoardOpInput(
                op_id="4",
                op_type="latex",
                payload={"latex": r"\frac{1}{2} x^2 + C"},
            ),
            BoardOpInput(
                op_id="5", op_type="callout", payload={"text": "Note: constant C"}
            ),
        ]

        alloc1 = SpatialAllocator()
        res1 = [alloc1.allocate(op) for op in ops]

        alloc2 = SpatialAllocator()
        res2 = [alloc2.allocate(op) for op in ops]

        assert len(res1) == len(res2)
        for r1, r2 in zip(res1, res2):
            assert r1.decision == r2.decision
            if r1.placement and r2.placement:
                assert r1.placement.x == r2.placement.x
                assert r1.placement.y == r2.placement.y
                assert r1.placement.width == r2.placement.width
                assert r1.placement.height == r2.placement.height
                assert r1.placement.zone == r2.placement.zone


class TestBoardSummary:
    """Test semantic summary representation and token budget fitting."""

    def test_summary_contains_labels_and_raw_latex_only(self) -> None:
        allocator = SpatialAllocator()
        allocator.allocate(
            BoardOpInput(
                op_id="step_1",
                op_type="latex",
                payload={
                    "latex": r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}"
                },
                label="Gauss's Law",
            )
        )
        allocator.allocate(
            BoardOpInput(
                op_id="step_2",
                op_type="latex",
                payload={"latex": r"\nabla \times \mathbf{B} = \mu_0 \mathbf{J}"},
                label="Ampere's Law",
            )
        )

        summary = allocator.summary()
        # Verify labels and LaTeX are present
        assert "Gauss's Law" in summary
        assert r"\nabla \cdot \mathbf{E} = \frac{\rho}{\varepsilon_0}" in summary
        assert "Ampere's Law" in summary

        # Critical: NO JSON scene keys (no Excalidraw elements)
        forbidden_keys = [
            '"elements"',
            '"type"',
            '"strokeColor"',
            '"backgroundColor"',
            '"roughness"',
            '"angle"',
            '"roundness"',
            '"customData"',
        ]
        for key in forbidden_keys:
            assert key not in summary

    def test_summary_fits_300_token_budget(self) -> None:
        allocator = SpatialAllocator()
        for i in range(10):
            allocator.allocate(
                BoardOpInput(
                    op_id=f"op_{i}",
                    op_type="latex",
                    payload={
                        "latex": (
                            f"y_{i} = \\sum_{{k=1}}^{{10}} x_{{i, k}}^2 + \\alpha_{i}"
                        )
                    },
                    label=f"Long Equation Label Step Number {i} With Explanatory Text",
                )
            )

        summary = allocator.summary()
        # Chars/4 token count <= 300
        estimated_tokens = (len(summary) + 3) // 4
        assert estimated_tokens <= 300

    def test_summary_cleared_on_reset(self) -> None:
        allocator = SpatialAllocator()
        allocator.allocate(
            BoardOpInput(
                op_id="1",
                op_type="latex",
                payload={"latex": "E = mc^2"},
                label="Mass-Energy",
            )
        )
        assert "Mass-Energy" in allocator.summary()
        allocator.reset_slide()
        assert allocator.summary() == ""


class TestAdversarialPropertyLoop:
    """Property test ensuring zero overlaps across randomized op sequences."""

    def test_zero_pairwise_overlaps_across_random_sequences(self) -> None:
        rng = random.Random(42)
        op_types = ["latex", "plot", "diagram", "callout", "header"]
        sample_latex = [
            "x + y = z",
            r"\frac{a + b}{c + d}",
            r"\int_0^\infty e^{-x} dx = 1",
            r"\begin{pmatrix} 1 & 0 \\ 0 & 1 \end{pmatrix}",
            r"\sum_{n=1}^\infty \frac{1}{n^2} = \frac{\pi^2}{6}",
            r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
        ]

        allocator = SpatialAllocator()

        for iteration in range(100):
            op_type = rng.choice(op_types)
            op_id = f"rand_{iteration}"
            payload: dict[str, Any] = {}
            if op_type == "latex":
                payload = {"latex": rng.choice(sample_latex)}
            elif op_type == "plot":
                payload = {"fn": "x^2", "domain": [-5, 5]}
            elif op_type == "diagram":
                payload = {"type": "flowchart"}
            elif op_type == "callout":
                payload = {"text": "Random callout note"}
            elif op_type == "header":
                payload = {"text": f"Section {iteration}"}

            res = allocator.allocate(
                BoardOpInput(
                    op_id=op_id,
                    op_type=op_type,
                    payload=payload,
                    label=f"Item {iteration}",
                )
            )

            if res.decision == "CLEAR_SLIDE":
                allocator.reset_slide()
                continue

            # Verify every currently active placed rect has zero overlap with any other
            active_rects = [
                Rect(p.x, p.y, p.width, p.height)
                for p in allocator.active_placements
            ]

            for i in range(len(active_rects)):
                for j in range(i + 1, len(active_rects)):
                    assert not rects_overlap(active_rects[i], active_rects[j]), (
                        f"Overlap detected between element {i} and {j} on slide!"
                    )
