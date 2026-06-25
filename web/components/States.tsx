"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** Neutral empty-state placeholder for a section with no content yet. */
export function EmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-zinc-200 bg-zinc-50/50 px-6 py-14 text-center dark:border-zinc-700 dark:bg-zinc-900/40">
      <span
        aria-hidden
        className="mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-600 dark:bg-brand-950 dark:text-brand-300"
      >
        <svg
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
          <path d="M9.5 13.5h5M9.5 16.5h3" />
        </svg>
      </span>
      <p className="text-sm font-semibold text-zinc-700 dark:text-zinc-200">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-sm text-zinc-500 dark:text-zinc-400">{description}</p>
      )}
    </div>
  );
}

/** Animated loading skeleton lines, used while a request is in flight. */
export function Skeleton({ lines = 3 }: { lines?: number }) {
  return (
    <div className="space-y-3" aria-hidden>
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={cn(
            "relative overflow-hidden rounded-md bg-zinc-100 dark:bg-zinc-800",
            i === lines - 1 ? "h-4 w-2/3" : "h-4 w-full",
          )}
        >
          <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/60 to-transparent dark:via-white/10" />
        </div>
      ))}
    </div>
  );
}

/**
 * The North-Star refusal banner: shown when the course does not cover the
 * question. Kept visually distinct (amber) so the honest-refusal behaviour is
 * obvious at a glance.
 */
export function RefusalBanner({ message }: { message: string }) {
  const { t } = useT();
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
      <p className="text-sm font-semibold text-amber-900 dark:text-amber-200">
        {t("refusal.title")}
      </p>
      {message && <p className="mt-1 text-sm text-amber-800 dark:text-amber-300/90">{message}</p>}
    </div>
  );
}
