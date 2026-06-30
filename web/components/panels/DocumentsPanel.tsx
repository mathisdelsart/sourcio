"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  deleteDocument,
  listDocuments,
  uploadDocument,
  type ConnectionConfig,
  type DocumentCourse,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";

interface DocumentsPanelProps {
  // Documents are global to the indexed collection, not student-scoped; the id
  // is accepted to match the other panels' call signature.
  studentId: string;
  config: ConnectionConfig;
}

/** Stable key for a course/chapter row, used to track the in-flight deletion. */
function rowKey(course: string, chapter: string | null): string {
  return `${course}::${chapter ?? ""}`;
}

export function DocumentsPanel({ config }: DocumentsPanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [items, setItems] = useState<DocumentCourse[]>([]);
  const [loading, setLoading] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [course, setCourse] = useState("");
  const [chapter, setChapter] = useState("");
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await listDocuments(config);
      setItems(rows);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }, [config, toast, t]);

  // The panel only mounts when its tab is active (and remounts on tab switch),
  // so a one-shot load on mount is enough.
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function upload() {
    if (!file || !course.trim() || uploading) return;
    setUploading(true);
    try {
      const result = await uploadDocument(file, course.trim(), chapter.trim() || null, config);
      toast.push(
        t("doc.upload.success", { pages: result.pages_indexed, course: result.course }),
        "success",
      );
      setFile(null);
      setChapter("");
      if (fileInputRef.current) fileInputRef.current.value = "";
      await load();
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setUploading(false);
    }
  }

  async function remove(courseName: string, chapterName: string | null) {
    if (deleting) return;
    const label = chapterName ? `${courseName} — ${chapterName}` : courseName;
    if (!window.confirm(t("doc.delete.confirm", { target: label }))) return;
    const key = rowKey(courseName, chapterName);
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

  const canUpload = !!file && course.trim().length > 0 && !uploading;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader title={t("doc.upload.title")} description={t("doc.upload.description")} />
        <CardBody>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="doc-file"
                className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
              >
                {t("doc.upload.file")}
              </label>
              <input
                id="doc-file"
                ref={fileInputRef}
                type="file"
                accept=".pdf,.md,.txt"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                className="block w-full text-sm text-zinc-600 file:mr-4 file:rounded-lg file:border-0 file:bg-brand-50 file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-brand-700 hover:file:bg-brand-100 dark:text-zinc-300 dark:file:bg-brand-500/10 dark:file:text-brand-300"
              />
              <p className="text-xs text-zinc-500 dark:text-zinc-400">{t("doc.upload.fileHint")}</p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row">
              <div className="flex-1">
                <TextField
                  label={t("doc.upload.course")}
                  placeholder={t("doc.upload.coursePlaceholder")}
                  value={course}
                  onChange={(e) => setCourse(e.target.value)}
                />
              </div>
              <div className="flex-1">
                <TextField
                  label={t("doc.upload.chapter")}
                  hint={t("doc.upload.chapterHint")}
                  placeholder={t("doc.upload.chapterPlaceholder")}
                  value={chapter}
                  onChange={(e) => setChapter(e.target.value)}
                />
              </div>
            </div>
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
          action={
            <Button variant="secondary" onClick={load} loading={loading}>
              {t("doc.refresh")}
            </Button>
          }
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
                  className="space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40"
                >
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                        {courseItem.course}
                      </p>
                      <p className="text-xs text-zinc-500 dark:text-zinc-400">
                        {t("doc.pageCount", { count: courseItem.total_pages })}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      onClick={() => remove(courseItem.course, null)}
                      loading={deleting === rowKey(courseItem.course, null)}
                    >
                      {t("doc.delete.course")}
                    </Button>
                  </div>
                  <ul className="space-y-1.5">
                    {courseItem.chapters.map((ch) => (
                      <li
                        key={rowKey(courseItem.course, ch.chapter)}
                        className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-800/60"
                      >
                        <span className="text-zinc-700 dark:text-zinc-200">
                          {ch.chapter ?? t("doc.uncategorized")}
                        </span>
                        <div className="flex items-center gap-3">
                          <span className="text-xs tabular-nums text-zinc-500 dark:text-zinc-400">
                            {t("doc.pageCount", { count: ch.pages })}
                          </span>
                          <Button
                            variant="ghost"
                            onClick={() => remove(courseItem.course, ch.chapter)}
                            loading={deleting === rowKey(courseItem.course, ch.chapter)}
                          >
                            {t("doc.delete.chapter")}
                          </Button>
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
