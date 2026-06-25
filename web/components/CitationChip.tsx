/**
 * A small citation pill. The label arrives pre-formatted from the API, e.g.
 * "(ELEC2885 Wavelet Transform, p.12)" — we render it verbatim.
 */
export function CitationChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-indigo-500 dark:bg-indigo-400" />
      {label}
    </span>
  );
}
