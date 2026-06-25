"use client";

import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";
import { SectionIntro } from "@/components/SectionIntro";

/** Stacked-layers icon — "index your course". */
function IndexIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 3 3 7.5 12 12l9-4.5L12 3Z" />
      <path d="m3 12 9 4.5L21 12" />
      <path d="m3 16.5 9 4.5 9-4.5" />
    </svg>
  );
}

/** Speech-bubble icon — "ask in natural language". */
function AskIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M21 11.5a8.38 8.38 0 0 1-8.5 8.5A8.38 8.38 0 0 1 8 19l-5 1 1-4.5A8.38 8.38 0 0 1 3 11.5 8.5 8.5 0 0 1 11.5 3 8.5 8.5 0 0 1 21 11.5Z" />
    </svg>
  );
}

/** Document-with-check icon — "cited answer or refusal". */
function CitedIcon() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-5 w-5"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
      <path d="m9 14 2 2 4-4" />
    </svg>
  );
}

interface Step {
  icon: ReactNode;
  title: TranslationKey;
  body: TranslationKey;
}

const STEPS: Step[] = [
  { icon: <IndexIcon />, title: "how.step1.title", body: "how.step1.body" },
  { icon: <AskIcon />, title: "how.step2.title", body: "how.step2.body" },
  { icon: <CitedIcon />, title: "how.step3.title", body: "how.step3.body" },
];

/**
 * Three concise steps as a horizontal stepper: numbered 01/02/03 nodes joined
 * by a thin connector line, each with a brand-tinted icon square. Collapses to
 * a vertical stack on mobile.
 */
export function HowItWorks() {
  const { t } = useT();
  return (
    <section id="how" aria-labelledby="how-heading" className="scroll-mt-24 py-4">
      <SectionIntro
        eyebrow="how.eyebrow"
        title="how.title"
        subtitle="how.subtitle"
        headingId="how-heading"
      />

      <ol className="relative mt-16 grid gap-12 sm:grid-cols-3 sm:gap-8">
        {/* Connector line behind the nodes (desktop only). */}
        <div
          aria-hidden
          className="pointer-events-none absolute left-[16.67%] right-[16.67%] top-7 hidden h-px bg-gradient-to-r from-brand-200 via-brand-300 to-brand-200 dark:from-brand-900 dark:via-brand-800 dark:to-brand-900 sm:block"
        />
        {STEPS.map((step, i) => (
          <li key={step.title} className="group relative text-center">
            <div className="flex justify-center">
              <span className="relative z-10 inline-flex h-14 w-14 items-center justify-center rounded-2xl border border-brand-200 bg-brand-50 text-brand-600 shadow-sm transition group-hover:-translate-y-0.5 group-hover:shadow-md dark:border-brand-900 dark:bg-brand-950 dark:text-brand-300">
                {step.icon}
                <span className="absolute -right-2 -top-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-ink text-[11px] font-bold tabular-nums text-white dark:bg-white dark:text-ink">
                  {String(i + 1).padStart(2, "0")}
                </span>
              </span>
            </div>
            <h3 className="mt-6 text-lg font-semibold text-ink dark:text-zinc-100">
              {t(step.title)}
            </h3>
            <p className="mx-auto mt-2 max-w-xs text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
              {t(step.body)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
