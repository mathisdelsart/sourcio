"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createSession,
  getSessionMessages,
  listSessions,
  type ConnectionConfig,
  type HistoryItem,
  type SessionOut,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
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

function isUser(role: string): boolean {
  return role.toLowerCase() === "user";
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

  const [messages, setMessages] = useState<HistoryItem[]>([]);
  const [messagesLoading, setMessagesLoading] = useState(false);

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

  const loadMessages = useCallback(
    async (sessionId: number) => {
      setMessagesLoading(true);
      try {
        const rows = await getSessionMessages(studentId, sessionId, config);
        setMessages(rows);
      } catch (err) {
        toast.push(err instanceof Error ? err.message : t("threads.messagesFailed"), "error");
        setMessages([]);
      } finally {
        setMessagesLoading(false);
      }
      // eslint-disable-next-line react-hooks/exhaustive-deps
    },
    [studentId, config, toast, t],
  );

  // Load the thread list the first time this tab is opened for a student.
  useEffect(() => {
    if (active && !loaded && !loading) {
      loadSessions();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // Fetch messages whenever a thread is selected (and on tab open with one set).
  useEffect(() => {
    if (!active) return;
    if (activeSessionId == null) {
      setMessages([]);
      return;
    }
    loadMessages(activeSessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, activeSessionId]);

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
          description={t("threads.description")}
          action={
            <Button variant="secondary" onClick={loadSessions} loading={loading}>
              {t("threads.refresh")}
            </Button>
          }
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
                    <li key={s.id}>
                      <button
                        type="button"
                        onClick={() => setActiveSessionId(s.id)}
                        aria-pressed={selected}
                        aria-label={t("threads.select", { title })}
                        className={cn(selectRow, selected ? selectedRow : idleRow)}
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
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </CardBody>
      </Card>

      {activeSessionId != null && (
        <Card>
          <CardHeader title={t("threads.messages.title")} />
          <CardBody>
            <p className="mb-4 rounded-lg border border-brand-100 bg-brand-50/70 px-4 py-2 text-sm text-brand-900 dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-200">
              {t("threads.activeBanner")}
            </p>
            {messagesLoading && messages.length === 0 ? (
              <Skeleton lines={5} />
            ) : messages.length === 0 ? (
              <EmptyState
                title={t("threads.messages.empty.title")}
                description={t("threads.messages.empty.description")}
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
                      <span className="font-medium capitalize text-zinc-500 dark:text-zinc-400">
                        {turn.role}
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
      )}
    </div>
  );
}
