"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createSession,
  deleteSession,
  listSessions,
  type ConnectionConfig,
  type SessionOut,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { RefreshButton } from "@/components/RefreshButton";
import { TextField } from "@/components/TextField";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT, type Locale } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface ThreadsPanelProps {
  studentId: string;
  config: ConnectionConfig;
  /** Only fetch when this tab is shown, mirroring the History panel. */
  active: boolean;
  /** Active thread id, or null for "All history (unthreaded)". */
  activeSessionId: number | null;
  setActiveSessionId: (id: number | null) => void;
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

export function ThreadsPanel({
  studentId,
  config,
  active,
  activeSessionId,
  setActiveSessionId,
}: ThreadsPanelProps) {
  const toast = useToast();
  const { t, locale } = useT();

  const [sessions, setSessions] = useState<SessionOut[]>([]);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const [newTitle, setNewTitle] = useState("");
  const [creating, setCreating] = useState(false);

  // Thread deletion: the id awaiting red confirmation, and the one in flight.
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null);
  const [deletingId, setDeletingId] = useState<number | null>(null);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listSessions(studentId, config);
      setSessions(rows);
      setLoaded(true);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("threads.loadFailed"), "error");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId, config, toast, t]);

  // Load the thread list the first time this tab is opened for a student.
  useEffect(() => {
    if (active && !loaded && !loading) {
      loadSessions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  async function onCreate() {
    setCreating(true);
    try {
      const created = await createSession(studentId, newTitle, config);
      setNewTitle("");
      setSessions((prev) => [created, ...prev]);
      setActiveSessionId(created.id);
      toast.push(t("threads.created"), "success");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("threads.createFailed"), "error");
    } finally {
      setCreating(false);
    }
  }

  async function removeThread(id: number) {
    setConfirmDelete(null);
    setDeletingId(id);
    try {
      await deleteSession(studentId, id, config);
      setSessions((prev) => prev.filter((s) => s.id !== id));
      // Deleting the active thread falls back to "all history".
      if (id === activeSessionId) {
        setActiveSessionId(null);
      }
      toast.push(t("threads.deleted"), "success");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("threads.deleteFailed"), "error");
    } finally {
      setDeletingId(null);
    }
  }

  const selectRow =
    "w-full rounded-lg border px-4 py-3 text-left text-sm transition-colors focus:outline-none " +
    "focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-950";
  const selectedRow =
    "border-brand-300 bg-brand-50/70 dark:border-brand-500/40 dark:bg-brand-500/10";
  const idleRow =
    "border-zinc-200 bg-white hover:bg-zinc-50 dark:border-zinc-700 dark:bg-zinc-800/40 dark:hover:bg-zinc-800";

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("threads.title")}
          description={
            <>
              {t("threads.description.line1")}
              <br />
              {t("threads.description.line2")}
            </>
          }
          action={<RefreshButton onRefresh={loadSessions} label={t("threads.refresh")} />}
        />
        <CardBody className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <TextField
                label={t("threads.newTitleLabel")}
                placeholder={t("threads.newTitlePlaceholder")}
                value={newTitle}
                onChange={(e) => setNewTitle(e.target.value)}
              />
            </div>
            <Button onClick={onCreate} loading={creating}>
              {t("threads.create")}
            </Button>
          </div>

          <div className="space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              {t("threads.list.title")}
            </p>

            <button
              type="button"
              onClick={() => setActiveSessionId(null)}
              aria-pressed={activeSessionId == null}
              className={cn(selectRow, activeSessionId == null ? selectedRow : idleRow)}
            >
              <span className="flex items-center justify-between gap-3">
                <span className="font-medium text-zinc-800 dark:text-zinc-100">
                  {t("threads.none")}
                </span>
                {activeSessionId == null && (
                  <span className="rounded-full bg-brand-600 px-2 py-0.5 text-xs font-medium text-white dark:bg-brand-500">
                    {t("threads.active")}
                  </span>
                )}
              </span>
              <span className="mt-0.5 block text-xs text-zinc-400 dark:text-zinc-500">
                {t("threads.noneHint")}
              </span>
            </button>

            {loading && sessions.length === 0 ? (
              <Skeleton lines={3} />
            ) : sessions.length === 0 ? (
              loaded ? (
                <EmptyState
                  title={t("threads.empty.title")}
                  description={t("threads.empty.description")}
                />
              ) : null
            ) : (
              <ul className="space-y-2">
                {sessions.map((s) => {
                  const selected = s.id === activeSessionId;
                  const title = s.title?.trim() || t("threads.untitled");
                  return (
                    <li key={s.id} className="flex items-stretch gap-2">
                      <button
                        type="button"
                        onClick={() => setActiveSessionId(s.id)}
                        aria-pressed={selected}
                        aria-label={t("threads.select", { title })}
                        className={cn(selectRow, "flex-1", selected ? selectedRow : idleRow)}
                      >
                        <span className="flex items-center justify-between gap-3">
                          <span className="truncate font-medium text-zinc-800 dark:text-zinc-100">
                            {title}
                          </span>
                          {selected && (
                            <span className="shrink-0 rounded-full bg-brand-600 px-2 py-0.5 text-xs font-medium text-white dark:bg-brand-500">
                              {t("threads.active")}
                            </span>
                          )}
                        </span>
                        {s.created_at && (
                          <span className="mt-0.5 block text-xs text-zinc-400 dark:text-zinc-500">
                            {formatTime(s.created_at, locale)}
                          </span>
                        )}
                      </button>

                      {confirmDelete === s.id ? (
                        <span className="flex shrink-0 flex-col items-stretch justify-center gap-1">
                          <button
                            type="button"
                            onClick={() => removeThread(s.id)}
                            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                          >
                            {t("threads.delete.yes")}
                          </button>
                          <button
                            type="button"
                            onClick={() => setConfirmDelete(null)}
                            className="text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-800"
                          >
                            {t("common.cancel")}
                          </button>
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => setConfirmDelete(s.id)}
                          disabled={deletingId === s.id}
                          aria-label={t("threads.delete")}
                          title={t("threads.delete")}
                          className="flex shrink-0 items-center rounded-lg border border-zinc-200 px-3 text-zinc-400 transition-colors hover:border-red-300 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 dark:border-zinc-700"
                        >
                          <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                            <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V6" />
                            <path d="M10 11v6M14 11v6" />
                          </svg>
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </CardBody>
      </Card>
    </div>
  );
}
