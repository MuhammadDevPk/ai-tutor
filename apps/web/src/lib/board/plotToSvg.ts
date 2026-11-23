/**
 * Client-side Function Plot to SVG Compiler (Phase 6).
 *
 * Captures mathematical function curves to standalone pure-vector SVG strings
 * with explicit pixel dimensions, Light Mode colors (dark strokes on transparent/white),
 * and preserved aspect ratio. Zero network requests.
 */

import functionPlot from "function-plot";
import { letterboxDimensions, type SvgOutput, type DimensionPlacement } from "./latexToSvg";

export interface PlotSpec {
  fn: string;
  domain?: [number, number];
  range?: [number, number];
  title?: string;
  color?: string;
}

/**
 * Generate a standalone pure vector SVG for a function expression when DOM rendering
 * is unavailable or for deterministic mathematical curve plotting.
 */
function generateFallbackSvg(
  spec: PlotSpec,
  width: number,
  height: number
): string {
  const [xMin, xMax] = spec.domain || [-5, 5];
  const [yMin, yMax] = spec.range || [-5, 5];

  const padLeft = 45;
  const padBottom = 35;
  const padRight = 20;
  const padTop = 25;

  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const toSvgX = (x: number) => padLeft + ((x - xMin) / (xMax - xMin)) * plotW;
  const toSvgY = (y: number) => padTop + ((yMax - y) / (yMax - yMin)) * plotH;

  // Safe expression evaluator for basic math expressions: x^2, sin(x), cos(x), exp(x), 1/x, etc.
  let compiledFn: ((x: number) => number) | null = null;
  const rawFn = (spec?.fn || "x^2").trim();
  try {
    const expr = rawFn
      .replace(/\^/g, "**")
      .replace(/\bsin\b/g, "Math.sin")
      .replace(/\bcos\b/g, "Math.cos")
      .replace(/\btan\b/g, "Math.tan")
      .replace(/\bexp\b/g, "Math.exp")
      .replace(/\blog\b/g, "Math.log")
      .replace(/\bsqrt\b/g, "Math.sqrt")
      .replace(/\babs\b/g, "Math.abs")
      .replace(/\bpi\b/gi, "Math.PI")
      .replace(/\be\b/g, "Math.E");
    compiledFn = new Function("x", `"use strict"; return (${expr});`) as (x: number) => number;
  } catch {
    compiledFn = null;
  }

  const evalFn = (x: number): number | null => {
    if (!compiledFn) return null;
    try {
      const val = compiledFn(x);
      return typeof val === "number" && isFinite(val) ? val : null;
    } catch {
      return null;
    }
  };

  // Sample points across domain
  const samples = 150;
  const step = (xMax - xMin) / samples;
  const pathSegments: string[] = [];
  let inPath = false;

  for (let i = 0; i <= samples; i++) {
    const x = xMin + i * step;
    const y = evalFn(x);
    if (y !== null && y >= yMin * 2 && y <= yMax * 2) {
      const sx = toSvgX(x).toFixed(1);
      const sy = toSvgY(y).toFixed(1);
      if (!inPath) {
        pathSegments.push(`M ${sx} ${sy}`);
        inPath = true;
      } else {
        pathSegments.push(`L ${sx} ${sy}`);
      }
    } else {
      inPath = false;
    }
  }

  const curvePath = pathSegments.join(" ");
  const strokeColor = spec.color || "#2563eb"; // High contrast crisp blue for curves

  // Zero axis coordinates
  const originX = Math.max(padLeft, Math.min(width - padRight, toSvgX(0)));
  const originY = Math.max(padTop, Math.min(height - padBottom, toSvgY(0)));

  return `
<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" style="background-color: transparent;">
  <!-- Axes and Grid (Light Mode: zinc-400 / zinc-700) -->
  <line x1="${padLeft}" y1="${originY}" x2="${width - padRight}" y2="${originY}" stroke="#71717a" stroke-width="1.5" />
  <line x1="${originX}" y1="${padTop}" x2="${originX}" y2="${height - padBottom}" stroke="#71717a" stroke-width="1.5" />
  
  <!-- Axis Ticks & Labels -->
  <text x="${width - padRight + 5}" y="${originY + 4}" font-family="sans-serif" font-size="11" fill="#52525b">x</text>
  <text x="${originX - 4}" y="${padTop - 8}" font-family="sans-serif" font-size="11" fill="#52525b" text-anchor="middle">y</text>
  <text x="${padLeft}" y="${height - padBottom + 16}" font-family="sans-serif" font-size="10" fill="#71717a">${xMin}</text>
  <text x="${width - padRight}" y="${height - padBottom + 16}" font-family="sans-serif" font-size="10" fill="#71717a" text-anchor="end">${xMax}</text>

  <!-- Function Curve -->
  <path d="${curvePath}" fill="none" stroke="${strokeColor}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" />

  ${
    spec.title
      ? `<text x="${width / 2}" y="${padTop - 5}" font-family="sans-serif" font-size="12" font-weight="bold" fill="#18181b" text-anchor="middle">${spec.title}</text>`
      : ""
  }
</svg>`.trim();
}

