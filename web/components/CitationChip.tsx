/**
 * A small citation pill. The label arrives pre-formatted from the API, e.g.
 * "(ELEC2885 Wavelet Transform, p.12)" — we render it verbatim.
 */
export function CitationChip({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-50 px-3 py-1 text-xs font-medium text-brand-700 dark:bg-brand-950 dark:text-brand-300">
      <span aria-hidden className="h-1.5 w-1.5 rounded-full bg-brand-500 dark:bg-brand-400" />
      {label}
    </span>
  );
}
