import { Suspense } from "react";
import Link from "next/link";
import MasteryDashboard from "@/components/courses/MasteryDashboard";

export const instant = false;

export default async function CoursePage({
  params,
}: {
  params: Promise<{ courseId: string }>;
}) {
  const { courseId } = await params;

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 font-sans">
      <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-zinc-200 shadow-xs">
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-xs font-semibold text-zinc-500 hover:text-zinc-900 transition-colors"
          >
            ← Home
          </Link>
          <span className="text-zinc-300">/</span>
          <h1 className="text-lg font-bold text-zinc-900">Course Mastery</h1>
          <span className="text-xs text-zinc-500 font-mono bg-zinc-100 px-2 py-0.5 rounded">
            {courseId}
          </span>
        </div>

        <div className="flex items-center gap-3">
          <Link
            href={`/courses/${courseId}/syllabus`}
            className="text-xs px-3 py-1.5 font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-md transition-colors shadow-xs"
          >
            Syllabus Inspector →
          </Link>
        </div>
      </header>

      <main className="max-w-5xl mx-auto p-6 sm:p-8">
        <Suspense fallback={<div className="text-xs text-zinc-400">Loading mastery dashboard...</div>}>
          <MasteryDashboard courseId={courseId} />
        </Suspense>
      </main>
    </div>
  );
}
