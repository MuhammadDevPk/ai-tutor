/**
 * Client-side MathJax 3 LaTeX-to-SVG Compiler (Phase 6).
 *
 * Compiles raw LaTeX strings to standalone, self-contained pure vector SVGs using
 * MathJax 3 (tex2svg) with font caching DISABLED (fontCache: "none").
 * Every glyph is an inline SVG path; zero external font URLs or network requests.
 * Explicit pixel dimensions are set while preserving the equation's natural aspect ratio.
 */

// MathJax 3 modular imports
import { mathjax } from "mathjax-full/js/mathjax.js";
import { TeX } from "mathjax-full/js/input/tex.js";
import { SVG } from "mathjax-full/js/output/svg.js";
import { liteAdaptor } from "mathjax-full/js/adaptors/liteAdaptor.js";
import { RegisterHTMLHandler } from "mathjax-full/js/handlers/html.js";
import { AllPackages } from "mathjax-full/js/input/tex/AllPackages.js";

export interface SvgOutput {
  svg: string;
  width: number;
  height: number;
}

export interface DimensionPlacement {
  width?: number;
  height?: number;
}

// Single persistent adaptor & document instance (in-memory DOM, zero external network)
const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);

const mathDocument = mathjax.document("", {
  InputJax: new TeX({
    packages: AllPackages,
    inlineMath: [
      ["$", "$"],
      ["\\(", "\\)"],
    ],
    displayMath: [
      ["$$", "$$"],
      ["\\[", "\\]"],
    ],
  }),
  OutputJax: new SVG({
    // HARD INVARIANT: fontCache must be "none" so every glyph is an inline path
    fontCache: "none",
  }),
});

/**
 * Letterbox dimensions to preserve natural aspect ratio inside target bounding box.
 */
export function letterboxDimensions(
  naturalWidth: number,
  naturalHeight: number,
  targetWidth: number,
  targetHeight: number
): { width: number; height: number } {
  if (naturalWidth <= 0 || naturalHeight <= 0) {
    return { width: targetWidth, height: targetHeight };
  }
  const naturalAspect = naturalWidth / naturalHeight;
  const targetAspect = targetWidth / targetHeight;

  if (naturalAspect > targetAspect) {
    // Width-constrained
    const w = targetWidth;
    const h = Math.max(1, Math.round(targetWidth / naturalAspect));
    return { width: w, height: h };
  } else {
    // Height-constrained
    const h = targetHeight;
    const w = Math.max(1, Math.round(targetHeight * naturalAspect));
    return { width: w, height: h };
  }
}

/**
 * Compile a LaTeX math expression into a self-contained inline SVG string.
 *
 * @param latex Raw LaTeX formula string
 * @param placement Optional target placement rectangle with width and height
 * @returns { svg, width, height }
 */
export function latexToSvg(
  latex: string,
  placement?: DimensionPlacement
): SvgOutput {
  const cleanLatex = (latex || "").trim() || "x";

  // Convert to MathJax SVG node
  const mathNode = mathDocument.convert(cleanLatex, { display: true });
  let rawSvg = adaptor.innerHTML(mathNode) as string;

  // Extract natural viewBox dimensions
  const vbMatch = rawSvg.match(
    /viewBox=["']\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*["']/
  );

  let naturalWidth = 400;
  let naturalHeight = 100;

  if (vbMatch) {
    const vbW = parseFloat(vbMatch[3]);
    const vbH = parseFloat(vbMatch[4]);
    if (!isNaN(vbW) && vbW > 0 && !isNaN(vbH) && vbH > 0) {
      naturalWidth = vbW;
      naturalHeight = vbH;
    }
  }

  // Calculate pixel dimensions
  let finalWidth = Math.round(naturalWidth / 10);
  let finalHeight = Math.round(naturalHeight / 10);

  if (placement?.width && placement?.height) {
    const fitted = letterboxDimensions(
      naturalWidth,
      naturalHeight,
      placement.width,
      placement.height
    );
    finalWidth = fitted.width;
    finalHeight = fitted.height;
  } else if (placement?.width) {
    finalWidth = placement.width;
    finalHeight = Math.max(
      1,
      Math.round((placement.width * naturalHeight) / naturalWidth)
    );
  } else if (placement?.height) {
    finalHeight = placement.height;
    finalWidth = Math.max(
      1,
      Math.round((placement.height * naturalWidth) / naturalHeight)
    );
  }

  // Ensure root <svg> has explicit pixel width and height (not relative 'ex')
  if (/width=["'][^"']*["']/.test(rawSvg)) {
    rawSvg = rawSvg.replace(
      /width=["'][^"']*["']/,
      `width="${finalWidth}"`
    );
  } else {
    rawSvg = rawSvg.replace("<svg ", `<svg width="${finalWidth}" `);
  }

  if (/height=["'][^"']*["']/.test(rawSvg)) {
    rawSvg = rawSvg.replace(
      /height=["'][^"']*["']/,
      `height="${finalHeight}"`
    );
  } else {
    rawSvg = rawSvg.replace("<svg ", `<svg height="${finalHeight}" `);
  }

  // Ensure Light Mode high contrast ink color (#18181b) without duplicate style attributes
  if (/style=["']([^"']*)["']/.test(rawSvg)) {
    rawSvg = rawSvg.replace(
      /style=["']([^"']*)["']/,
      (_, existingStyle) =>
        `style="color: #18181b; fill: currentColor; ${existingStyle}"`
    );
  } else {
    rawSvg = rawSvg.replace(
      "<svg ",
      '<svg style="color: #18181b; fill: currentColor;" '
    );
  }

  return {
    svg: rawSvg,
    width: finalWidth,
    height: finalHeight,
  };
}
