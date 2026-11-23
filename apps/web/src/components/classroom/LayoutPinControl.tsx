"use client";

import type { LayoutMode } from "@/lib/avatar/flipLayout";

export interface LayoutPinControlProps {
  mode: LayoutMode;
  onChange: (newMode: LayoutMode) => void;
  className?: string;
}

export default function LayoutPinControl({
  mode,
  onChange,
  className = "",
}: LayoutPinControlProps) {
  const options: Array<{ id: LayoutMode; label: string; icon: React.ReactNode }> = [
    {
      id: "AUTO",
      label: "Auto",
      icon: (
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M13 10V3L4 14h7v7l9-11h-7z"
          />
        </svg>
      ),
    },
    {
      id: "FULL_AVATAR",
      label: "Full Avatar",
      icon: (
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"
          />
        </svg>
      ),
    },
    {
      id: "PIP_WHITEBOARD",
      label: "PiP Whiteboard",
      icon: (
        <svg
          className="w-3.5 h-3.5"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M4 6a2 2 0 012-2h12a2 2 0 012 2v12a2 2 0 01-2 2H6a2 2 0 01-2-2V6zm10 2h4v4h-4V8z"
          />
        </svg>
      ),
    },
  ];

  return (
    <div
      className={`inline-flex items-center p-0.5 bg-zinc-100 rounded-lg border border-zinc-200/80 shadow-2xs ${className}`}
      role="group"
      aria-label="Classroom Layout Mode"
    >
      {options.map((opt) => {
        const isActive = mode === opt.id;
        return (
          <button
            key={opt.id}
            type="button"
            onClick={() => onChange(opt.id)}
            className={`flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-md transition-all ${
              isActive
                ? "bg-white text-indigo-700 shadow-xs font-semibold"
                : "text-zinc-600 hover:text-zinc-900 hover:bg-zinc-200/50"
            }`}
            aria-pressed={isActive}
            title={`Switch to ${opt.label} mode`}
          >
            {opt.icon}
            <span>{opt.label}</span>
          </button>
        );
      })}
    </div>
  );
}