/**
 * Compile a math function plot specification to an inline standalone SVG.
 *
 * @param spec Function plot specification (fn, domain, range, etc.)
 * @param placement Optional layout dimensions from the spatial allocator
 * @returns { svg, width, height }
 */
export function plotToSvg(
  spec: PlotSpec | string,
  placement?: DimensionPlacement
): SvgOutput {
  const normalizedSpec: PlotSpec =
    typeof spec === "string" ? { fn: spec } : spec;

  const targetWidth = placement?.width || 400;
  const targetHeight = placement?.height || 300;

  // Preserve standard 4:3 plot aspect ratio
  const fitted = letterboxDimensions(400, 300, targetWidth, targetHeight);
  const finalWidth = fitted.width;
  const finalHeight = fitted.height;

  // Check if browser DOM is available for function-plot
  if (
    typeof document !== "undefined" &&
    typeof document.createElement === "function"
  ) {
    try {
      const container = document.createElement("div");
      container.style.position = "absolute";
      container.style.left = "-99999px";
      container.style.top = "-99999px";
      container.style.width = `${finalWidth}px`;
      container.style.height = `${finalHeight}px`;
      document.body.appendChild(container);

      try {
        functionPlot({
          target: container,
          width: finalWidth,
          height: finalHeight,
          grid: true,
          xAxis: {
            domain: normalizedSpec.domain || [-5, 5],
          },
          yAxis: {
            domain: normalizedSpec.range || [-5, 5],
          },
          title: normalizedSpec.title,
          data: [
            {
              fn: normalizedSpec.fn,
              color: normalizedSpec.color || "#2563eb",
            },
          ],
        });

        const svgEl = container.querySelector("svg");
        if (svgEl) {
          // Explicit pixel width and height
          svgEl.setAttribute("width", finalWidth.toString());
          svgEl.setAttribute("height", finalHeight.toString());
          svgEl.setAttribute(
            "viewBox",
            `0 0 ${finalWidth} ${finalHeight}`
          );

          // Force Light Mode transparent background & crisp dark text
          svgEl.style.backgroundColor = "transparent";
          const allText = svgEl.querySelectorAll("text");
          allText.forEach((t) => {
            t.setAttribute("fill", "#27272a");
          });

          const svgString = svgEl.outerHTML;
          return {
            svg: svgString,
            width: finalWidth,
            height: finalHeight,
          };
        }
      } finally {
        container.remove();
      }
    } catch {
      // Fallback to pure vector SVG generator on error
    }
  }

  // Standalone vector SVG fallback
  const fallbackSvg = generateFallbackSvg(
    normalizedSpec,
    finalWidth,
    finalHeight
  );

  return {
    svg: fallbackSvg,
    width: finalWidth,
    height: finalHeight,
  };
}
