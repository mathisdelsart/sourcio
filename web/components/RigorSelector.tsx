"use client";

import { RIGORS, type Rigor } from "@/lib/api";
import { useT, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const RIGOR_KEYS: Record<Rigor, TranslationKey> = {
  lenient: "rigor.lenient",
  standard: "rigor.standard",
  strict: "rigor.strict",
};

/** Segmented control for choosing the marking strictness applied when grading. */
export function RigorSelector({
  value,
  onChange,
  disabled,
}: {
  value: Rigor;
  onChange: (rigor: Rigor) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  return (
    <div
      role="radiogroup"
      aria-label={t("rigor.aria")}
      className="inline-flex rounded-lg border border-zinc-200 bg-zinc-50 p-1 dark:border-zinc-700 dark:bg-zinc-800"
    >
      {RIGORS.map((rigor) => {
        const selected = rigor === value;
        return (
          <button
            key={rigor}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(rigor)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
              "disabled:cursor-not-allowed disabled:opacity-50",
              selected
                ? "bg-white text-brand-700 shadow-card dark:bg-zinc-700 dark:text-brand-300"
                : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
            )}
          >
            {t(RIGOR_KEYS[rigor])}
          </button>
        );
      })}
    </div>
  );
}
