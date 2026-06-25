"use client";

import { useEffect, useId, useRef, useState } from "react";
import { getCourses, type ConnectionConfig } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const baseField =
  "w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm text-zinc-900 placeholder:text-zinc-400 " +
  "transition-colors focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 " +
  "disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-400 " +
  "dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 " +
  "dark:focus:border-indigo-400 dark:focus:ring-indigo-400/20 dark:disabled:bg-zinc-800/50 dark:disabled:text-zinc-500";

type FetchState = "loading" | "ready" | "error";

interface CourseSelectProps {
  /** Current course filter value. Empty string means "All courses" (no filter). */
  value: string;
  /** Called with the chosen course, or an empty string for "All courses". */
  onChange: (course: string) => void;
  config: ConnectionConfig;
  label?: string;
  hint?: string;
}

/**
 * Course filter backed by `GET /courses`. Fetches the indexed courses on mount
 * and renders an accessible dropdown with an "All courses" option (sends no
 * filter). If the list is empty or the request fails, it degrades to a free-text
 * input so the filter never blocks the UI. Re-fetches when the connection target
 * changes; if the persisted value is missing from the returned list it is kept
 * as an extra option so a saved choice is not silently dropped.
 */
export function CourseSelect({
  value,
  onChange,
  config,
  label,
  hint,
}: CourseSelectProps) {
  const { t } = useT();
  const id = useId();
  const [courses, setCourses] = useState<string[]>([]);
  const [state, setState] = useState<FetchState>("loading");

  const configRef = useRef(config);
  configRef.current = config;

  useEffect(() => {
    let active = true;
    setState("loading");
    getCourses(configRef.current)
      .then((list) => {
        if (!active) return;
        setCourses(list);
        setState("ready");
      })
      .catch(() => {
        if (!active) return;
        setCourses([]);
        setState("error");
      });
    return () => {
      active = false;
    };
    // Re-run when the connection target changes.
  }, [config.baseUrl, config.apiKey, config.token]);

  const resolvedLabel = label ?? t("ask.courseLabel");

  // Free-text fallback: request failed, or succeeded with no indexed courses.
  if (state === "error" || (state === "ready" && courses.length === 0)) {
    const resolvedHint =
      state === "error" ? t("course.fetchFailed") : hint ?? t("ask.courseHint");
    return (
      <div className="space-y-1.5">
        <label
          htmlFor={id}
          className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
        >
          {resolvedLabel}
        </label>
        <input
          id={id}
          className={baseField}
          placeholder={t("ask.coursePlaceholder")}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
        <p className="text-xs text-zinc-400 dark:text-zinc-500">{resolvedHint}</p>
      </div>
    );
  }

  const loading = state === "loading";
  // Keep a persisted value that is not (yet) in the fetched list as an option.
  const options =
    value && !courses.includes(value) ? [value, ...courses] : courses;

  return (
    <div className="space-y-1.5">
      <label
        htmlFor={id}
        className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
      >
        {resolvedLabel}
      </label>
      <select
        id={id}
        className={cn(baseField, "pr-8")}
        value={value}
        disabled={loading}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">
          {loading ? t("course.loading") : t("course.allCourses")}
        </option>
        {options.map((course) => (
          <option key={course} value={course}>
            {course}
          </option>
        ))}
      </select>
      <p className="text-xs text-zinc-400 dark:text-zinc-500">
        {hint ?? t("ask.courseHint")}
      </p>
    </div>
  );
}
