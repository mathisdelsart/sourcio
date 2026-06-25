"use client";

import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

export interface TabItem {
  id: string;
  label: string;
}

/** Segmented tab strip. Controlled via `active` / `onChange`. */
export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: TabItem[];
  active: string;
  onChange: (id: string) => void;
}) {
  const { t } = useT();
  return (
    <div
      role="tablist"
      aria-label={t("tabs.aria")}
      className="flex flex-wrap gap-1 rounded-xl border border-zinc-200 bg-zinc-50/80 p-1 dark:border-zinc-800 dark:bg-zinc-900/80"
    >
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={cn(
              "rounded-lg px-3.5 py-1.5 text-sm font-medium transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1 dark:focus-visible:ring-offset-zinc-900",
              selected
                ? "bg-white text-zinc-900 shadow-card dark:bg-zinc-700 dark:text-zinc-50"
                : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-100",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
