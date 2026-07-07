"use client";

import { useEffect, useId, useState } from "react";
import { getChapters, type ConnectionConfig } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const baseField =
  "w-full rounded-lg border border-zinc-300 bg-white px-3.5 py-2.5 text-sm text-zinc-900 placeholder:text-zinc-400 " +
  "transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 " +
  "disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-400 " +
  "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 " +
  "dark:focus:border-brand-400 dark:focus:ring-brand-400/20 dark:disabled:bg-zinc-800/50 dark:disabled:text-zinc-500";

interface ChapterSelectProps {
  /** The currently selected course. Empty string means no course is chosen. */
  course: string;
  /** Owner id used to scope the chapter list to the caller's own material. */
  studentId: string;
  config: ConnectionConfig;
  /** Current chapter filter value. Empty string means "All chapters" (no filter). */
  value: string;
  /** Called with the chosen chapter, or an empty string for "All chapters". */
  onChange: (chapter: string) => void;
  label?: string;
}

/**
 * Chapter filter that depends on the selected course: it fetches that course's
 * own chapters (owner-scoped) and offers them in a dropdown with an "All
 * chapters" option that sends no filter. When no course is selected, or the
 * course has no chapters, the control is disabled with a short hint explaining
 * why, so the user is never faced with a free-text field that expects an exact,
 * unknown chapter name. The chosen chapter is sent to ask/exercise/quiz exactly
 * as before (empty = no chapter filter).
 */
export function ChapterSelect({
  course,
  studentId,
  config,
  value,
  onChange,
  label,
}: ChapterSelectProps) {
  const { t } = useT();
  const id = useId();
  const [chapters, setChapters] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const trimmedCourse = course.trim();

  // Refetch the course's chapters whenever the selected course, owner, or
  // connection target changes. With no course there is nothing to scope to, so
  // skip the request and clear the list.
  useEffect(() => {
    if (!trimmedCourse) {
      setChapters([]);
      setLoading(false);
      setError(false);
      return;
    }
    let active = true;
    setLoading(true);
    setError(false);
    getChapters(trimmedCourse, studentId, config)
      .then((list) => {
        if (!active) return;
        setChapters(list);
        setLoading(false);
      })
      .catch(() => {
        if (!active) return;
        setChapters([]);
        setError(true);
        setLoading(false);
      });
    return () => {
      active = false;
    };
    // The connection primitives are the real fetch inputs; `config` is derived
    // from them, so depend on those rather than the object identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trimmedCourse, studentId, config.baseUrl, config.apiKey, config.token]);

  // Drop a chosen chapter that is not in the current course's list (e.g. after
  // switching course) so the filter never sends a chapter from another course.
  useEffect(() => {
    if (loading || error) return;
    if (value && !chapters.includes(value)) onChange("");
  }, [loading, error, value, chapters, onChange]);

  const resolvedLabel = label ?? t("ask.chapterLabel");
  const disabled = !trimmedCourse || loading || error || chapters.length === 0;

  // The hint explains the current state, especially why the control is disabled.
  let hint: string;
  if (!trimmedCourse) hint = t("chapter.selectCourseFirst");
  else if (loading) hint = t("chapter.loading");
  else if (error) hint = t("chapter.fetchFailed");
  else if (chapters.length === 0) hint = t("chapter.none");
  else hint = t("ask.chapterHint");

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
        {resolvedLabel}
      </label>
      <select
        id={id}
        className={cn(baseField, "pr-8")}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{t("chapter.all")}</option>
        {chapters.map((chapter) => (
          <option key={chapter} value={chapter}>
            {chapter}
          </option>
        ))}
      </select>
      <p className="text-xs text-zinc-500 dark:text-zinc-400">{hint}</p>
    </div>
  );
}
