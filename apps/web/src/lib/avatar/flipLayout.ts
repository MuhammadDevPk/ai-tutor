/**
 * flipLayout.ts — Pure FLIP layout math & resolution for Full-to-PiP avatar transitions.
 *
 * System Invariant 5: One permanently mounted 30fps WebGL canvas. Full <-> 200x200px PiP
 * animates ONLY `transform` (`translate3d`, `scale`) and `clip-path` over ~280ms.
 * Call Three.js `setSize()` and camera reframe ONCE on `transitionend`.
 */

export type LayoutMode = "FULL_AVATAR" | "PIP_WHITEBOARD" | "AUTO";
export type EffectiveLayout = "FULL_AVATAR" | "PIP_WHITEBOARD";

export interface ViewportDimensions {
  width: number;
  height: number;
}

export interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

export interface PipLayoutConfig {
  size: number; // default: 200px
  margin: number; // default: 16px
  borderRadius: number; // default: 16px
  durationMs: number; // default: 280ms
  easing: string; // default: "cubic-bezier(0.4, 0, 0.2, 1)"
}

export const DEFAULT_PIP_CONFIG: PipLayoutConfig = {
  size: 200,
  margin: 16,
  borderRadius: 16,
  durationMs: 280,
  easing: "cubic-bezier(0.4, 0, 0.2, 1)",
};

/**
 * Calculates the bounding rectangle for a layout mode in a given viewport.
 */
export function calculateLayoutRect(
  layout: EffectiveLayout,
  viewport: ViewportDimensions,
  config: PipLayoutConfig = DEFAULT_PIP_CONFIG
): Rect {
  if (layout === "FULL_AVATAR") {
    return {
      top: 0,
      left: 0,
      width: Math.max(0, viewport.width),
      height: Math.max(0, viewport.height),
    };
  }

  // PIP_WHITEBOARD: 200x200px at top-right
  const size = config.size;
  const left = Math.max(0, viewport.width - size - config.margin);
  const top = config.margin;

  return {
    top,
    left,
    width: size,
    height: size,
  };
}

/**
 * Computes the FLIP Invert transform (translate3d, scale) between the First rect and Last rect.
 * When applied to the element at the Last rect position, it visually places it back at First.
 */
export function computeFlipInvert(
  first: Rect,
  last: Rect
): {
  deltaX: number;
  deltaY: number;
  scaleX: number;
  scaleY: number;
  transform: string;
} {
  const deltaX = first.left - last.left;
  const deltaY = first.top - last.top;
  const rawScaleX = last.width > 0 ? first.width / last.width : 1;
  const rawScaleY = last.height > 0 ? first.height / last.height : 1;
  const scaleX = Number.isFinite(rawScaleX) && rawScaleX > 0 ? rawScaleX : 1;
  const scaleY = Number.isFinite(rawScaleY) && rawScaleY > 0 ? rawScaleY : 1;

  return {
    deltaX,
    deltaY,
    scaleX,
    scaleY,
    transform: `translate3d(${deltaX}px, ${deltaY}px, 0px) scale(${scaleX}, ${scaleY})`,
  };
}

/**
 * Returns the final (identity) FLIP transform for the Play step.
 */
export function getPlayTransform(): string {
  return "translate3d(0px, 0px, 0px) scale(1, 1)";
}

/**
 * Computes the CSS clip-path for an effective layout mode.
 * During FLIP, clip-path smoothly transitions between full rectangle and rounded box.
 */
export function getClipPathForLayout(
  layout: EffectiveLayout,
  config: PipLayoutConfig = DEFAULT_PIP_CONFIG
): string {
  if (layout === "FULL_AVATAR") {
    return "inset(0% 0% 0% 0% round 0px)";
  }
  return `inset(0% 0% 0% 0% round ${config.borderRadius}px)`;
}

/**
 * Resolves the effective layout ("FULL_AVATAR" | "PIP_WHITEBOARD") based on:
 * - user override mode ("FULL_AVATAR" | "PIP_WHITEBOARD" | "AUTO")
 * - speaking state (teacher is currently speaking or idle)
 * - whiteboard activity (board has operations present)
 *
 * Automatic rule:
 * - If user explicitly set FULL_AVATAR or PIP_WHITEBOARD, honor it unconditionally.
 * - In AUTO mode:
 *   - If the whiteboard has content/derivations (hasBoardOps is true), use PIP_WHITEBOARD
 *     so the student can focus on formulas, derivations, and slides.
 *   - If the whiteboard is empty (initial greeting, conversational onboarding, direct dialogue),
 *     use FULL_AVATAR.
 */
export function resolveEffectiveLayout(
  mode: LayoutMode,
  isSpeaking: boolean,
  hasBoardOps: boolean
): EffectiveLayout {
  if (mode === "FULL_AVATAR") return "FULL_AVATAR";
  if (mode === "PIP_WHITEBOARD") return "PIP_WHITEBOARD";

  // AUTO mode:
  // If the board has active derivations/steps, keep avatar in PiP to keep the board primary.
  if (hasBoardOps) {
    return "PIP_WHITEBOARD";
  }

  // Without board operations, avatar is full-stage (face-to-face dialogue).
  return "FULL_AVATAR";
}
