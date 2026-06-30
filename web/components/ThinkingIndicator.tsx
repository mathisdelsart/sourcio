"use client";

import { useEffect, useState } from "react";
import { Spinner } from "@/components/Spinner";
import { useT, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** Which staged message sequence to cycle through. */
export type ThinkingVariant = "answer" | "exercise" | "grade" | "quiz";

/** Ordered i18n keys per variant — retrieval → reading → writing, etc. */
const SEQUENCES: Record<ThinkingVariant, TranslationKey[]> = {
  answer: ["thinking.answer.1", "thinking.answer.2", "thinking.answer.3"],
  exercise: ["thinking.exercise.1", "thinking.exercise.2"],
  grade: ["thinking.grade.1", "thinking.grade.2", "thinking.grade.3"],
  quiz: ["thinking.quiz.1", "thinking.quiz.2"],
};

/** How long each stage message is shown before advancing to the next. */
const STEP_MS = 1600;

/** True when the user asked the OS to minimize motion. */
function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const onChange = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);
  return reduced;
}

/**
 * Friendly "what the tutor is doing" indicator. Cycles through stage messages
 * every ~1.6s and then holds on the last one, so a slow local-LLM wait reads as
 * real work rather than a stuck screen. Honors `prefers-reduced-motion` by
 * skipping the cycling and the spinner animation.
 */
export function ThinkingIndicator({
  variant,
  className,
}: {
  variant: ThinkingVariant;
  className?: string;
}) {
  const { t } = useT();
  const reduced = usePrefersReducedMotion();
  const steps = SEQUENCES[variant];
  const [index, setIndex] = useState(0);

  // Reset to the first stage when the variant changes mid-mount.
  useEffect(() => {
    setIndex(0);
  }, [variant]);

  useEffect(() => {
    if (reduced) return;
    if (index >= steps.length - 1) return; // Hold on the last message.
    const id = setTimeout(() => setIndex((i) => i + 1), STEP_MS);
    return () => clearTimeout(id);
  }, [reduced, index, steps.length]);

  // Reduced motion: no cycling, just show the last (overall) stage statically.
  const message = reduced ? t(steps[steps.length - 1]) : t(steps[index]);

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex items-center gap-3 text-sm text-zinc-500 dark:text-zinc-400",
        className,
      )}
    >
      <Spinner className="motion-reduce:animate-none" />
      <span key={message} className={cn(!reduced && "animate-fade-in")}>
        {message}
      </span>
    </div>
  );
}
