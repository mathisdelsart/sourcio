"use client";

import { useEffect, useState } from "react";
import { getSource, type ConnectionConfig, type SourceChunk } from "@/lib/api";
import { Markdown } from "@/components/Markdown";
import { Spinner } from "@/components/Spinner";
import { useT } from "@/lib/i18n";

const CHIP =
  "inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700";

/**
 * A citation pill. The label arrives pre-formatted from the API, e.g.
 * "(Wavelet Transform, p.12)". When a chunk `id` is provided the chip becomes a
 * button that opens the exact source excerpt (resolved via GET /source/{id}) in
 * a modal, so the reader can check precisely where a claim comes from. Without
 * an id it renders as a plain, non-interactive pill. When `n` is given, the chip
 * leads with the inline marker `[n]` so it pairs with the `[n]` in the answer.
 */
export function CitationChip({
  label,
  id,
  n,
  config,
}: {
  label: string;
  id?: string;
  n?: number;
  config?: ConnectionConfig;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [chunk, setChunk] = useState<SourceChunk | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  // Close the modal on Escape while it is open.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Lead with the inline marker `[n]` when given, otherwise a small dot.
  const marker =
    typeof n === "number" ? (
      <span className="font-semibold tabular-nums">[{n}]</span>
    ) : (
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-500" />
    );

  if (!id) {
    return (
      <span className={CHIP}>
        {marker}
        {label}
      </span>
    );
  }

  async function openSource() {
    setOpen(true);
    if (chunk || loading) return;
    setLoading(true);
    setFailed(false);
    try {
      setChunk(await getSource(id!, config));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={openSource}
        title={t("source.view")}
        className={`${CHIP} cursor-pointer transition-colors hover:bg-brand-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2`}
      >
        {marker}
        {label}
        <svg
          aria-hidden
          viewBox="0 0 24 24"
          className="h-3 w-3 opacity-70"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>

      {open && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label={label}
          className="fixed inset-0 z-50 flex items-center justify-center p-4"
        >
          <div
            aria-hidden
            onClick={() => setOpen(false)}
            className="absolute inset-0 bg-ink/40 backdrop-blur-sm"
          />
          <div className="relative flex max-h-[80vh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-card-hover">
            <div className="flex items-start justify-between gap-4 border-b border-zinc-100 px-5 py-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wider text-brand-600">
                  {t("source.title")}
                </p>
                <p className="mt-1 text-sm font-semibold text-zinc-900">{label}</p>
              </div>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label={t("source.close")}
                className="rounded-lg p-1 text-zinc-400 transition-colors hover:bg-zinc-100 hover:text-zinc-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
              >
                <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 6 6 18M6 6l12 12" />
                </svg>
              </button>
            </div>
            <div className="overflow-y-auto px-5 py-4">
              {loading ? (
                <p className="flex items-center gap-2 text-sm text-zinc-500">
                  <Spinner /> {t("common.loading")}
                </p>
              ) : failed ? (
                <p className="text-sm text-red-600">{t("source.failed")}</p>
              ) : chunk ? (
                <Markdown>{chunk.text}</Markdown>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </>
  );
}
