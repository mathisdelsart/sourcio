"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** A minimal, accessible loading spinner. */
export function Spinner({ className }: { className?: string }) {
  const { t } = useT();
  return (
    <span
      role="status"
      aria-label={t("common.loading")}
      className={cn(
        "inline-block h-4 w-4 animate-spin rounded-full border-2 border-zinc-300 border-t-indigo-600 dark:border-zinc-600 dark:border-t-indigo-400",
        className,
      )}
    />
  );
}
