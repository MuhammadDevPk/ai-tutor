/**
 * playoutClock.ts — Pure-logic client playout clock core.
 *
 * Decision logic: arming, elapsed time with pause-freeze and rewind
 * shifts, release scheduling, epoch/dedup decisions.
 *
 * All external dependencies are injected:
 * - `clock()`: returns current time in ms (e.g. performance.now).
 * - `onRelease(op)`: callback when a BoardOp's offset is reached.
 *
 * Exported and test-ready. The Python side carries the executed tests
 * for the shared math (offset computation, epoch rules).
 */

import type { BoardOp } from "@/lib/api-client";

// RMS silence threshold for onset detection (linear amplitude, not dB).
// Calibrated for 24 kHz int16 PCM via WebRTC remote track analyser.
export const RMS_ONSET_THRESHOLD = 0.01;

export interface PlayoutClockConfig {
  clock: () => number;
  onRelease: (op: BoardOp) => void;
}

export interface QueuedOp {
  op: BoardOp;
  released: boolean;
}

export class PlayoutClock {
  private _armed = false;
  private _paused = false;
  private _anchorTime: number | null = null;
  private _segmentStartTime: number | null = null;
  private _elapsedAtPause = 0;
  private _rewindShiftMs = 0;
  private _activeTurnId = 0;
  private _queue: QueuedOp[] = [];
  private _renderedOpIds: Set<string> = new Set();
  private _clock: () => number;
  private _onRelease: (op: BoardOp) => void;

  constructor(config: PlayoutClockConfig) {
    this._clock = config.clock;
    this._onRelease = config.onRelease;
  }

  // ---- Epoch / Turn Management ----

  get activeTurnId(): number {
    return this._activeTurnId;
  }

  get armed(): boolean {
    return this._armed;
  }

  get paused(): boolean {
    return this._paused;
  }

  /**
   * Elapsed ms since the onset anchor, accounting for pause-freeze
   * and rewind shifts.
   */
  get elapsedMs(): number {
    if (this._anchorTime === null) return 0;
    if (this._paused) return this._elapsedAtPause;
    const raw = this._clock() - this._anchorTime - this._rewindShiftMs;
    return Math.max(0, raw);
  }

  // ---- Arm-Gated RMS Onset ----

  /**
   * Called on AUDIO_SEGMENT_START. Only "response" arms the clock;
   * "filler" segments are ignored.
   */
  onSegmentStart(turnId: number, segmentId: "filler" | "response"): void {
    if (segmentId === "filler") return;
    // "response" — arm the clock for this turn
    this._activeTurnId = turnId;
    this._armed = true;
    this._paused = false;
    this._anchorTime = null;
    this._segmentStartTime = this._clock();
    this._elapsedAtPause = 0;
    this._rewindShiftMs = 0;
  }

  /**
   * Called periodically from the analyser/worklet with the current RMS.
   * Anchors t=0 on the first non-silent frame when armed.
   */
  onRmsSample(rms: number): void {
    if (!this._armed || this._anchorTime !== null) return;
    if (rms >= RMS_ONSET_THRESHOLD) {
      this._anchorTime = this._clock();
    }
  }

  // ---- Pause / Resume / Rewind ----

  onPlayoutPause(): void {
    if (!this._armed) return;
    this._paused = true;
    this._elapsedAtPause = this.elapsedMs;
  }

  onPlayoutResume(rewindMs: number): void {
    if (!this._armed) return;
    this._paused = false;
    // Shift backward by exactly rewindMs
    this._rewindShiftMs += rewindMs;
    // Re-anchor so elapsed continues from the paused point minus rewind
    if (this._anchorTime !== null) {
      this._anchorTime =
        this._clock() - this._elapsedAtPause + rewindMs;
      // Recompute rewind shift relative to new anchor
      this._rewindShiftMs = 0;
    }
  }

  // ---- Board Op Scheduling ----

