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
    <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-zinc-200 px-6 py-12 text-center">
      <p className="text-sm font-medium text-zinc-700">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-zinc-400">{description}</p>}
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
            "relative overflow-hidden rounded-md bg-zinc-100",
            i === lines - 1 ? "h-4 w-2/3" : "h-4 w-full",
          )}
        >
          <div className="absolute inset-0 -translate-x-full animate-shimmer bg-gradient-to-r from-transparent via-white/60 to-transparent" />
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
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3">
      <p className="text-sm font-semibold text-amber-900">
        Refused — not covered by the course
      </p>
      {message && <p className="mt-1 text-sm text-amber-800">{message}</p>}
    </div>
  );
}
