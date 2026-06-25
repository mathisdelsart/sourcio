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
  /** Bento span — the highlighted tile is wider/taller than the rest. */
  span: string;
}

/** Secondary tiles — the highlighted "cited" tile is rendered separately. */
const FEATURES: Feature[] = [
  {
    icon: <ShieldIcon />,
    title: "features.refusal.title",
    body: "features.refusal.body",
    span: "lg:col-span-3",
  },
  {
    icon: <SearchIcon />,
    title: "features.retrieval.title",
    body: "features.retrieval.body",
    span: "lg:col-span-3",
  },
  {
    icon: <LockIcon />,
    title: "features.private.title",
    body: "features.private.body",
    span: "lg:col-span-2",
  },
  {
    icon: <RepeatIcon />,
    title: "features.quiz.title",
    body: "features.quiz.body",
    span: "lg:col-span-2",
  },
  {
    icon: <GlobeIcon />,
    title: "features.bilingual.title",
    body: "features.bilingual.body",
    span: "lg:col-span-2",
  },
];

const TILE =
  "rounded-2xl border border-zinc-200 bg-white p-6 shadow-sm transition-shadow hover:shadow-md dark:border-zinc-800 dark:bg-zinc-900";

/** A bento grid of the product's real differentiators. */
export function Features() {
  const { t } = useT();
  return (
    <section id="features" aria-labelledby="features-heading" className="scroll-mt-24 py-4">
      <div className="text-center">
        <p className="text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400">
          {t("features.eyebrow")}
        </p>
        <h2
          id="features-heading"
          className="mt-3 text-balance text-3xl font-bold tracking-tight text-ink dark:text-zinc-50 sm:text-4xl"
        >
          {t("features.title")}
        </h2>
      </div>

      <ul className="mt-12 grid auto-rows-fr gap-5 sm:grid-cols-2 lg:grid-cols-6">
        {/* Highlighted lead tile: cited by construction, with a mini visual. */}
        <li className="lg:col-span-3 lg:row-span-2">
          <div className="relative flex h-full flex-col overflow-hidden rounded-2xl border border-brand-200 bg-gradient-to-br from-brand-50 to-white p-7 shadow-sm dark:border-brand-900/60 dark:from-brand-950/40 dark:to-zinc-900">
            <div
              aria-hidden
              className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-brand-500/10 blur-2xl dark:bg-brand-400/10"
            />
            <div className="relative">
              <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand-500/15 text-brand-600 dark:bg-brand-400/20 dark:text-brand-300">
                <QuoteIcon />
              </span>
              <h3 className="mt-5 text-lg font-semibold text-ink dark:text-zinc-100">
                {t("features.cited.title")}
              </h3>
              <p className="mt-2 max-w-md text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
                {t("features.cited.body")}
              </p>
            </div>

            {/* Mini visual: an answer fragment carrying a periwinkle citation chip. */}
            <div className="relative mt-auto pt-6">
              <div className="rounded-xl border border-zinc-200 bg-white/80 p-4 shadow-sm backdrop-blur dark:border-zinc-800 dark:bg-zinc-900/70">
                <p className="text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
                  {t("features.cited.demo.answer")}
                </p>
                <div className="mt-3">
                  <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                    <span
                      aria-hidden
                      className="h-1.5 w-1.5 rounded-full bg-brand-500 dark:bg-brand-400"
                    />
                    {t("features.cited.demo.chip")}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </li>

        {/* Remaining tiles in varied spans. */}
        {FEATURES.map((feature) => (
          <li key={feature.title} className={feature.span}>
            <div className={`${TILE} flex h-full flex-col`}>
              <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500/10 text-brand-600 dark:bg-brand-400/15 dark:text-brand-300">
                {feature.icon}
              </span>
              <h3 className="mt-5 font-semibold text-ink dark:text-zinc-100">
                {t(feature.title)}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
                {t(feature.body)}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
