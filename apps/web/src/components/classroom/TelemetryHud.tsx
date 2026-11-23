"use client";

import React, { useEffect, useState, useCallback, useRef } from "react";

/**
 * TelemetryHud — Dev-only toggleable overlay.
 *
 * Shows:
 * - active turn_id
 * - playout elapsed_ms
 * - VAD state
 * - active LLM bucket
 * - remaining Groq TPM (server-reported, or "n/a")
 * - per-stage latency timings
 *
 * Hidden by default. Shown when:
 * - URL has ?hud=1
 * - User presses Ctrl+Shift+H toggle shortcut
 */

export interface TelemetryData {
  turnId: number;
  elapsedMs: number;
  vadState: string;
  activeLlmBucket: string;
  groqTpmRemaining: number | null;
  latencies: {
    scheduleArrivalToRelease?: number;
    onsetDetectionDelay?: number;
  };
}

interface TelemetryHudProps {
  data: TelemetryData;
  className?: string;
}

export default function TelemetryHud({
  data,
  className = "",
}: TelemetryHudProps) {
  const [visible, setVisible] = useState(false);
  const toggleRef = useRef(false);

  // Check URL param on mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("hud") === "1") {
      queueMicrotask(() => {
        toggleRef.current = true;
        setVisible(true);
      });
    }
  }, []);

  // Keyboard shortcut: Ctrl+Shift+H
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.ctrlKey && e.shiftKey && e.key === "H") {
      e.preventDefault();
      toggleRef.current = !toggleRef.current;
      setVisible(toggleRef.current);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  if (!visible) return null;

  return (
    <div
      className={`fixed bottom-3 left-3 z-[9999] bg-zinc-900 text-zinc-100 px-4 py-3 rounded-lg shadow-lg text-xs font-mono space-y-1.5 max-w-sm border border-zinc-700 ${className}`}
    >
      <div className="flex items-center gap-2 pb-1 border-b border-zinc-700 mb-1">
        <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
        <span className="font-semibold text-[11px] uppercase tracking-wider text-zinc-400">
          Dev Telemetry HUD
        </span>
        <button
          onClick={() => {
            toggleRef.current = false;
            setVisible(false);
          }}
          className="ml-auto text-zinc-500 hover:text-zinc-200 text-sm font-bold"
        >
          ×
        </button>
      </div>

      <Row label="Turn ID" value={String(data.turnId)} />
      <Row label="Elapsed" value={`${data.elapsedMs.toFixed(0)} ms`} />
      <Row label="VAD" value={data.vadState} />
      <Row label="LLM Bucket" value={data.activeLlmBucket || "n/a"} />
      <Row
        label="Groq TPM"
        value={
          data.groqTpmRemaining !== null
            ? String(data.groqTpmRemaining)
            : "n/a"
        }
      />
      {data.latencies.scheduleArrivalToRelease !== undefined && (
        <Row
          label="Sched→Release"
          value={`${data.latencies.scheduleArrivalToRelease.toFixed(0)} ms`}
        />
      )}
      {data.latencies.onsetDetectionDelay !== undefined && (
        <Row
          label="Onset Delay"
          value={`${data.latencies.onsetDetectionDelay.toFixed(0)} ms`}
        />
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <span className="text-zinc-500">{label}:</span>
      <span className="font-medium text-zinc-200 truncate">{value}</span>
    </div>
  );
}
