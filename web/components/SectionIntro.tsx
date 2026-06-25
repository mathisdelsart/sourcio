"use client";

import { useT } from "@/lib/i18n";
import type { TranslationKey } from "@/lib/i18n";

interface SectionIntroProps {
  /** Small brand uppercase eyebrow. */
  eyebrow: TranslationKey;
  /** Bold section title. */
  title: TranslationKey;
  /** One muted subtitle line. */
  subtitle: TranslationKey;
  /** id for the heading, used by the section's aria-labelledby. */
  headingId: string;
  /** Render on a dark band (navy) — flips the muted colours for contrast. */
  onDark?: boolean;
}

/**
 * Consistent landing section intro: a centered brand uppercase eyebrow, a bold
 * title, and a single muted subtitle line. Shared by How-it-works, Features and
 * the stats band so every section opens with the same rhythm.
 */
export function SectionIntro({
  eyebrow,
  title,
  subtitle,
  headingId,
  onDark = false,
}: SectionIntroProps) {
  const { t } = useT();
  return (
    <div className="mx-auto max-w-2xl text-center">
      <p
        className={
          onDark
            ? "text-xs font-semibold uppercase tracking-wider text-brand-300"
            : "text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400"
        }
      >
        {t(eyebrow)}
      </p>
      <h2
        id={headingId}
        className={
          onDark
            ? "mt-3 text-balance text-3xl font-bold tracking-tight text-white sm:text-4xl"
            : "mt-3 text-balance text-3xl font-bold tracking-tight text-ink dark:text-zinc-50 sm:text-4xl"
        }
      >
        {t(title)}
      </h2>
      <p
        className={
          onDark
            ? "mx-auto mt-4 max-w-2xl text-pretty text-base leading-relaxed text-zinc-300"
            : "mx-auto mt-4 max-w-2xl text-pretty text-base leading-relaxed text-zinc-600 dark:text-zinc-300"
        }
      >
        {t(subtitle)}
      </p>
    </div>
  );
}
