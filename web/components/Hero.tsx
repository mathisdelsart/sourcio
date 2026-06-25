"use client";

import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";
import { scrollToId } from "@/lib/scroll";

/** Arrow-down glyph for the primary call-to-action. */
function ArrowDown() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-4 w-4 transition-transform group-hover:translate-y-0.5"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M12 5v14M19 12l-7 7-7-7" />
    </svg>
  );
}

/** Small check glyph for the positive trust badge. */
function Check() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 24 24"
      className="h-3.5 w-3.5"
      fill="none"
      stroke="currentColor"
      strokeWidth={2.5}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m5 12 5 5L20 6" />
    </svg>
  );
}

type BadgeTone = "success" | "neutral" | "brand";

interface Badge {
  key: TranslationKey;
  tone: BadgeTone;
  check?: boolean;
}

const BADGES: Badge[] = [
  { key: "hero.badge.refuses", tone: "success", check: true },
  { key: "hero.badge.cited", tone: "brand" },
  { key: "hero.badge.private", tone: "neutral" },
];

const badgeTone: Record<BadgeTone, string> = {
  success:
    "border-transparent bg-[#e7f6ef] text-[#0f7a52] dark:bg-emerald-950/50 dark:text-emerald-300",
  brand:
    "border-transparent bg-brand-50 text-brand-700 dark:bg-brand-950 dark:text-brand-300",
  neutral:
    "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300",
};

/**
 * Landing hero: left-aligned, two-column on desktop. A trust-badges row sits
 * above a two-tone headline (ink lead + brand accent), a supporting line, and a
 * dark ink CTA that smooth-scrolls to the tool. The right column is a larger
 * app-window mockup — a faux product window showing a grounded, cited answer
 * plus an honest refusal — floating on a brand radial glow.
 */
