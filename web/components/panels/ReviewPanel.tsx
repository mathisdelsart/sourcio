"use client";

import { useCallback, useEffect, useState } from "react";
import {
  getDueReviews,
  recordReview,
  type ConnectionConfig,
  type ReviewItem,
  type ReviewQuality,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT, type TranslationKey } from "@/lib/i18n";
import { submitOnCmdEnter } from "@/lib/keys";
import { cn } from "@/lib/cn";

interface ReviewPanelProps {
  studentId: string;
  config: ConnectionConfig;
  active: boolean;
}

/**
 * The four recall ratings, mapped onto the backend's 0..5 quality scale.
 * Again (forgot) → 0, Hard → 2, Good → 4, Easy (perfect) → 5. The intermediate
 * values are skipped so the choice stays a simple, unambiguous four-way pick.
 */
const RATINGS: ReadonlyArray<{
  quality: ReviewQuality;
  labelKey: TranslationKey;
  ariaKey: TranslationKey;
  tone: string;
}> = [
  {
    quality: 0,
    labelKey: "review.rate.again",
    ariaKey: "review.rate.againAria",
    tone:
      "border-red-200 text-red-700 hover:bg-red-50 dark:border-red-500/30 dark:text-red-300 dark:hover:bg-red-500/10",
  },
  {
    quality: 2,
    labelKey: "review.rate.hard",
    ariaKey: "review.rate.hardAria",
    tone:
      "border-amber-200 text-amber-700 hover:bg-amber-50 dark:border-amber-500/30 dark:text-amber-300 dark:hover:bg-amber-500/10",
  },
  {
    quality: 4,
    labelKey: "review.rate.good",
    ariaKey: "review.rate.goodAria",
    tone:
      "border-emerald-200 text-emerald-700 hover:bg-emerald-50 dark:border-emerald-500/30 dark:text-emerald-300 dark:hover:bg-emerald-500/10",
  },
  {
    quality: 5,
    labelKey: "review.rate.easy",
    ariaKey: "review.rate.easyAria",
    tone:
      "border-brand-200 text-brand-700 hover:bg-brand-50 dark:border-brand-500/30 dark:text-brand-300 dark:hover:bg-brand-500/10",
  },
];

export function ReviewPanel({ studentId, config, active }: ReviewPanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);
  // Notions currently being submitted, keyed by notion, to disable their row.
  const [rating, setRating] = useState<Record<string, boolean>>({});
  const [newNotion, setNewNotion] = useState("");
  const [adding, setAdding] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await getDueReviews(studentId, config);
      setItems(rows);
      setLoaded(true);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }, [studentId, config, toast, t]);

  // Auto-load the due queue the first time the tab is opened for this student.
  useEffect(() => {
    if (active && !loaded && !loading) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  /** Human-readable next-interval phrase ("1 day" / "N days"). */
  function describeInterval(days: number): string {
    const rounded = Math.max(1, Math.round(days));
    return rounded === 1 ? t("review.day") : t("review.days", { days: rounded });
  }

  async function rate(notion: string, quality: ReviewQuality) {
    if (rating[notion]) return;
    setRating((r) => ({ ...r, [notion]: true }));
    try {
      const result = await recordReview(studentId, notion, quality, config);
      // Drop the reviewed notion from the due list and confirm the next interval.
      setItems((prev) => prev.filter((it) => it.notion !== notion));
      toast.push(
        t("review.rescheduled", {
          notion,
          days: describeInterval(result.interval_days),
        }),
        "success",
      );
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setRating((r) => {
        const next = { ...r };
        delete next[notion];
        return next;
      });
    }
  }

  async function add() {
    const notion = newNotion.trim();
    if (!notion || adding) return;
    setAdding(true);
    try {
      // Seed the notion with a neutral first rating so it enters the queue.
      await recordReview(studentId, notion, 3, config);
      setNewNotion("");
      toast.push(t("review.added", { notion }), "success");
      // Reload so the new notion shows up (it is due immediately).
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setAdding(false);
    }
  }

  const canAdd = newNotion.trim().length > 0 && !adding;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={t("review.add.title")} description={t("review.description")} />
        <CardBody>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <TextField
                label={t("review.add.label")}
                hint={t("review.add.hint")}
                placeholder={t("review.add.placeholder")}
                value={newNotion}
                onChange={(e) => setNewNotion(e.target.value)}
                onKeyDown={submitOnCmdEnter(add)}
              />
            </div>
            <Button onClick={add} loading={adding} disabled={!canAdd}>
              {t("review.add.button")}
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("review.dueTitle")}
          action={
            <div className="flex items-center gap-2">
              {loaded && items.length > 0 && (
                <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium tabular-nums text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
                  {t("review.dueCount", { count: items.length })}
                </span>
              )}
              <Button variant="secondary" onClick={load} loading={loading}>
                {t("review.refresh")}
              </Button>
            </div>
          }
        />
        <CardBody>
          {loading && items.length === 0 ? (
            <Skeleton lines={4} />
          ) : items.length === 0 ? (
            <EmptyState
              title={t("review.empty.title")}
              description={t("review.empty.description")}
            />
          ) : (
            <ul className="space-y-4">
              {items.map((item) => {
                const busy = !!rating[item.notion];
                return (
                  <li
                    key={item.notion}
                    className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40"
                  >
                    <p className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {item.notion}
                    </p>
                    <fieldset disabled={busy} className="space-y-2">
                      <legend className="text-xs font-medium text-zinc-500 dark:text-zinc-400">
                        {t("review.rateLabel")}
                      </legend>
                      <div className="flex flex-wrap gap-2">
                        {RATINGS.map((r) => (
                          <button
                            key={r.quality}
                            type="button"
                            aria-label={t(r.ariaKey, { notion: item.notion })}
                            disabled={busy}
                            onClick={() => rate(item.notion, r.quality)}
                            className={cn(
                              "rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors",
                              "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                              "disabled:cursor-not-allowed disabled:opacity-50",
                              r.tone,
                            )}
                          >
                            {t(r.labelKey)}
                          </button>
                        ))}
                      </div>
                    </fieldset>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
