/**
 * Client-side Spatial Layout Allocator Port (Phase 6).
 *
 * Mirrors the backend's deterministic 1280x720 4-zone spatial allocator.
 * Used when an incoming BoardOp does not have an attached placement.
 */

export interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ClientPlacement extends Rect {
  zone: "header" | "derivation" | "visual" | "callout";
  op_id?: string;
}

export const CANVAS_WIDTH = 1280;
export const CANVAS_HEIGHT = 720;

export const ZONE_HEADER: Rect = { x: 40, y: 20, width: 1200, height: 60 };
export const ZONE_DERIVATION: Rect = { x: 40, y: 100, width: 740, height: 480 };
export const ZONE_VISUAL: Rect = { x: 800, y: 100, width: 440, height: 480 };
export const ZONE_CALLOUT: Rect = { x: 40, y: 600, width: 1200, height: 100 };

export const ZONES = {
  header: ZONE_HEADER,
  derivation: ZONE_DERIVATION,
  visual: ZONE_VISUAL,
  callout: ZONE_CALLOUT,
} as const;

export type ZoneName = keyof typeof ZONES;

/**
 * Estimate bounding box dimensions for an op on the client side.
 */
export function estimateClientBBox(
  opType: string,
  payload: Record<string, unknown> | string
): { width: number; height: number } {
  const typeLower = (opType || "latex").toLowerCase();

  if (typeLower === "latex") {
    const raw = typeof payload === "string" ? payload : (payload?.latex as string) || (payload?.raw as string) || "";
    let height = 50;
    if (/\\(?:c|d)?frac/.test(raw)) height += 35;
    if (/\\(?:int|sum|prod|lim)/.test(raw)) height += 32;
    if (/\\begin\{(?:pmatrix|bmatrix|matrix)/.test(raw)) {
      const rows = raw.split(/\\\\/).length;
      height += Math.max(0, rows - 1) * 32;
    }
    const clean = raw.replace(/\\[a-zA-Z]+/g, " ");
    const width = Math.min(700, Math.max(160, 40 + clean.length * 13));
    return { width, height };
  } else if (typeLower === "plot") {
    const spec =
      typeof payload === "object" && payload !== null && "spec" in payload
        ? (payload as { spec: Record<string, unknown> }).spec
        : payload;
    const w = typeof spec === "object" && spec !== null ? Number(spec.width) || 400 : 400;
    const h = typeof spec === "object" && spec !== null ? Number(spec.height) || 300 : 300;
    return { width: w, height: h };
  } else if (typeLower === "diagram") {
    const spec =
      typeof payload === "object" && payload !== null && "spec" in payload
        ? (payload as { spec: Record<string, unknown> }).spec
        : payload;
    const w = typeof spec === "object" && spec !== null ? Number(spec.width) || 400 : 400;
    const h = typeof spec === "object" && spec !== null ? Number(spec.height) || 240 : 240;
    return { width: w, height: h };
  } else if (typeLower === "header" || typeLower === "title") {
    return { width: 1120, height: 44 };
  } else if (typeLower === "callout" || typeLower === "text") {
    return { width: 1000, height: 60 };
  }

  return { width: 300, height: 60 };
}

/**
 * Allocate placement for an op within active slide placements.
 */
export function allocateClientPlacement(
  opType: string,
  payload: Record<string, unknown> | string,
  activePlacements: readonly ClientPlacement[],
  opId?: string
): ClientPlacement | "CLEAR_SLIDE" {
  const typeLower = (opType || "latex").toLowerCase();
  let zoneName: ZoneName = "derivation";

  if (typeLower === "clear") {
    return "CLEAR_SLIDE";
  } else if (typeLower === "header" || typeLower === "title") {
    zoneName = "header";
  } else if (typeLower === "plot" || typeLower === "diagram") {
    zoneName = "visual";
  } else if (typeLower === "callout" || typeLower === "text") {
    zoneName = "callout";
  }

  const zone = ZONES[zoneName];
  const bbox = estimateClientBBox(typeLower, payload);

  const zonePlacements = activePlacements.filter((p) => p.zone === zoneName);
  const margin = 16;

  const candidateY =
    zonePlacements.length === 0
      ? zone.y
      : Math.max(...zonePlacements.map((p) => p.y + p.height)) + margin;

  if (candidateY + bbox.height > zone.y + zone.height) {
    return "CLEAR_SLIDE";
  }

  return {
    x: zone.x,
    y: candidateY,
    width: bbox.width,
    height: bbox.height,
    zone: zoneName,
    op_id: opId,
  };
}
