"use client";

import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";
import { SectionIntro } from "@/components/SectionIntro";
import { CountUp } from "@/components/CountUp";

interface Stat {
  value: TranslationKey;
  label: TranslationKey;
}

/**
 * Benefit-first figures (no internal jargon): every answer is cited, answers
 * come from the user's own courses, the full toolset, and the free start. The
 * numbers count up the first time the band scrolls into view.
 */
const STATS: Stat[] = [
  { value: "stats.cited.value", label: "stats.cited.label" },
  { value: "stats.fromCourse.value", label: "stats.fromCourse.label" },
  { value: "stats.tools.value", label: "stats.tools.label" },
  { value: "stats.free.value", label: "stats.free.label" },
];

/**
 * Full-width navy band with big bold stat figures and short labels, lit by a
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

        {/* Thin vertical dividers separate the figures on wider viewports.
            Each stat renders its figure once (dd) and its label once (dt),
            with column-reverse so the big figure sits above the label. */}
        <dl className="mt-14 grid grid-cols-2 gap-y-12 lg:grid-cols-4 lg:divide-x lg:divide-white/10">
          {STATS.map((stat) => (
            <div
              key={stat.value}
              className="flex flex-col-reverse items-center px-4 text-center sm:px-6"
            >
              <dt className="mt-3 max-w-[15rem] text-sm leading-snug text-zinc-300">
                {t(stat.label)}
              </dt>
              <dd className="text-4xl font-bold tracking-tight text-white tabular-nums sm:text-5xl">
                <CountUp value={t(stat.value)} />
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
