"use client";

import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";

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

/** Three concise, numbered steps explaining the product flow end to end. */
export function HowItWorks() {
  const { t } = useT();
  return (
    <section aria-labelledby="how-heading" className="py-4">
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-indigo-600 dark:text-indigo-400">
          {t("how.eyebrow")}
        </p>
        <h2
          id="how-heading"
          className="mt-3 text-balance text-2xl font-bold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-3xl"
        >
          {t("how.title")}
        </h2>
      </div>

      <ol className="mt-10 grid gap-6 sm:grid-cols-3">
        {STEPS.map((step, i) => (
          <li
            key={step.title}
            className="rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900"
          >
            <div className="flex items-center gap-3">
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950 dark:text-indigo-300">
                {step.icon}
              </span>
              <span className="text-xs font-semibold tabular-nums text-zinc-400 dark:text-zinc-500">
                {String(i + 1).padStart(2, "0")}
              </span>
            </div>
            <h3 className="mt-5 font-semibold text-zinc-900 dark:text-zinc-100">
              {t(step.title)}
            </h3>
            <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
              {t(step.body)}
            </p>
          </li>
        ))}
      </ol>
    </section>
  );
}
