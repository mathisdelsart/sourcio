"use client";

import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";
import { SectionIntro } from "@/components/SectionIntro";

interface Stat {
  value: TranslationKey;
  label: TranslationKey;
}

/**
 * Real, measured figures only — every number is taken verbatim from the
 * README metrics table (retrieval hit-rate, hybrid gain, threshold
 * separation, faithfulness) plus the fully-local zero-cost option.
 */
const STATS: Stat[] = [
  { value: "stats.hitRate.value", label: "stats.hitRate.label" },
  { value: "stats.hybrid.value", label: "stats.hybrid.label" },
  { value: "stats.separation.value", label: "stats.separation.label" },
  { value: "stats.faithfulness.value", label: "stats.faithfulness.label" },
  { value: "stats.local.value", label: "stats.local.label" },
];

/**
 * Full-width navy band with big bold stat figures and small labels, lit by a
 * subtle brand radial glow. Breaks out of the centered landing column.
 */
export function StatsBand() {
  const { t } = useT();
  return (
    <section
      aria-labelledby="stats-heading"
      className="relative overflow-hidden border-y border-navy-900 bg-navy text-white"
    >
      {/* Subtle brand glow. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(80%_120%_at_50%_-10%,theme(colors.brand.500/22%),transparent_60%)]"
      />
      <div className="relative mx-auto max-w-6xl px-4 py-20 sm:px-6 sm:py-24">
        <SectionIntro
          eyebrow="stats.eyebrow"
          title="stats.title"
          subtitle="stats.subtitle"
          headingId="stats-heading"
          onDark
        />

        {/* Thin vertical dividers separate the figures on wider viewports. */}
        <dl className="mt-14 grid grid-cols-2 gap-y-12 sm:grid-cols-3 lg:grid-cols-5 lg:divide-x lg:divide-white/10">
          {STATS.map((stat) => (
            <div key={stat.value} className="px-4 text-center sm:px-6">
              <dt className="sr-only">{t(stat.label)}</dt>
              <dd>
                <span className="block text-4xl font-bold tracking-tight text-white tabular-nums sm:text-5xl">
                  {t(stat.value)}
                </span>
                <span className="mx-auto mt-3 block max-w-[16rem] text-sm leading-snug text-zinc-400">
                  {t(stat.label)}
                </span>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
