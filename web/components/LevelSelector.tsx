"use client";

import { LEVELS, type Level } from "@/lib/api";
import { useT, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const LEVEL_KEYS: Record<Level, TranslationKey> = {
  beginner: "level.beginner",
  intermediate: "level.intermediate",
  advanced: "level.advanced",
};

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
  const { t } = useT();
  return (
    <div
      role="radiogroup"
      aria-label={t("level.aria")}
      className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-1 dark:border-zinc-700 dark:bg-zinc-800"
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
              selected
                ? "bg-white text-indigo-700 shadow-card dark:bg-zinc-700 dark:text-indigo-300"
                : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
            )}
          >
            {t(LEVEL_KEYS[level])}
          </button>
        );
      })}
    </div>
  );
}