  /**
   * Enqueue a BoardOp received from BOARD_SCHEDULE.
   * Applies epoch/dedup guard:
   * - Ignores ops with turn_id below active.
   * - Never injects the same op_id twice.
   * - On a future turn (turnId > activeTurnId), resets clock state for the new turn
   *   without treating operations as late arrivals against the previous turn's clock.
   */
  enqueue(turnId: number, op: BoardOp): void {
    // Epoch guard: ignore stale turns
    if (turnId < this._activeTurnId) return;

    // New turn advance ahead of audio
    if (turnId > this._activeTurnId) {
      this._activeTurnId = turnId;
      this._armed = false;
      this._paused = false;
      this._anchorTime = null;
      this._segmentStartTime = null;
      this._elapsedAtPause = 0;
      this._rewindShiftMs = 0;
      this._queue = [];
      this._renderedOpIds.clear();
    }

    // Dedup guard: ignore already-seen op_ids
    if (this._renderedOpIds.has(op.op_id)) return;
    // Check if already in queue
    if (this._queue.some((q) => q.op.op_id === op.op_id)) return;

    // Only check late arrival if this turn is armed, playing, and anchored
    if (
      this._armed &&
      this._anchorTime !== null &&
      op.playout_offset_ms <= this.elapsedMs
    ) {
      // Late arrival: inject immediately
      this._renderedOpIds.add(op.op_id);
      this._onRelease(op);
      return;
    }

    this._queue.push({ op, released: false });
  }

  /**
   * Called on each requestAnimationFrame tick. Releases ops whose
   * playout_offset_ms has been reached.
   */
  tick(): void {
    if (!this._armed || this._paused) return;

    // Fallback anchor: If 500ms has elapsed since AUDIO_SEGMENT_START("response")
    // without crossing RMS threshold (silent lead-in or non-speech turn), anchor now.
    if (this._anchorTime === null) {
      if (
        this._segmentStartTime !== null &&
        this._clock() - this._segmentStartTime >= 500
      ) {
        this._anchorTime = this._clock();
      } else {
        return;
      }
    }

    const elapsed = this.elapsedMs;

    for (const entry of this._queue) {
      if (entry.released) continue;
      if (elapsed >= entry.op.playout_offset_ms) {
        entry.released = true;
        this._renderedOpIds.add(entry.op.op_id);
        this._onRelease(entry.op);
      }
    }
  }

  /**
   * Last rendered op_id, for INTERRUPT_FLUSH reporting.
   */
  get lastRenderedOpId(): string | null {
    // Return the last one that was rendered, by queue order
    let last: string | null = null;
    for (const entry of this._queue) {
      if (entry.released) {
        last = entry.op.op_id;
      }
    }
    // Also check renderedOpIds for immediately-injected ops
    if (last === null && this._renderedOpIds.size > 0) {
      last = Array.from(this._renderedOpIds).pop() ?? null;
    }
    return last;
  }

  // ---- Interrupt Flush ----

  /**
   * On INTERRUPT_FLUSH: discard every queued unrendered op for the old
   * turn and return the last rendered op_id for server reconciliation.
   */
  onInterruptFlush(newTurnId: number): string | null {
    const lastRendered = this.lastRenderedOpId;
    // Discard all unrendered ops
    this._queue = [];
    this._renderedOpIds.clear();
    this._armed = false;
    this._paused = false;
    this._anchorTime = null;
    this._segmentStartTime = null;
    this._elapsedAtPause = 0;
    this._rewindShiftMs = 0;
    this._activeTurnId = newTurnId;
    return lastRendered;
  }

  /**
   * Reset entire clock state (e.g. on session end).
   */
  reset(): void {
    this._armed = false;
    this._paused = false;
    this._anchorTime = null;
    this._segmentStartTime = null;
    this._elapsedAtPause = 0;
    this._rewindShiftMs = 0;
    this._activeTurnId = 0;
    this._queue = [];
    this._renderedOpIds.clear();
  }
}
