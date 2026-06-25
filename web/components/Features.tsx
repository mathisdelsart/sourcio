"use client";

import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";

function QuoteIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 21v-4a4 4 0 0 1 4-4h1" />
      <path d="M3 13V8a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2" />
      <path d="M14 21v-4a4 4 0 0 1 4-4h1" />
      <path d="M14 13V8a2 2 0 0 1 2-2h3a2 2 0 0 1 2 2v3a2 2 0 0 1-2 2" />
    </svg>
  );
}

function ShieldIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z" />
      <path d="m9 12 2 2 4-4" />
    </svg>
  );
}

function SearchIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="7" />
      <path d="m21 21-4.3-4.3" />
    </svg>
  );
}

function LockIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="9" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  );
}

function RepeatIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <path d="m17 2 4 4-4 4" />
      <path d="M3 11V9a4 4 0 0 1 4-4h14" />
      <path d="m7 22-4-4 4-4" />
      <path d="M21 13v2a4 4 0 0 1-4 4H3" />
    </svg>
  );
}

function GlobeIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="9" />
      <path d="M3 12h18" />
      <path d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18Z" />
    </svg>
  );
}

interface Feature {
  icon: ReactNode;
  title: TranslationKey;
  body: TranslationKey;
}

const FEATURES: Feature[] = [
  { icon: <QuoteIcon />, title: "features.cited.title", body: "features.cited.body" },
  { icon: <ShieldIcon />, title: "features.refusal.title", body: "features.refusal.body" },
  { icon: <SearchIcon />, title: "features.retrieval.title", body: "features.retrieval.body" },
  { icon: <LockIcon />, title: "features.private.title", body: "features.private.body" },
  { icon: <RepeatIcon />, title: "features.quiz.title", body: "features.quiz.body" },
  { icon: <GlobeIcon />, title: "features.bilingual.title", body: "features.bilingual.body" },
];

/** A grid of the product's real differentiators. */
export function Features() {
  const { t } = useT();
  return (
    <section aria-labelledby="features-heading" className="py-4">
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-indigo-600 dark:text-indigo-400">
          {t("features.eyebrow")}
        </p>
        <h2
          id="features-heading"
          className="mt-2 text-balance text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-50 sm:text-2xl"
        >
          {t("features.title")}
        </h2>
      </div>

      <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature) => (
          <li
            key={feature.title}
            className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-card transition-shadow hover:shadow-card-hover dark:border-zinc-800 dark:bg-zinc-900"
          >
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-500/10 dark:text-indigo-400">
              {feature.icon}
            </span>
            <h3 className="mt-4 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              {t(feature.title)}
            </h3>
            <p className="mt-1.5 text-sm leading-relaxed text-zinc-600 dark:text-zinc-400">
              {t(feature.body)}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}
