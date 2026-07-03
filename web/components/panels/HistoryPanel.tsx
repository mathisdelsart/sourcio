"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  clearHistory,
  getSessionMessages,
  history,
  type ConnectionConfig,
  type HistoryItem,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { RefreshButton } from "@/components/RefreshButton";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface HistoryPanelProps {
  studentId: string;
  config: ConnectionConfig;
  active: boolean;
  /** Active thread id, or null for the unthreaded flat history. */
  activeSessionId: number | null;
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

export function HistoryPanel({ studentId, config, active, activeSessionId }: HistoryPanelProps) {
  const toast = useToast();
  const { t, locale } = useT();
  const [messages, setMessages] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    // Drop any previously loaded turns up front so a failed or empty load can
    // never leave a different thread's content on screen.
    setMessages([]);
    try {
      // With an active thread, show only that thread's turns; otherwise show the
      // unthreaded flat history.
      const rows =
        activeSessionId != null
          ? await getSessionMessages(studentId, activeSessionId, config)
          : await history(studentId, 100, config);
      setMessages(rows);
    } catch (err) {
      // A 404 (e.g. a stale/empty thread id after a DB reset) is not an error:
      // treat it as an empty thread and let the empty state render.
      if (err instanceof ApiError && err.status === 404) {
        setMessages([]);
      } else {
        toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
      }
    } finally {
      setLoading(false);
    }
  }, [studentId, config, activeSessionId, toast, t]);

  // Reload when the tab becomes active or the selected thread changes.
  useEffect(() => {
    if (active) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, activeSessionId]);

  async function onClear() {
    setConfirmClear(false);
    setClearing(true);
    try {
      await clearHistory(studentId, activeSessionId, config);
      setMessages([]);
      toast.push(t("history.cleared"), "success");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("history.clearFailed"), "error");
    } finally {
      setClearing(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={t("history.title")}
        description={t("history.description")}
        action={
          <div className="flex items-center gap-2">
            {confirmClear ? (
              <>
                <button
                  type="button"
                  onClick={onClear}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                >
                  {t("history.clear.yes")}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmClear(false)}
                  className="text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:hover:text-zinc-200"
                >
                  {t("common.cancel")}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmClear(true)}
                disabled={clearing || messages.length === 0}
                className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:border-red-300 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 dark:border-zinc-700"
              >
                {t("history.clear")}
              </button>
            )}
            <RefreshButton onRefresh={load} label={t("history.refresh")} size="sm" />
          </div>
        }
      />
      <CardBody>
        {loading && messages.length === 0 ? (
          <Skeleton lines={5} />
        ) : messages.length === 0 ? (
          <EmptyState
            title={t("history.empty.title")}
            description={t("history.empty.description")}
          />
        ) : (
          <ol className="space-y-4">
            {messages.map((turn, i) => (
              <li
                key={`${turn.created_at}-${i}`}
                className={cn(
                  "flex flex-col gap-1",
                  isUser(turn.role) ? "items-end" : "items-start",
                )}
              >
                <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-500">
                  <span className="font-medium text-zinc-500 dark:text-zinc-400">
                    {isUser(turn.role) ? t("role.you") : t("role.tutor")}
                  </span>
                  {turn.created_at && <span>· {formatTime(turn.created_at, locale)}</span>}
                </div>
                <div
                  className={cn(
                    "max-w-[85%] rounded-xl border px-4 py-3",
                    isUser(turn.role)
                      ? "border-brand-100 bg-brand-50/70 dark:border-brand-500/30 dark:bg-brand-500/10"
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
