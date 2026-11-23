/**
 * Circle-to-Ask Geometry Matcher (Phase 6 Core Module).
 *
 * Listens for student freehand strokes or arrows on the whiteboard,
 * computes the stroke's bounding box, and finds injected elements whose
 * bounding boxes overlap it (largest overlap wins; ties break by smallest element).
 * Emits the Phase 1 BOARD_SELECTION event over the classroom DataChannel.
 *
 * PURE GEOMETRY ONLY: Zero screenshot, vision, or OCR API calls anywhere.
 */

import type { BoardSelectionEvent } from "@/lib/api-client";

export interface BoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface BoardCustomData {
  op_id?: string;
  label?: string;
  raw?: string;
  [key: string]: unknown;
}

export interface BoardElementLike {
  id: string;
  type?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  isDeleted?: boolean;
  points?: readonly (readonly [number, number])[] | readonly { x: number; y: number }[];
  customData?: BoardCustomData;
}

export interface MatchResult {
  element: BoardElementLike;
  overlapArea: number;
  referencedOpId: string;
  label: string;
  rawPayload: string;
}

/**
 * Compute the bounding box of a stroke or element.
 * Accounts for Excalidraw freehand / linear stroke points relative to (x, y).
 */
export function computeStrokeBBox(element: BoardElementLike): BoundingBox {
  if (element.points && element.points.length > 0) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;

    for (const pt of element.points) {
      const px = Array.isArray(pt) ? pt[0] : (pt as { x: number }).x;
      const py = Array.isArray(pt) ? pt[1] : (pt as { y: number }).y;
      const absX = element.x + px;
      const absY = element.y + py;

      if (absX < minX) minX = absX;
      if (absX > maxX) maxX = absX;
      if (absY < minY) minY = absY;
      if (absY > maxY) maxY = absY;
    }

    if (minX <= maxX && minY <= maxY) {
      return {
        x: minX,
        y: minY,
        width: Math.max(1, maxX - minX),
        height: Math.max(1, maxY - minY),
      };
    }
  }

  return {
    x: element.x,
    y: element.y,
    width: Math.max(1, element.width),
    height: Math.max(1, element.height),
  };
}

/**
 * Compute the geometric intersection area between two axis-aligned bounding boxes.
 */
export function computeBBoxOverlap(boxA: BoundingBox, boxB: BoundingBox): number {
  const x1 = Math.max(boxA.x, boxB.x);
  const y1 = Math.max(boxA.y, boxB.y);
  const x2 = Math.min(boxA.x + boxA.width, boxB.x + boxB.width);
  const y2 = Math.min(boxA.y + boxA.height, boxB.y + boxB.height);

  if (x2 <= x1 || y2 <= y1) {
    return 0;
  }

  return (x2 - x1) * (y2 - y1);
}

/**
 * Find the best matching injected board element that overlaps the user's stroke.
 *
 * Rules:
 * - Must have positive overlap area (> 0).
 * - Largest overlap area wins.
 * - Ties broken by smallest candidate element area.
 */
export function findBestMatchingElement(
  strokeBBox: BoundingBox,
  candidateElements: readonly BoardElementLike[]
): MatchResult | null {
  let bestMatch: BoardElementLike | null = null;
  let maxOverlap = 0;
  let minElementArea = Infinity;

  for (const candidate of candidateElements) {
    // Only match injected content items that have an op_id in customData
    if (candidate.isDeleted || !candidate.customData?.op_id) {
      continue;
    }

    const candBox: BoundingBox = {
      x: candidate.x,
      y: candidate.y,
      width: candidate.width,
      height: candidate.height,
    };

    const overlap = computeBBoxOverlap(strokeBBox, candBox);

    if (overlap > 0) {
      const candidateArea = candidate.width * candidate.height;
      const isGreater = overlap > maxOverlap + 1e-4;
      const isTie = Math.abs(overlap - maxOverlap) <= 1e-4;

      if (isGreater || (isTie && candidateArea < minElementArea)) {
        maxOverlap = overlap;
        minElementArea = candidateArea;
        bestMatch = candidate;
      }
    }
  }

  if (!bestMatch) {
    return null;
  }

  const opId = bestMatch.customData?.op_id || bestMatch.id;
  const label =
    bestMatch.customData?.label || `Board Element (${bestMatch.type || "latex"})`;
  const rawPayload = bestMatch.customData?.raw || "";

  return {
    element: bestMatch,
    overlapArea: maxOverlap,
    referencedOpId: opId,
    label,
    rawPayload,
  };
}

/**
 * Format a MatchResult into the canonical Phase 1 BOARD_SELECTION event.
 */
export function createBoardSelectionEvent(
  match: MatchResult
): BoardSelectionEvent {
  return {
    event_type: "BOARD_SELECTION",
    referenced_op_id: match.referencedOpId,
    label: match.label,
    payload: match.rawPayload,
  };
}

/**
 * Check if a newly added or modified element is a student gesture stroke
 * (freehand line or arrow), and find the referenced board element if so.
 */
export function evaluateStudentGesture(
  allElements: readonly BoardElementLike[],
  lastGestureElement: BoardElementLike
): MatchResult | null {
  // Freehand, arrow, or line gestures by student
  const isGesture =
    lastGestureElement.type === "freedraw" ||
    lastGestureElement.type === "arrow" ||
    lastGestureElement.type === "line";

  if (!isGesture) {
    return null;
  }

  const strokeBBox = computeStrokeBBox(lastGestureElement);
  return findBestMatchingElement(strokeBBox, allElements);
}
