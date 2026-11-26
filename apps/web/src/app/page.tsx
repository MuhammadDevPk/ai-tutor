"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import type { Course } from "@/lib/api-client";

export default function Home() {
  const [courses, setCourses] = useState<Course[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authToken, setAuthToken] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [courseCode, setCourseCode] = useState("");
  const [title, setTitle] = useState("");
  const [baselineSkill, setBaselineSkill] = useState("intermediate");

  const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

  useEffect(() => {
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("auth_token") || "";
      setAuthToken(token);
    }
  }, []);

  const fetchCourses = async (token: string) => {
    if (!token) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${apiBase}/courses`, {
        headers: {
          Authorization: `Bearer ${token}`,
        },
      });
      if (res.status === 401) {
        setError("Invalid or expired authentication token. Please sign in again.");
        setCourses([]);
        setLoading(false);
        return;
      }
      if (!res.ok) {
        throw new Error(`Failed to load courses: HTTP ${res.status}`);
      }
      const data = await res.json();
      setCourses(data.items || data.courses || []);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to connect to API");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (authToken) {
      fetchCourses(authToken);
    } else {
      setLoading(false);
    }
  }, [authToken]);

  const handleDevLogin = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${apiBase}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: "dev@example.com",
          password: "devpassword123",
        }),
      });
      if (!res.ok) {
        throw new Error("Dev login failed. Ensure the API backend is running on port 8000.");
      }
      const data = await res.json();
      localStorage.setItem("auth_token", data.access_token);
      setAuthToken(data.access_token);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to log in");
      setLoading(false);
    }
  };

  const handleCreateCourse = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!courseCode || !title) return;
    try {
      setCreating(true);
      setError(null);
      const res = await fetch(`${apiBase}/courses`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          course_code: courseCode,
          title,
          baseline_skill: baselineSkill,
        }),
      });
      if (!res.ok) {
        throw new Error(`Failed to create course: HTTP ${res.status}`);
      }
      setCourseCode("");
      setTitle("");
      await fetchCourses(authToken);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create course");
    } finally {
      setCreating(false);
    }
  };

  const handleLogout = () => {
    localStorage.removeItem("auth_token");
    setAuthToken("");
    setCourses([]);
  };

  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 font-sans">
      <header className="flex items-center justify-between px-6 py-4 bg-white border-b border-zinc-200 shadow-xs">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-zinc-900">AI Video Tutor</h1>
          <p className="text-xs text-zinc-500">
            Autonomous multi-modal tutoring with 3D Avatar and synchronized whiteboard
          </p>
        </div>

        <div className="flex items-center gap-3">
          {authToken ? (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
                Signed In (Dev Account)
              </span>
              <button
                onClick={handleLogout}
                className="text-xs text-zinc-500 hover:text-zinc-800 underline px-2 py-1"
              >
                Sign out
              </button>
            </div>
          ) : (
            <button
              onClick={handleDevLogin}
              className="text-xs px-3.5 py-1.5 font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-md transition-colors shadow-xs"
            >
              Sign In with Dev Account
            </button>
          )}
        </div>
      </header>

      <main className="max-w-5xl mx-auto p-6 sm:p-8 space-y-8">
        {!authToken && (
          <div className="p-6 bg-amber-50 border border-amber-200 rounded-xl space-y-4">
            <h2 className="text-base font-semibold text-amber-900">Authentication Required</h2>
            <p className="text-sm text-amber-800">
              You are currently not signed in. Click below to automatically sign in with the local
              development credentials (<code className="bg-amber-100 px-1 py-0.5 rounded">dev@example.com</code>).
            </p>
            <div className="flex items-center gap-3">
              <button
                onClick={handleDevLogin}
                className="px-4 py-2 text-sm font-semibold text-white bg-amber-700 hover:bg-amber-800 rounded-md transition-colors"
              >
                1-Click Dev Sign In
              </button>
            </div>
          </div>
        )}

        {error && (
          <div className="p-4 bg-rose-50 border border-rose-200 text-rose-800 text-sm rounded-lg">
            {error}
          </div>
        )}

        {/* Existing Courses Section */}
        {authToken && (
          <section className="space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-zinc-900">Your Courses</h2>
              <span className="text-xs text-zinc-500">{courses.length} available</span>
            </div>

            {loading ? (
              <div className="p-8 text-center text-sm text-zinc-500">Loading courses...</div>
            ) : courses.length === 0 ? (
              <div className="p-8 text-center bg-white border border-dashed border-zinc-300 rounded-xl space-y-2">
                <p className="text-sm font-medium text-zinc-700">No courses created yet.</p>
                <p className="text-xs text-zinc-500">Create your first course below to upload PDFs and begin tutoring.</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {courses.map((c) => (
                  <div
                    key={c.id}
                    className="p-5 bg-white border border-zinc-200 rounded-xl shadow-xs hover:border-zinc-300 transition-all space-y-3 flex flex-col justify-between"
                  >
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono font-bold text-indigo-600 bg-indigo-50 px-2 py-0.5 rounded">
                          {c.course_code}
                        </span>
                        <span className="text-xs text-zinc-400 capitalize">{c.baseline_skill}</span>
                      </div>
                      <h3 className="mt-2 text-base font-semibold text-zinc-900">{c.title}</h3>
                    </div>

                    <div className="pt-2 border-t border-zinc-100 flex items-center justify-between gap-2">
                      <Link
                        href={`/courses/${c.id}`}
                        className="text-xs font-medium text-zinc-600 hover:text-zinc-900 px-2 py-1 rounded hover:bg-zinc-100 transition-colors"
                      >
                        Mastery Dashboard
                      </Link>
                      <Link
                        href={`/courses/${c.id}/syllabus`}
                        className="text-xs font-semibold text-white bg-zinc-900 hover:bg-zinc-800 px-3 py-1.5 rounded-md transition-colors"
                      >
                        Syllabus & Classroom →
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}

        {/* Create Course Section */}
        {authToken && (
          <section className="p-6 bg-white border border-zinc-200 rounded-xl shadow-xs space-y-4">
            <h2 className="text-base font-bold text-zinc-900">Create a New Course</h2>
            <form onSubmit={handleCreateCourse} className="space-y-4 max-w-xl">
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div>
                  <label className="block text-xs font-medium text-zinc-700 mb-1">
                    Course Code
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. MATH201"
                    value={courseCode}
                    onChange={(e) => setCourseCode(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-zinc-300 rounded-md focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs font-medium text-zinc-700 mb-1">
                    Course Title
                  </label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Multivariable Calculus"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-zinc-300 rounded-md focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-zinc-700 mb-1">
                  Baseline Skill Level
                </label>
                <select
                  value={baselineSkill}
                  onChange={(e) => setBaselineSkill(e.target.value)}
                  className="w-full sm:w-60 px-3 py-2 text-sm border border-zinc-300 rounded-md focus:outline-hidden focus:ring-2 focus:ring-indigo-500 bg-white"
                >
                  <option value="foundational">Foundational</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="advanced">Advanced</option>
                </select>
              </div>

              <button
                type="submit"
                disabled={creating}
                className="px-4 py-2 text-sm font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-md transition-colors disabled:opacity-50"
              >
                {creating ? "Creating..." : "Create Course"}
              </button>
            </form>
          </section>
        )}
      </main>
    </div>
  );
}
