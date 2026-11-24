"use client";

import { useEffect, useState } from "react";
import type { CourseMasteryResponse } from "@/lib/api-client";

export default function MasteryDashboard({
  courseId,
}: {
  courseId: string;
}) {
  const [mastery, setMastery] = useState<CourseMasteryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    let active = true;
    const fetchMastery = async () => {
      try {
        const token =
          typeof window !== "undefined"
            ? localStorage.getItem("auth_token") || ""
            : "";
        const headers: Record<string, string> = token
          ? { Authorization: `Bearer ${token}` }
          : {};

        const res = await fetch(`${apiBase}/courses/${courseId}/mastery`, {
          headers,
        });
        if (!res.ok) {
          throw new Error(`Failed to load mastery data (HTTP ${res.status})`);
        }
        const data: CourseMasteryResponse = await res.json();
        if (!active) return;
        setMastery(data);
        setLoading(false);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : "Failed to load mastery");
        setLoading(false);
      }
    };

    fetchMastery();
    return () => {
      active = false;
    };
  }, [courseId, apiBase]);

  if (loading) {
    return (
      <div className="p-8 text-center text-xs text-zinc-500 bg-white border border-zinc-200 rounded-xl">
        Loading course mastery statistics...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 text-xs text-red-600 bg-red-50 border border-red-200 rounded-xl">
        {error}
      </div>
    );
  }

  if (!mastery) return null;

  return (
    <div className="space-y-6">
      {/* Course Progress Card */}
      <div className="bg-white p-6 rounded-xl border border-zinc-200 shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <span className="text-xs font-bold uppercase tracking-wider text-indigo-600 block">
              Course Progress
            </span>
            <h2 className="text-xl font-bold text-zinc-900">
              {mastery.completed_chapters} of {mastery.total_chapters} Chapters Mastered
            </h2>
          </div>
          <span className="text-2xl font-extrabold text-indigo-600 font-mono">
            {mastery.completion_percentage}%
          </span>
        </div>

        {/* Progress Bar */}
        <div className="w-full bg-zinc-100 rounded-full h-3 overflow-hidden">
          <div
            className="bg-indigo-600 h-3 rounded-full transition-all duration-500 ease-out"
            style={{ width: `${Math.min(100, Math.max(0, mastery.completion_percentage))}%` }}
          />
        </div>
      </div>

      {/* Chapters Grid */}
      <div className="space-y-3">
        <h3 className="text-sm font-bold text-zinc-900">Chapter Breakdown</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {(mastery.chapters ?? []).map((ch) => (
            <div
              key={ch.chapter_path}
              className="bg-white p-4 rounded-xl border border-zinc-200 shadow-xs flex flex-col justify-between gap-3"
            >
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-[10px] font-mono text-zinc-400">
                    {ch.chapter_path}
                  </span>
                  <span
                    className={`text-[10px] font-bold px-2 py-0.5 rounded capitalize ${
                      ch.status === "completed"
                        ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                        : ch.status === "in_progress"
                        ? "bg-amber-50 text-amber-700 border border-amber-200"
                        : "bg-zinc-100 text-zinc-500"
                    }`}
                  >
                    {ch.status.replace("_", " ")}
                  </span>
                </div>
                <h4 className="text-xs font-bold text-zinc-900 line-clamp-2">
                  {ch.title}
                </h4>
              </div>

              <div className="text-[11px] text-zinc-500 border-t border-zinc-100 pt-2 flex justify-between">
                <span>Sessions: {ch.sessions_count}</span>
                <span>Q&A Loops: {ch.interrupt_qa_count}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Weak Subtopics / Areas for Review */}
      <div className="bg-white p-6 rounded-xl border border-zinc-200 shadow-xs space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-1.5">
              <span>⚠️</span> Priority Review Areas (Frequent Interrupt Q&A)
            </h3>
            <p className="text-xs text-zinc-500">
              Subtopics where you asked questions or experienced misconceptions during lectures.
            </p>
          </div>
        </div>

        {(mastery.weak_subtopics ?? []).length === 0 ? (
          <p className="text-xs text-zinc-400 italic p-3 bg-zinc-50 rounded-lg">
            No weak subtopics identified yet! Great comprehension across all tutoring sessions.
          </p>
        ) : (
          <div className="divide-y divide-zinc-100">
            {(mastery.weak_subtopics ?? []).map((item, idx) => (
              <div
                key={item.subtopic_path}
                className="py-3 flex items-center justify-between gap-4 text-xs"
              >
                <div className="flex items-center gap-3">
                  <span className="w-5 h-5 rounded-full bg-amber-50 border border-amber-200 text-amber-800 font-bold flex items-center justify-center text-[10px]">
                    {idx + 1}
                  </span>
                  <div>
                    <span className="font-semibold text-zinc-900 block">
                      {item.title}
                    </span>
                    <span className="font-mono text-[10px] text-zinc-400">
                      {item.subtopic_path}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-2 font-mono text-[11px]">
                  <span className="px-2 py-0.5 bg-amber-50 text-amber-800 border border-amber-200 rounded">
                    {item.interrupt_count} Q&A Interrupt{item.interrupt_count > 1 ? "s" : ""}
                  </span>
                  {item.misconception_count > 0 && (
                    <span className="px-2 py-0.5 bg-emerald-50 text-emerald-800 border border-emerald-200 rounded">
                      {item.misconception_count} Cleared
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
