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
      className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
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
              "whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium transition-colors",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950",
              selected
                ? "bg-zinc-900 text-white shadow-sm dark:bg-white dark:text-zinc-900"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
