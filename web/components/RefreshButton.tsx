"use client";

import { useState } from "react";
import { Button } from "@/components/Button";
import { useT } from "@/lib/i18n";

/**
 * A refresh button that always shows a brief spinner (even when the fetch is
 * instant) and then a short green "up to date" confirmation, so a refresh never
 * looks like it did nothing. The minimum spinner is only ~0.6s — any longer is
 * the real backend call, not an artificial delay.
 */
export function RefreshButton({
  onRefresh,
  label,
}: {
  onRefresh: () => Promise<unknown>;
  label: string;
}) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  async function run() {
    if (busy) return;
    setBusy(true);
    setDone(false);
    try {
      await Promise.all([
        Promise.resolve(onRefresh()),
        new Promise((resolve) => setTimeout(resolve, 600)),
      ]);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="secondary" onClick={run} loading={busy}>
      {done ? (
        <span className="flex items-center gap-1.5 text-emerald-600">
          <svg
            aria-hidden
            viewBox="0 0 24 24"
            className="h-4 w-4"
            fill="none"
            stroke="currentColor"
            strokeWidth={2.5}
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="m5 12 5 5L20 6" />
          </svg>
          {t("common.upToDate")}
        </span>
      ) : (
        label
      )}
    </Button>
  );
}
