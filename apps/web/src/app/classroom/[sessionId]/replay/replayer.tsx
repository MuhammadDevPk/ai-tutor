"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import type { SessionEvent } from "@/lib/api-client";
import { computeReplayStateAtStep, type ReplayState } from "@/lib/board/replayEngine";
import BoardWorkspace from "@/components/classroom/BoardWorkspace";

export default function SessionReplayer({
  sessionId,
}: {
  sessionId: string;
}) {
  const [events, setEvents] = useState<SessionEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Scrubber index (0 to events.length)
  const [stepIndex, setStepIndex] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const playTimerRef = useRef<NodeJS.Timeout | null>(null);

  // Clipboard toast
  const [copyToast, setCopyToast] = useState<string | null>(null);

  // Optional MediaRecorder WebM Export state
  const [isRecording, setIsRecording] = useState<boolean>(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recordedChunksRef = useRef<Blob[]>([]);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  // Load session events
  useEffect(() => {
    let active = true;
    const fetchEvents = async () => {
      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("auth_token") || ""
            : "";
        const headers: Record<string, string> = token
          ? { Authorization: `Bearer ${token}` }
          : {};

        const res = await fetch(`${apiBase}/sessions/${sessionId}/events`, {
          headers,
        });
        if (!res.ok) {
          throw new Error(`Failed to load replay events (HTTP ${res.status})`);
        }
        const data: SessionEvent[] = await res.json();
        if (!active) return;
        setEvents(data);
        setStepIndex(data.length); // Start at full completion
        setLoading(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load replay");
        setLoading(false);
      }
    };

    fetchEvents();
    return () => {
      active = false;
    };
  }, [sessionId, apiBase]);

  // Compute current replay state from pure event-sourcing engine
  const replayState: ReplayState = computeReplayStateAtStep(events, stepIndex);

  // Play / Pause auto scrubber loop
  useEffect(() => {
    if (isPlaying) {
      playTimerRef.current = setInterval(() => {
        setStepIndex((prev) => {
          if (prev >= events.length) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 1500);
    } else if (playTimerRef.current) {
      clearInterval(playTimerRef.current);
      playTimerRef.current = null;
    }

    return () => {
      if (playTimerRef.current) {
        clearInterval(playTimerRef.current);
      }
    };
  }, [isPlaying, events.length]);

  // Click-to-copy clean raw LaTeX handler
  const handleFormulaClick = useCallback((latex: string, label?: string) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(latex);
      setCopyToast(`Copied formula${label ? ` (${label})` : ""}: ${latex}`);
      setTimeout(() => setCopyToast(null), 3000);
    }
  }, []);

  // Optional client-side MediaRecorder WebM export (zero server cost)
  const toggleWebMRecording = () => {
    if (isRecording) {
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      setIsRecording(false);
      return;
    }

    // Try finding Excalidraw canvas
    const canvas = document.querySelector(".excalidraw__canvas") as HTMLCanvasElement | null;
    if (!canvas || typeof canvas.captureStream !== "function") {
      // Graceful fallback notice per spec
      alert(
        "Canvas stream capture is not supported in this environment. (TODO: WebM screen recording fallback)"
      );
      return;
    }

    try {
      const stream = canvas.captureStream(30);
      const recorder = new MediaRecorder(stream, { mimeType: "video/webm" });
      recordedChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          recordedChunksRef.current.push(e.data);
        }
      };

      recorder.onstop = () => {
        const blob = new Blob(recordedChunksRef.current, { type: "video/webm" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `session-replay-${sessionId}.webm`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (err) {
      console.warn("Client-side WebM recording failed:", err);
      alert("WebM recording unsupported: TODO client-side MediaRecorder fallback");
    }
  };

  return (
    <div className="flex flex-col min-h-screen bg-zinc-50 text-zinc-900 font-sans">
      {/* Top Header */}
      <header className="flex items-center justify-between px-6 py-3.5 bg-white border-b border-zinc-200 shadow-xs z-20">
        <div className="flex items-center gap-3">
          <Link
            href={`/classroom/${sessionId}`}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            ← Classroom
          </Link>
          <span className="text-zinc-300">|</span>
          <span className="text-xs font-semibold uppercase tracking-wider text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
            Interactive Timeline Replay
          </span>
          <span className="text-xs text-zinc-400 font-mono hidden md:inline">
            ID: {sessionId}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href={`/classroom/${sessionId}/export`}
            className="px-3 py-1.5 text-xs font-semibold text-zinc-700 bg-zinc-100 hover:bg-zinc-200 border border-zinc-200 rounded-md transition-colors"
          >
            Study Cheat Sheet
          </Link>

          {/* Optional WebM Export Button */}
          <button
            onClick={toggleWebMRecording}
            className={`px-3 py-1.5 text-xs font-semibold rounded-md transition-colors ${
              isRecording
                ? "bg-red-600 text-white animate-pulse"
                : "bg-purple-50 text-purple-700 border border-purple-200 hover:bg-purple-100"
            }`}
          >
            {isRecording ? "Stop Recording (.webm)" : "Export Replay Video (.webm)"}
          </button>
        </div>
      </header>

      {/* Copy LaTeX Toast */}
      {copyToast && (
        <div className="fixed top-16 right-6 px-4 py-2 bg-emerald-900 text-white text-xs font-mono rounded-lg shadow-lg z-50 animate-bounce">
          ✓ {copyToast}
        </div>
      )}

      {/* Replay Controls & Scrubber Bar */}
      <div className="bg-white border-b border-zinc-200 px-6 py-3 shadow-xs flex flex-col gap-2 z-10">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setIsPlaying(!isPlaying)}
              className="px-3 py-1 text-xs font-bold text-white bg-indigo-600 hover:bg-indigo-700 rounded transition-colors"
            >
              {isPlaying ? "❚❚ Pause" : "▶ Play"}
            </button>
            <button
              onClick={() => setStepIndex((prev) => Math.max(0, prev - 1))}
              disabled={stepIndex === 0}
              className="px-2 py-1 text-xs font-semibold text-zinc-700 bg-zinc-100 hover:bg-zinc-200 rounded disabled:opacity-50"
            >
              ◀ Step Back
            </button>
            <button
              onClick={() => setStepIndex((prev) => Math.min(events.length, prev + 1))}
              disabled={stepIndex >= events.length}
              className="px-2 py-1 text-xs font-semibold text-zinc-700 bg-zinc-100 hover:bg-zinc-200 rounded disabled:opacity-50"
            >
              Step Forward ▶
            </button>
            <span className="text-xs text-zinc-500 font-mono">
              Step {stepIndex} / {events.length}
            </span>
          </div>

          {/* FSM & Subtopic Badges */}
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium text-zinc-500">State:</span>
            <span className="text-xs font-bold text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded border border-indigo-100">
              {replayState.currentFsmState}
            </span>
            {replayState.isInterruptLoop && (
              <span className="text-xs font-bold text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 animate-pulse">
                Q&A Interrupt Loop
              </span>
            )}
            {replayState.currentSubtopic && (
              <span className="text-xs text-zinc-600 bg-zinc-100 px-2 py-0.5 rounded font-mono hidden sm:inline">
                {replayState.currentSubtopic}
              </span>
            )}
          </div>
        </div>

        {/* Timeline Range Slider */}
        <div className="flex items-center gap-3">
          <input
            type="range"
            min={0}
            max={events.length}
            value={stepIndex}
            onChange={(e) => setStepIndex(Number(e.target.value))}
            className="w-full accent-indigo-600 cursor-pointer"
          />
        </div>
      </div>

      {/* Main Grid: Whiteboard + Context Sidebar */}
      <main className="flex flex-1 flex-col lg:flex-row gap-4 p-4 min-h-0 overflow-hidden">
        {loading ? (
          <div className="flex-1 flex items-center justify-center text-sm text-zinc-500">
            Loading timeline events...
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center text-sm text-red-600">
            {error}
          </div>
        ) : (
          <>
            {/* Excalidraw Whiteboard Replayer */}
            <div className="flex-1 flex flex-col min-h-[500px] min-w-0">
              <BoardWorkspace
                operations={replayState.activeSlideOps}
                slidesDeck={replayState.archivedSlides.map((s) => ({
                  slide_number: s.slideNumber,
                  ops: s.ops,
                }))}
                activeSlideIndex={replayState.activeSlideIndex}
                resetOnOperationsChange={true}
                readOnly={true}
                onFormulaClick={handleFormulaClick}
                className="h-full"
              />
            </div>

            {/* Replay Context & Formula Inspector */}
            <div className="w-full lg:w-80 flex flex-col gap-3 overflow-y-auto">
              {/* Misconception Notice */}
              {replayState.activeMisconception && (
                <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-xl shadow-xs text-xs space-y-1">
                  <span className="font-bold text-emerald-800 block">
                    ✓ Misconception Cleared
                  </span>
                  <p className="text-emerald-950 font-medium">
                    &ldquo;{replayState.activeMisconception.question}&rdquo;
                  </p>
                  <p className="text-emerald-700 text-[11px]">
                    {replayState.activeMisconception.clarification}
                  </p>
                </div>
              )}

              {/* Speech Transcript at Scrub Point */}
              <div className="bg-white p-4 rounded-xl border border-zinc-200 shadow-xs space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                  Dialogue Transcript
                </h3>
                {replayState.studentSpeechText && (
                  <div className="text-xs text-zinc-700 bg-zinc-50 p-2.5 rounded-lg border border-zinc-100">
                    <span className="font-semibold text-zinc-500 block text-[10px] uppercase">
                      Student
                    </span>
                    {replayState.studentSpeechText}
                  </div>
                )}
                {replayState.teacherSayText ? (
                  <div className="text-xs text-indigo-950 bg-indigo-50/50 p-2.5 rounded-lg border border-indigo-100">
                    <span className="font-semibold text-indigo-600 block text-[10px] uppercase">
                      Teacher
                    </span>
                    {replayState.teacherSayText}
                  </div>
                ) : (
                  <div className="text-xs text-zinc-400 italic">
                    No speech line at this scrub point.
                  </div>
                )}
              </div>

              {/* Click-to-Copy Formula Deck */}
              <div className="bg-white p-4 rounded-xl border border-zinc-200 shadow-xs space-y-2 flex-1">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
                    Board Formulas
                  </h3>
                  <span className="text-[10px] text-zinc-400">Click to copy</span>
                </div>

                {replayState.allFormulas.length === 0 ? (
                  <p className="text-xs text-zinc-400 italic">
                    No formulas generated up to this point.
                  </p>
                ) : (
                  <div className="space-y-2 max-h-[400px] overflow-y-auto pr-1">
                    {replayState.allFormulas.map((f, idx) => (
                      <button
                        key={`${f.opId}_${idx}`}
                        onClick={() => handleFormulaClick(f.latex, f.label)}
                        className="w-full text-left p-2.5 bg-zinc-50 hover:bg-indigo-50 border border-zinc-200 hover:border-indigo-200 rounded-lg transition-colors group cursor-pointer"
                      >
                        <span className="text-[10px] font-semibold text-zinc-500 group-hover:text-indigo-600 block">
                          {f.label}
                        </span>
                        <code className="text-xs font-mono text-zinc-800 group-hover:text-indigo-900 block truncate">
                          {f.latex}
                        </code>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