export function Hero({ targetId = "tool" }: { targetId?: string }) {
  const { t } = useT();
  return (
    <section
      aria-labelledby="hero-heading"
      className="relative overflow-hidden rounded-3xl border border-zinc-200 bg-white px-6 py-20 dark:border-zinc-800 dark:bg-zinc-950 sm:px-10 sm:py-24"
    >
      {/* Faint concentric radial texture behind the hero. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_78%_30%,theme(colors.brand.500/14%),transparent_70%)] dark:bg-[radial-gradient(60%_60%_at_78%_30%,theme(colors.brand.400/16%),transparent_70%)]"
      />

      <div className="relative grid items-center gap-14 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
        {/* Left column: copy + CTA. */}
        <div className="text-left">
          <ul className="flex flex-wrap gap-2" aria-label={t("hero.principles")}>
            {BADGES.map((badge) => (
              <li
                key={badge.key}
                className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${badgeTone[badge.tone]}`}
              >
                {badge.check && <Check />}
                {t(badge.key)}
              </li>
            ))}
          </ul>

          <h1
            id="hero-heading"
            className="mt-6 max-w-2xl text-balance text-4xl font-bold leading-[1.03] tracking-tight text-ink dark:text-zinc-50 sm:text-5xl lg:text-[3.75rem]"
          >
            {t("hero.headline.lead")}{" "}
            <span className="text-brand-500 dark:text-brand-400">
              {t("hero.headline.accent")}
            </span>
          </h1>

          <p className="mt-6 max-w-xl text-pretty text-base leading-relaxed text-zinc-600 dark:text-zinc-300 sm:text-lg">
            {t("hero.description")}
          </p>

          <div className="mt-10">
            <button
              type="button"
              onClick={() => scrollToId(targetId)}
              aria-label={t("hero.ctaAria")}
              className="group inline-flex items-center justify-center gap-2 rounded-xl bg-ink px-6 py-3 text-base font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:opacity-90 hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:bg-white dark:text-ink dark:focus-visible:ring-offset-zinc-950"
            >
              {t("hero.cta")}
              <ArrowDown />
            </button>
          </div>
        </div>

        {/* Right column: app-window mockup. Stacks below on mobile. */}
        <AppMockup />
      </div>
    </section>
  );
}

/** Three-dot glyph row for the faux window top bar. */
function WindowDots() {
  return (
    <div className="flex items-center gap-1.5" aria-hidden>
      <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
      <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
      <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
    </div>
  );
}

/**
 * A larger faux app window: top bar with dots + title, a tab strip hint, an
 * input line, a grounded answer with a periwinkle citation chip, and a small
 * honest-refusal state. Decorative only (aria-hidden).
 */
function AppMockup() {
  const { t } = useT();
  const tabs = [
    t("hero.app.tab.ask"),
    t("hero.app.tab.exercise"),
    t("hero.app.tab.grade"),
  ];
  return (
    <div className="relative" aria-hidden>
      {/* Brand glow pooled behind the window. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -inset-6 rounded-[2rem] bg-[radial-gradient(60%_55%_at_50%_45%,theme(colors.brand.500/22%),transparent_75%)] blur-xl"
      />
      <div className="relative overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl shadow-ink/10 ring-1 ring-black/[0.02] dark:border-zinc-800 dark:bg-zinc-900 dark:shadow-black/40">
        {/* Browser chrome: traffic-light dots + a faint URL pill. */}
        <div className="flex items-center gap-3 border-b border-zinc-200 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-950/40">
          <WindowDots />
          <span className="mx-auto flex max-w-[16rem] flex-1 items-center justify-center gap-1.5 truncate rounded-md border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
            <svg viewBox="0 0 24 24" className="h-3 w-3 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
              <rect x="5" y="11" width="14" height="9" rx="2" />
              <path d="M8 11V8a4 4 0 0 1 8 0v3" />
            </svg>
            grounded-tutor.app
          </span>
          {/* Spacer to balance the dots so the pill stays centered. */}
          <span aria-hidden className="w-[42px]" />
        </div>

        {/* Tab strip. */}
        <div className="flex items-center gap-1 border-b border-zinc-200 px-3 pt-2.5 dark:border-zinc-800">
          {tabs.map((label, i) => (
            <span
              key={label}
              className={
                i === 0
                  ? "rounded-t-md border-b-2 border-brand-500 px-3 pb-2 text-xs font-semibold text-ink dark:text-zinc-100"
                  : "px-3 pb-2 text-xs font-medium text-zinc-400 dark:text-zinc-500"
              }
            >
              {label}
            </span>
          ))}
        </div>

        <div className="space-y-4 p-5">
          {/* Question input line. */}
          <div className="flex items-center gap-2 rounded-lg border border-zinc-200 bg-zinc-50 px-3 py-2.5 dark:border-zinc-700 dark:bg-zinc-950/40">
            <span className="flex h-4 w-4 items-center justify-center text-zinc-400">
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <circle cx="11" cy="11" r="7" />
                <path d="m21 21-4.3-4.3" />
              </svg>
            </span>
            <span className="text-sm text-zinc-600 dark:text-zinc-300">
              {t("hero.preview.question")}
            </span>
          </div>

          {/* Grounded answer with a token-by-token feel. */}
          <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900/60">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-[#0f7a52] dark:text-emerald-400">
              <span aria-hidden className="flex h-3.5 w-3.5 items-center justify-center">
                <Check />
              </span>
              {t("hero.app.answered")}
            </p>
            <p className="mt-2.5 text-sm leading-6 text-zinc-700 dark:text-zinc-300">
              {t("hero.preview.answer")}
              {/* Caret hinting at streamed tokens. */}
              <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-brand-500 align-baseline dark:bg-brand-400" />
            </p>
            <div className="mt-3.5 border-t border-zinc-100 pt-3 dark:border-zinc-800">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 dark:bg-brand-950 dark:text-brand-300">
                <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-500 dark:bg-brand-400" />
                {t("hero.preview.citation")}
              </span>
            </div>
          </div>

          {/* Second state: an honest refusal. */}
          <div className="rounded-xl border border-amber-200/70 bg-amber-50/60 p-3.5 dark:border-amber-900/50 dark:bg-amber-950/20">
            <p className="text-sm text-zinc-500 dark:text-zinc-400">
              {t("hero.app.refusalQuestion")}
            </p>
            <p className="mt-1.5 flex items-center gap-1.5 text-sm font-medium text-amber-700 dark:text-amber-400">
              <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
              {t("hero.preview.refusal")}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
