"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  ApiError,
  deleteDocument,
  fetchDocumentFile,
  getJob,
  listDocuments,
  startUpload,
  type ConnectionConfig,
  type DocumentCourse,
  type DocumentProgress,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { RefreshButton } from "@/components/RefreshButton";
import { TextField, FieldShell, baseField } from "@/components/TextField";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface DocumentsPanelProps {
  studentId: string;
  config: ConnectionConfig;
  /**
   * Called after a successful upload so the parent can refresh the course
   * selectors (Ask/Exercise/Quiz) — a freshly indexed course then appears
   * without a manual page refresh.
   */
  onCoursesChanged?: () => void;
  /**
   * The visitor's own OpenAI key, lifted to the page so it stays in sync with
   * the account-menu setting (both persist to the same storage key). When set it
   * is sent on every request (including this upload) so LLM calls use the
   * visitor's own premium model instead of the free one.
   */
  openaiKey: string;
  /** Persist a new OpenAI key value (writes localStorage in the parent). */
  onOpenaiKeyChange: (value: string) => void;
}

function rowKey(course: string, chapter: string | null): string {
  return `${course}::${chapter ?? ""}`;
}

/**
 * localStorage key holding the currently running upload, so a page refresh or
 * navigation can re-attach to the background server job instead of losing it.
 */
const ACTIVE_JOB_KEY = "activeUploadJob";

/** What we persist about a running upload: the job id plus a label for the UI. */
interface ActiveJob {
  job_id: string;
  course: string;
  filename: string;
}

