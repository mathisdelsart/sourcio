"use client";

import { LEVELS, type Level } from "@/lib/api";
import { cn } from "@/lib/cn";

/** Segmented control for choosing the re-explanation audience level. */
export function LevelSelector({
  value,
  onChange,
  disabled,
}: {
  value: Level;
  onChange: (level: Level) => void;
  disabled?: boolean;
}) {
  return (
    <div
      role="radiogroup"
      aria-label="Re-explanation level"
      className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-1"
    >
      {LEVELS.map((level) => {
        const selected = level === value;
        return (
          <button
            key={level}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(level)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500",
              "disabled:cursor-not-allowed disabled:opacity-50",
              selected ? "bg-white text-indigo-700 shadow-card" : "text-zinc-500 hover:text-zinc-800",
            )}
          >
            {level}
          </button>
        );
      })}
    </div>
  );
}
