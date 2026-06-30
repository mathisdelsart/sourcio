"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocument,
  fetchDocumentFile,
  listDocuments,
  uploadDocument,
  type ConnectionConfig,
  type DocumentCourse,
  type DocumentProgress,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { RefreshButton } from "@/components/RefreshButton";
import { TextField } from "@/components/TextField";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface DocumentsPanelProps {
  studentId: string;
  config: ConnectionConfig;
}

function rowKey(course: string, chapter: string | null): string {
  return `${course}::${chapter ?? ""}`;
}

/** Format seconds as m:ss (or s when under a minute). */
function fmtTime(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function DocumentsPanel({ config }: DocumentsPanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [items, setItems] = useState<DocumentCourse[]>([]);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [course, setCourse] = useState("");
  const [chapter, setChapter] = useState("");
  const [deleting, setDeleting] = useState<string | null>(null);
  // Row currently awaiting an explicit red confirmation before deletion.
  const [confirmKey, setConfirmKey] = useState<string | null>(null);
  const [viewing, setViewing] = useState<string | null>(null);
  // Live ingestion progress; null when no upload is running.
  const [progress, setProgress] = useState<DocumentProgress | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setItems(await listDocuments(config));
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }, [config, toast, t]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function upload() {
    if (!file || !course.trim() || uploading) return;
    setUploading(true);
    setProgress({ type: "start" });
    try {
      await uploadDocument(
        file,
        course.trim(),
        chapter.trim() || null,
        (event) => setProgress(event),
        config,
      );
      setFile(null);
      setChapter("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await load();
    } catch (err) {
      setProgress({
        type: "error",
        message: err instanceof Error ? err.message : t("common.requestFailed"),
      });
    } finally {
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
      const result = await deleteDocument(courseName, chapterName, config);
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
              <input
                id="doc-file"
                ref={fileInputRef}
                type="file"
                accept=".pdf,.md,.txt"
                disabled={uploading}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-zinc-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100"
              />
              <p className="text-xs text-zinc-500">{t("doc.upload.fileHint")}</p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="flex-1">
                <TextField
                  label={t("doc.upload.course")}
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

            {/* Live ingestion progress. */}
            {progress && (
              <div
                className={cn(
                  "rounded-xl border p-4",
                  progress.type === "error"
                    ? "border-red-200 bg-red-50"
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
                        className="h-full rounded-full bg-brand-500 transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500">
                      <span>{t("doc.progress.elapsed", { time: fmtTime(elapsed) })}</span>
                      {eta != null && <span>{t("doc.progress.eta", { time: fmtTime(eta) })}</span>}
                      {(progress.skipped ?? 0) > 0 && (
                        <span>{t("doc.progress.skipped", { count: progress.skipped ?? 0 })}</span>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            <div className="flex justify-end">
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

function FileIcon() {
  return (
    <svg aria-hidden viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8l-5-5Z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}
