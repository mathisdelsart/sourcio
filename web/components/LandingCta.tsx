"use client";

import { useT } from "@/lib/i18n";
import { scrollToId } from "@/lib/scroll";

/** Closing call-to-action that scrolls down into the tool. */
export function LandingCta({ targetId = "tool" }: { targetId?: string }) {
  const { t } = useT();
  return (
    <section
      aria-labelledby="landing-cta-heading"
      className="relative overflow-hidden rounded-3xl border border-navy-900 bg-navy px-6 py-14 text-center shadow-sm dark:border-zinc-800 sm:px-10 sm:py-16"
    >
      {/* Subtle radial glow — a "trust / quality" highlight. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(70%_70%_at_50%_0%,theme(colors.brand.500/22%),transparent_70%)]"
      />
      <div className="relative">
        <h2
          id="landing-cta-heading"
          className="mx-auto max-w-xl text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl"
        >
          {t("landing.cta.title")}
        </h2>
        <p className="mx-auto mt-4 max-w-lg text-pretty text-base leading-relaxed text-zinc-300">
          {t("landing.cta.body")}
        </p>
        <div className="mt-8 flex justify-center">
          <button
            type="button"
            onClick={() => scrollToId(targetId)}
            aria-label={t("hero.ctaAria")}
            className="inline-flex items-center justify-center rounded-xl bg-brand-500 px-6 py-3 text-base font-medium text-white shadow-sm transition hover:-translate-y-0.5 hover:bg-brand-400 hover:shadow-md active:bg-brand-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 focus-visible:ring-offset-navy"
          >
            {t("landing.cta.button")}
          </button>
        </div>
      </div>
    </section>
  );
}
