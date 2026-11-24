"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import type { CheatSheetResponse } from "@/lib/api-client";
import { latexToSvg } from "@/lib/board";

export default function StudyCheatSheet({
  sessionId,
}: {
  sessionId: string;
}) {
  const [cheatSheet, setCheatSheet] = useState<CheatSheetResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [copiedIndex, setCopiedIndex] = useState<number | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    let active = true;
    const fetchCheatSheet = async () => {
      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("auth_token") || ""
            : "";
        const headers: Record<string, string> = token
          ? { Authorization: `Bearer ${token}` }
          : {};

        const res = await fetch(`${apiBase}/sessions/${sessionId}/cheat-sheet`, {
          headers,
        });
        if (!res.ok) {
          throw new Error(`Failed to load cheat sheet (HTTP ${res.status})`);
        }
        const data: CheatSheetResponse = await res.json();
        if (!active) return;
        setCheatSheet(data);
        setLoading(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load cheat sheet");
        setLoading(false);
      }
    };

    fetchCheatSheet();
    return () => {
      active = false;
    };
  }, [sessionId, apiBase]);

  const copyFormula = useCallback((latex: string, index: number) => {
    if (typeof navigator !== "undefined" && navigator.clipboard) {
      navigator.clipboard.writeText(latex);
      setCopiedIndex(index);
      setTimeout(() => setCopiedIndex(null), 2500);
    }
  }, []);

  const handlePrint = () => {
    if (typeof window !== "undefined") {
      window.print();
    }
  };

  const downloadMarkdown = () => {
    if (!cheatSheet) return;
    const blob = new Blob([cheatSheet.markdown], { type: "text/markdown;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `cheat-sheet-${sessionId}.md`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  return (
    <div className="min-h-screen bg-zinc-50 print:bg-white text-zinc-900 font-sans p-4 sm:p-8">
      {/* Navigation & Action Bar (Hidden when printing to PDF) */}
      <div className="max-w-4xl mx-auto mb-6 flex items-center justify-between print:hidden">
        <div className="flex items-center gap-3">
          <Link
            href={`/classroom/${sessionId}`}
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            ← Classroom
          </Link>
          <span className="text-zinc-300">|</span>
          <Link
            href={`/classroom/${sessionId}/replay`}
            className="text-xs font-semibold text-purple-600 hover:text-purple-800 transition-colors"
          >
            Timeline Replay
          </Link>
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={downloadMarkdown}
            className="px-3 py-1.5 text-xs font-semibold text-zinc-700 bg-white hover:bg-zinc-100 border border-zinc-300 rounded-md shadow-xs transition-colors"
          >
            Download Markdown (.md)
          </button>
          <button
            onClick={handlePrint}
            className="px-3.5 py-1.5 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-md shadow-xs transition-colors flex items-center gap-1.5"
          >
            <span>🖨</span> Print / Save to PDF
          </button>
        </div>
      </div>

      {/* Main Printable Document Card */}
      <div className="max-w-4xl mx-auto bg-white border border-zinc-200 print:border-none rounded-xl p-8 sm:p-12 shadow-xs print:shadow-none space-y-8">
        {loading ? (
          <div className="p-12 text-center text-sm text-zinc-500">
            Compiling exam study cheat sheet...
          </div>
        ) : error ? (
          <div className="p-8 text-center text-sm text-red-600 bg-red-50 rounded-lg">
            {error}
          </div>
        ) : cheatSheet ? (
          <>
            {/* Header */}
            <div className="border-b border-zinc-200 pb-6 space-y-2">
              <span className="text-xs font-bold uppercase tracking-wider text-indigo-600">
                Exam Study Asset • AI Video Tutor
              </span>
              <h1 className="text-2xl sm:text-3xl font-extrabold text-zinc-900 tracking-tight">
                {cheatSheet.chapter_title}
              </h1>
              <div className="flex flex-wrap items-center gap-4 text-xs text-zinc-500 font-mono pt-1">
                <span>Chapter: {cheatSheet.chapter_path}</span>
                <span>•</span>
                <span>Session: {sessionId}</span>
                <span>•</span>
                <span>{(cheatSheet.formulas ?? []).length} Formulas</span>
                <span>•</span>
                <span>{(cheatSheet.misconceptions ?? []).length} Misconceptions Cleared</span>
              </div>
            </div>

            {/* Key Mathematical Formulas */}
            <section className="space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-100 pb-2">
                <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
                  <span>📐</span> Key Mathematical Formulas
                </h2>
                <span className="text-xs text-zinc-400 print:hidden">
                  Click any equation to copy raw LaTeX
                </span>
              </div>

              {(cheatSheet.formulas ?? []).length === 0 ? (
                <p className="text-xs text-zinc-500 italic p-4 bg-zinc-50 rounded-lg">
                  No formulas recorded during this tutoring session.
                </p>
              ) : (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {(cheatSheet.formulas ?? []).map((f, idx) => (
                    <div
                      key={`formula_${idx}`}
                      onClick={() => copyFormula(f.latex, idx)}
                      className="p-4 bg-zinc-50 hover:bg-indigo-50/50 print:bg-zinc-50/30 border border-zinc-200 rounded-lg transition-colors group cursor-pointer relative"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-xs font-semibold text-zinc-600 group-hover:text-indigo-600">
                          {idx + 1}. {f.label || "Formula"}
                        </span>
                        <span className="text-[10px] text-zinc-400 font-mono print:hidden">
                          {copiedIndex === idx ? "✓ Copied" : "Copy"}
                        </span>
                      </div>
                      <div className="p-3 bg-white border border-zinc-200/80 rounded font-mono text-sm text-zinc-900 overflow-x-auto text-center flex flex-col items-center justify-center gap-2">
                        {(() => {
                          try {
                            const res = latexToSvg(f.latex, { width: 380, height: 60 });
                            if (res?.svg) {
                              return (
                                <div
                                  className="max-w-full overflow-x-auto py-1"
                                  dangerouslySetInnerHTML={{ __html: res.svg }}
                                />
                              );
                            }
                          } catch {
                            // Fallback to text
                          }
                          return <div>$${f.latex}$$</div>;
                        })()}
                        <span className="text-[11px] text-zinc-400 font-mono select-all">
                          {f.latex}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Cleared Misconceptions & Discussion */}
            <section className="space-y-4">
              <div className="border-b border-zinc-100 pb-2">
                <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
                  <span>💡</span> Cleared Misconceptions & Clarifications
                </h2>
              </div>

              {(cheatSheet.misconceptions ?? []).length === 0 ? (
                <p className="text-xs text-zinc-500 italic p-4 bg-zinc-50 rounded-lg">
                  No misconceptions or interrupt questions were recorded for this session.
                </p>
              ) : (
                <div className="space-y-3">
                  {(cheatSheet.misconceptions ?? []).map((m, idx) => (
                    <div
                      key={`misc_${idx}`}
                      className="p-4 bg-emerald-50/40 border border-emerald-200/80 rounded-lg space-y-2"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-bold text-emerald-800">
                          Topic: {m.subtopic_title || m.subtopic_path}
                        </span>
                        <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-100 px-2 py-0.5 rounded">
                          Resolved in Q&A
                        </span>
                      </div>
                      <div className="text-xs space-y-1">
                        <p className="text-zinc-800">
                          <span className="font-semibold text-zinc-600">Question / Misconception:</span>{" "}
                          &ldquo;{m.question}&rdquo;
                        </p>
                        <p className="text-zinc-700">
                          <span className="font-semibold text-emerald-700">Clarification:</span>{" "}
                          {m.clarification}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Footer */}
            <footer className="border-t border-zinc-100 pt-6 flex items-center justify-between text-[11px] text-zinc-400 font-mono">
              <span>AI Video Tutor — $0 Open Academic Architecture</span>
              <span>Headless Playout & Persistence Engine</span>
            </footer>
          </>
        ) : null}
      </div>
    </div>
  );
}
