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
      className="h-4 w-4"
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
 * dark ink CTA that smooth-scrolls to the tool. The right column is a self-
 * contained "answer preview" mock card floating on a faint radial texture.
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
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(60%_60%_at_75%_30%,theme(colors.brand.500/12%),transparent_70%)] dark:bg-[radial-gradient(60%_60%_at_75%_30%,theme(colors.brand.400/14%),transparent_70%)]"
      />

      <div className="relative grid items-center gap-12 lg:grid-cols-2">
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
            className="mt-6 max-w-2xl text-balance text-4xl font-bold leading-[1.05] tracking-tight text-ink dark:text-zinc-50 sm:text-5xl lg:text-6xl"
          >
            {t("hero.headline.lead")}{" "}
            <span className="text-brand-500 dark:text-brand-400">
              {t("hero.headline.accent")}
            </span>
          </h1>

          <p className="mt-5 max-w-xl text-pretty text-base leading-relaxed text-zinc-600 dark:text-zinc-300 sm:text-lg">
            {t("hero.description")}
          </p>

          <div className="mt-9">
            <button
              type="button"
              onClick={() => scrollToId(targetId)}
              aria-label={t("hero.ctaAria")}
              className="inline-flex items-center justify-center gap-2 rounded-xl bg-ink px-6 py-3 text-base font-medium text-white shadow-sm transition-opacity hover:opacity-90 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:bg-white dark:text-ink dark:focus-visible:ring-offset-zinc-950"
            >
              {t("hero.cta")}
              <ArrowDown />
            </button>
          </div>
        </div>

        {/* Right column: answer-preview mock. Stacks below on mobile. */}
        <div className="relative" aria-hidden>
          <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-card dark:border-zinc-800 dark:bg-zinc-900">
            <p className="text-sm font-medium text-zinc-500 dark:text-zinc-400">
              {t("hero.preview.question")}
            </p>
            <p className="mt-3 text-sm leading-relaxed text-zinc-700 dark:text-zinc-300">
              {t("hero.preview.answer")}
            </p>
            <div className="mt-4">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-[#e7f6ef] px-3 py-1 text-xs font-medium text-[#0f7a52] dark:bg-emerald-950/50 dark:text-emerald-300">
                <span
                  aria-hidden
                  className="h-1.5 w-1.5 rounded-full bg-[#0f7a52] dark:bg-emerald-400"
                />
                {t("hero.preview.citation")}
              </span>
            </div>
          </div>

          {/* Second, tiny card: an honest refusal. */}
          <div className="mt-4 rounded-xl border border-zinc-200 bg-[#f6f6f3] p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900/60">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-amber-700 dark:text-amber-400">
              {t("hero.preview.refusalLabel")}
            </p>
            <p className="mt-1.5 text-sm text-zinc-600 dark:text-zinc-300">
              {t("hero.preview.refusal")}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
