"use client";

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
  return (
    <div
      role="tablist"
      aria-label="Tutor sections"
      className="flex flex-wrap gap-1 rounded-xl border border-zinc-200 bg-zinc-50/80 p-1"
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
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1",
              selected
                ? "bg-white text-zinc-900 shadow-card"
                : "text-zinc-500 hover:text-zinc-800",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