function loadActiveJob(): ActiveJob | null {
  try {
    const raw = localStorage.getItem(ACTIVE_JOB_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as ActiveJob;
    return parsed && typeof parsed.job_id === "string" ? parsed : null;
  } catch {
    return null;
  }
}

/** Client-side extension guard; the backend stays the final arbiter. */
const ACCEPTED_EXTENSIONS = [".pdf", ".md", ".txt"];

function isSupportedFile(name: string): boolean {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

/** Format seconds as m:ss (or s when under a minute). */
function fmtTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function DocumentsPanel({
  studentId,
  config,
  onCoursesChanged,
  openaiKey,
  onOpenaiKeyChange,
}: DocumentsPanelProps) {
  const toast = useToast();
  const { t } = useT();
  const openaiKeyId = useId();
  const [items, setItems] = useState<DocumentCourse[]>([]);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [course, setCourse] = useState("");
  const [chapter, setChapter] = useState("");
  // The OpenAI key is lifted to the page (props) so it stays in sync with the
  // account-menu setting; only the show/hide toggle is local here.
  const [showKey, setShowKey] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  // Row currently awaiting an explicit red confirmation before deletion.
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  // Live ingestion progress; null when no upload is running.
  const [progress, setProgress] = useState<DocumentProgress | null>(null);
  const [uploading, setUploading] = useState(false);
  // The background job being polled; null when none is active. Set on upload and
  // on mount (resume) — it is what drives the polling effect below.
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  // True while a file is being dragged over the dropzone (drives the accent styling).
  const [dragging, setDragging] = useState(false);
  // Live elapsed seconds, ticked by a client interval so the clock counts up
  // continuously rather than only when an SSE progress event arrives.
  const [liveElapsed, setLiveElapsed] = useState(0);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Set the file into the shared state used by the button flow, rejecting
  // obviously unsupported types with a gentle message.
  const acceptFile = useCallback(
    (candidate: File | null) => {
      if (!candidate) {
        setFile(null);
        return;
      }
      if (!isSupportedFile(candidate.name)) {
        toast.push(t("doc.upload.unsupported"), "error");
        return;
      }
      setFile(candidate);
    },
    [toast, t],
  );

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listDocuments(config, studentId));
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }, [config, studentId, toast, t]);

  useEffect(() => {
    load();
    // On mount, re-attach to a background job left running by a previous visit
    // (started before a refresh/navigation). The polling effect takes over.
    const resumed = loadActiveJob();
    if (resumed) setActiveJob(resumed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Poll the background ingestion job once one is active. This is the single
  // place progress is fed, whether the job was just started or resumed after a
  // refresh, so both paths render identically. On a terminal status it stops,
  // clears the persisted job, and refreshes the inventory + course selectors. A
  // 404 means the server restarted or pruned the job: clear it and just reload.
  useEffect(() => {
    if (!activeJob) return;
    setUploading(true);
    let cancelled = false;

    const finish = (clear: boolean) => {
      if (clear) localStorage.removeItem(ACTIVE_JOB_KEY);
      setUploading(false);
      setActiveJob(null);
    };

    const poll = async () => {
      try {
        const job = await getJob(activeJob.job_id, config);
        if (cancelled) return;
        setProgress(job);
        if (job.status === "done" || job.status === "error") {
          finish(true);
          if (job.status === "done") {
            await load();
            // A new course may now be indexed: let the parent refresh its pickers.
            onCoursesChanged?.();
          }
        }
      } catch (err) {
        if (cancelled) return;
        if (err instanceof ApiError && err.status === 404) {
          // Server restarted or job pruned: drop it and reconcile the inventory.
          setProgress(null);
          finish(true);
          await load();
        }
        // Other (transient) errors: keep polling on the next tick.
      }
    };

    poll();
    const id = window.setInterval(poll, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [activeJob, config, load, onCoursesChanged]);

  // Live elapsed clock: while an upload is running, anchor a monotonic start
  // timestamp and tick every second, so the elapsed time counts up smoothly on
  // its own (the SSE `elapsed` only updates per processed page, in jumps).
  useEffect(() => {
    if (!uploading) return;
    const start = performance.now();
    setLiveElapsed(0);
    const id = window.setInterval(() => {
      setLiveElapsed((performance.now() - start) / 1000);
    }, 1000);
    return () => window.clearInterval(id);
  }, [uploading]);

  async function upload() {
    if (!file || !course.trim() || uploading) return;
    setUploading(true);
    setProgress({ type: "start" });
    try {
      const { job_id } = await startUpload(
        file,
        course.trim(),
        chapter.trim() || null,
        config,
        studentId,
        openaiKey.trim() || null,
      );
      // Persist the job so a refresh/navigation re-attaches to it, then hand off
      // to the polling effect. Clearing the inputs frees the user to do other
      // things (or queue nothing) while ingestion runs server-side.
      const job: ActiveJob = { job_id, course: course.trim(), filename: file.name };
      localStorage.setItem(ACTIVE_JOB_KEY, JSON.stringify(job));
      setActiveJob(job);
      setFile(null);
      setChapter("");
      if (fileInputRef.current) fileInputRef.current.value = "";
    } catch (err) {
      setProgress({
        type: "error",
        message: err instanceof Error ? err.message : t("common.requestFailed"),
      });
      setUploading(false);
    }
  }

  async function viewFile(courseName: string, name: string) {
    const key = `${courseName}::${name}`;
    if (viewing) return;
    setViewing(key);
    try {
      const blob = await fetchDocumentFile(courseName, name, config);
      window.open(URL.createObjectURL(blob), "_blank", "noopener");
    } catch {
      toast.push(t("doc.viewFailed"), "error");
    } finally {
      setViewing(null);
    }
  }

  async function confirmRemove(courseName: string, chapterName: string | null) {
    const key = rowKey(courseName, chapterName);
    const label = chapterName ? `${courseName} — ${chapterName}` : courseName;
    setConfirmKey(null);
    setDeleting(key);
    try {
      const result = await deleteDocument(courseName, chapterName, config, studentId);
      toast.push(t("doc.delete.success", { count: result.deleted, target: label }), "success");
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setDeleting(null);
    }
  }

  /** Delete affordance: a neutral button that flips to a red confirm/cancel pair. */
  function DeleteControl({ courseName, chapter }: { courseName: string; chapter: string | null }) {
    const key = rowKey(courseName, chapter);
    if (confirmKey === key) {
      return (
        <span className="inline-flex items-center gap-2">
          <span className="text-xs text-zinc-500">{t("doc.delete.confirmShort")}</span>
          <button
            type="button"
            onClick={() => confirmRemove(courseName, chapter)}
            className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2"
          >
            {t("doc.delete.confirmYes")}
          </button>
          <button
            type="button"
            onClick={() => setConfirmKey(null)}
            className="rounded px-1.5 text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            {t("common.cancel")}
          </button>
        </span>
      );
    }
    return (
      <Button variant="ghost" loading={deleting === key} onClick={() => setConfirmKey(key)}>
        {chapter ? t("doc.delete.chapter") : t("doc.delete.course")}
      </Button>
    );
  }

  const canUpload = !!file && course.trim().length > 0 && !uploading;

  // Derived progress numbers for the bar.
  const total = progress?.total ?? 0;
  const done = progress?.done ?? (progress?.type === "start" ? (progress.skipped ?? 0) : 0);
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : progress ? 5 : 0;
  const elapsed = progress?.elapsed ?? 0;
  // Show the continuously ticking client clock while uploading (never behind the
  // per-page SSE elapsed); fall back to the SSE value once the run has ended.
  const displayElapsed = uploading ? Math.max(liveElapsed, elapsed) : elapsed;
  const fresh = done - (progress?.skipped ?? 0); // pages actually processed this run
  const eta = fresh > 0 && elapsed > 0 ? (elapsed / fresh) * (total - done) : null;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={t("doc.upload.title")} description={t("doc.upload.description")} />
        <CardBody>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label htmlFor="doc-file" className="block text-sm font-medium text-zinc-700">
                {t("doc.upload.file")}
              </label>

              {/* Drag-and-drop zone; clicking or Enter/Space opens the native picker. */}
              <div
                role="button"
                tabIndex={uploading ? -1 : 0}
                aria-label={t("doc.upload.dropzoneAria")}
                aria-disabled={uploading}
                onClick={() => {
                  if (!uploading) fileInputRef.current?.click();
                }}
                onKeyDown={(e) => {
                  if (uploading) return;
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    fileInputRef.current?.click();
                  }
                }}
                onDragOver={(e) => {
                  e.preventDefault();
                  if (!uploading) setDragging(true);
                }}
                onDragLeave={(e) => {
                  // Ignore leave events fired when moving between child elements.
                  if (!e.currentTarget.contains(e.relatedTarget as Node | null)) {
                    setDragging(false);
                  }
                }}
                onDrop={(e) => {
                  e.preventDefault();
                  setDragging(false);
                  if (uploading) return;
                  acceptFile(e.dataTransfer.files?.[0] ?? null);
                }}
                className={cn(
                  "flex flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-4 py-8 text-center transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2",
                  uploading
                    ? "cursor-not-allowed border-zinc-200 opacity-60"
                    : dragging
                      ? "cursor-copy border-brand-500 bg-brand-50"
                      : "cursor-pointer border-zinc-300 hover:border-brand-400 hover:bg-brand-50/40",
                )}
              >
                <UploadIcon />
                <p className="text-sm font-medium text-zinc-700">{t("doc.upload.dropzone")}</p>
                {file ? (
                  <p className="text-xs font-medium text-brand-700">
                    {t("doc.upload.selectedFile", { name: file.name })}
                  </p>
                ) : (
                  <p className="text-xs text-zinc-500">{t("doc.upload.fileHint")}</p>
                )}
              </div>

              <input
                id="doc-file"
                ref={fileInputRef}
                type="file"
                accept=".pdf,.md,.txt"
                disabled={uploading}
                onChange={(e) => acceptFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-zinc-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
              />
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="flex-1">
                <TextField
                  label={`${t("doc.upload.course")} *`}
                  placeholder={t("doc.upload.coursePlaceholder")}
                  value={course}
                  disabled={uploading}
                  onChange={(e) => setCourse(e.target.value)}
                />
              </div>
              <div className="flex-1">
                <TextField
                  label={t("doc.upload.chapter")}
                  hint={t("doc.upload.chapterHint")}
                  placeholder={t("doc.upload.chapterPlaceholder")}
                  value={chapter}
                  disabled={uploading}
                  onChange={(e) => setChapter(e.target.value)}
                />
              </div>
            </div>

            {/* Visitor's own OpenAI key for importing scanned/image PDFs. Masked
                by default with a show/hide toggle (same pattern as the sign-in
                password field). Persisted to the browser only; sent solely with
                the upload request, never stored server-side. */}
            <FieldShell
              label={t("doc.upload.openaiKey")}
              hint={t("doc.upload.openaiKeyHint")}
              id={openaiKeyId}
            >
              <div className="relative">
                <input
                  id={openaiKeyId}
                  // Masked text input (not type="password") + anti-autofill hints,
                  // so the browser never prompts to save this API key as a password.
                  type="text"
                  name="sourcio-openai-key"
                  autoComplete="off"
                  autoCorrect="off"
                  autoCapitalize="off"
                  spellCheck={false}
                  data-1p-ignore
                  data-lpignore="true"
                  placeholder="sk-…"
                  value={openaiKey}
                  disabled={uploading}
                  onChange={(e) => onOpenaiKeyChange(e.target.value)}
                  className={cn(baseField, "pr-11", !showKey && "[-webkit-text-security:disc]")}
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  aria-label={showKey ? t("doc.upload.hideKey") : t("doc.upload.showKey")}
                  aria-pressed={showKey}
                  className={cn(
                    "absolute inset-y-0 right-0 flex w-11 items-center justify-center rounded-r-lg",
                    "text-zinc-400 transition-colors hover:text-zinc-600 dark:hover:text-zinc-200",
                    "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                  )}
                >
                  {showKey ? (
                    // Eye with a slash: the key is currently visible.
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M3 3l18 18" />
                      <path d="M10.58 10.58a2 2 0 002.83 2.83" />
                      <path d="M9.36 5.18A9.46 9.46 0 0112 5c5 0 9 4.5 9 7a12.3 12.3 0 01-2.16 3.19M6.61 6.61A12.9 12.9 0 003 12c0 2.5 4 7 9 7a9.3 9.3 0 004.24-1" />
                    </svg>
                  ) : (
                    // Open eye: the key is currently hidden.
                    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
            </FieldShell>

            {/* Live ingestion progress. */}
            {progress && (
              <div
                className={cn(
                  "rounded-xl border p-4",
                  progress.type === "error"
                    ? "border-red-200 bg-red-50"
                    : progress.type === "done" && (progress.indexed ?? 0) === 0
                      ? "border-amber-200 bg-amber-50"
                      : progress.type === "done"
                        ? "border-emerald-200 bg-emerald-50"
                        : "border-brand-200 bg-brand-50/60",
                )}
                aria-live="polite"
              >
                {progress.type === "error" ? (
                  <p className="text-sm font-medium text-red-700">
                    {t("doc.progress.error", { message: progress.message ?? "" })}
                  </p>
                ) : progress.type === "done" && (progress.indexed ?? 0) === 0 ? (
                  <p className="text-sm font-medium text-amber-700">
                    {progress.reason === "already_indexed"
                      ? t("doc.progress.alreadyIndexed")
                      : t("doc.progress.empty")}
                  </p>
                ) : progress.type === "done" ? (
                  <p className="flex items-center gap-2 text-sm font-medium text-emerald-700">
                    <CheckIcon />
                    {t("doc.progress.done", { indexed: progress.indexed ?? 0 })}
                  </p>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center justify-between text-sm font-medium text-brand-700">
                      <span>
                        {total > 0
                          ? t("doc.progress.pages", { done, total })
                          : t("doc.progress.starting")}
                      </span>
                      <span className="tabular-nums text-brand-600">{pct}%</span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-brand-100">
                      <div
                        className="h-full rounded-full bg-brand-500 transition-[width] duration-700 ease-out"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                      <span>{t("doc.progress.elapsed", { time: fmtTime(displayElapsed) })}</span>
                      {eta != null && <span>{t("doc.progress.eta", { time: fmtTime(eta) })}</span>}
                      {(progress.skipped ?? 0) > 0 && (
                        <span>{t("doc.progress.skipped", { count: progress.skipped ?? 0 })}</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="flex flex-wrap items-center justify-end gap-3">
              {!!file && !course.trim() && !uploading && (
                <p className="text-xs text-amber-600">{t("doc.upload.courseRequired")}</p>
              )}
              <Button onClick={upload} loading={uploading} disabled={!canUpload}>
                {t("doc.upload.button")}
              </Button>
            </div>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("doc.library.title")}
          description={t("doc.library.description")}
          action={<RefreshButton onRefresh={load} label={t("doc.refresh")} />}
        />
        <CardBody>
          {loading && items.length === 0 ? (
            <Skeleton lines={4} />
          ) : items.length === 0 ? (
            <EmptyState title={t("doc.empty.title")} description={t("doc.empty.description")} />
          ) : (
            <ul className="space-y-4">
              {items.map((courseItem) => (
                <li
                  key={courseItem.course}
                  className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-zinc-900">{courseItem.course}</p>
                      <p className="text-xs text-zinc-500">
                        {t("doc.pageCount", { count: courseItem.total_pages })}
                      </p>
                    </div>
                    <DeleteControl courseName={courseItem.course} chapter={null} />
                  </div>

                  {/* Original files, re-openable. */}
                  {courseItem.files.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                      {courseItem.files.map((name) => (
                        <button
                          key={name}
                          type="button"
                          onClick={() => viewFile(courseItem.course, name)}
                          disabled={viewing === `${courseItem.course}::${name}`}
                          className="inline-flex items-center gap-1.5 rounded-full border border-brand-200 bg-white px-3 py-1 text-xs font-medium text-brand-700 transition-colors hover:bg-brand-50 disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
                        >
                          <FileIcon />
                          {name}
                        </button>
                      ))}
                    </div>
                  )}

                  <ul className="space-y-1.5">
                    {courseItem.chapters.map((ch) => (
                      <li
                        key={rowKey(courseItem.course, ch.chapter)}
                        className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm"
                      >
                        <span className="text-zinc-700">{ch.chapter ?? t("doc.uncategorized")}</span>
                        <div className="flex items-center gap-3">
                          <span className="text-xs tabular-nums text-zinc-500">
                            {t("doc.pageCount", { count: ch.pages })}
                          </span>
                          <DeleteControl courseName={courseItem.course} chapter={ch.chapter} />
                        </div>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
      <path d="m5 12 5 5L20 6" />
    </svg>
  );
}

function UploadIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-6 w-6 text-brand-500" fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="M17 8l-5-5-5 5" />
      <path d="M12 3v12" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}
