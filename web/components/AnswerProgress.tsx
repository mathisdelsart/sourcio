"use client";

import { Spinner } from "@/components/Spinner";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/**
 * Real, event-driven progress for a streamed answer. The two steps reflect
 * actual backend stages emitted over SSE — "retrieving" (embedding + vector
 * search) then "generating" (sources found, the model is writing) — not a timer.
 * Once tokens start streaming the answer text itself takes over as the progress.
 */
export function AnswerProgress({
  stage,
  sources,
}: {
  stage: "retrieving" | "generating" | null;
  sources: number | null;
}) {
  const { t } = useT();
  const activeIndex = stage === "generating" ? 1 : 0;
  const pct = stage === "generating" ? 70 : 30;

  const steps = [
    { label: t("answerProgress.search"), hint: null as string | null },
    {
      label: t("answerProgress.write"),
      hint: sources != null ? t("answerProgress.sourcesFound", { count: sources }) : null,
    },
  ];

  return (
    <div className="space-y-3" role="status" aria-live="polite">
      <div className="h-2 w-full overflow-hidden rounded-full bg-brand-100">
        <div
          className="h-full rounded-full bg-brand-500 transition-all duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>
      <ul className="space-y-2">
        {steps.map((s, i) => {
          const done = i < activeIndex;
          const active = i === activeIndex;
          return (
            <li key={s.label} className="flex items-center gap-2.5 text-sm">
              <span className="flex h-5 w-5 shrink-0 items-center justify-center">
                {done ? (
                  <svg viewBox="0 0 24 24" className="h-4 w-4 text-emerald-500" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                    <path d="m5 12 5 5L20 6" />
                  </svg>
                ) : active ? (
                  <Spinner />
                ) : (
                  <span className="h-1.5 w-1.5 rounded-full bg-zinc-300" aria-hidden />
                )}
              </span>
              <span
                className={cn(
                  done ? "text-zinc-500" : active ? "font-medium text-zinc-800" : "text-zinc-400",
                )}
              >
                {s.label}
                {active && s.hint && (
                  <span className="ml-1.5 text-xs font-normal text-zinc-400">· {s.hint}</span>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
