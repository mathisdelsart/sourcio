"use client";

import { useCallback, useEffect, useState } from "react";
import { history, type ConnectionConfig, type HistoryItem } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface HistoryPanelProps {
  studentId: string;
  config: ConnectionConfig;
  active: boolean;
}

function formatTime(iso: string, locale: Locale): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function isUser(role: string): boolean {
  return role.toLowerCase() === "user";
}

export function HistoryPanel({ studentId, config, active }: HistoryPanelProps) {
  const toast = useToast();
  const { t, locale } = useT();
  const [items, setItems] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await history(studentId, 20, config);
      setItems(rows);
      setLoaded(true);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }, [studentId, config, toast, t]);

  // Auto-load when the tab becomes active for a student that hasn't loaded yet.
  useEffect(() => {
    if (active && !loaded && !loading) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  return (
    <Card>
      <CardHeader
        title={t("history.title")}
        description={t("history.description")}
        action={
          <Button variant="secondary" onClick={load} loading={loading}>
            {t("history.refresh")}
          </Button>
        }
      />
      <CardBody>
        {loading && items.length === 0 ? (
          <Skeleton lines={5} />
        ) : items.length === 0 ? (
          <EmptyState
            title={t("history.empty.title")}
            description={t("history.empty.description")}
          />
        ) : (
          <ol className="space-y-4">
            {items.map((turn, i) => (
              <li
                key={`${turn.created_at}-${i}`}
                className={cn("flex flex-col gap-1", isUser(turn.role) ? "items-end" : "items-start")}
              >
                <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-500">
                  <span className="font-medium capitalize text-zinc-500 dark:text-zinc-400">
                    {turn.role}
                  </span>
                  {turn.created_at && <span>· {formatTime(turn.created_at, locale)}</span>}
                </div>
                <div
                  className={cn(
                    "max-w-[85%] rounded-xl border px-4 py-3",
                    isUser(turn.role)
                      ? "border-indigo-100 bg-indigo-50/70 dark:border-indigo-500/30 dark:bg-indigo-500/10"
                      : "border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-800/60",
                  )}
                >
                  <Markdown>{turn.content}</Markdown>
                </div>
              </li>
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}
