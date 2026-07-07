"use client";

import { useState } from "react";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

interface SettingsPanelProps {
  studentId: string;
  baseUrl: string;
  apiKey: string;
  sourcesMax: number;
  onSave: (next: {
    studentId: string;
    baseUrl: string;
    apiKey: string;
    sourcesMax: number;
  }) => void;
}

// Bounds for the candidate-source ceiling. A too-small pool starves the answer
// of sources; a very high one slows a LOCAL model (larger context, latency).
export const SOURCES_MAX_MIN = 1;
export const SOURCES_MAX_MAX = 50;
export const DEFAULT_SOURCES_MAX = 15;

/**
 * Collapsible identity + connection settings: editable student id, API base URL
 * override, an optional API key, and the max candidate-source pool. Values are
 * persisted by the parent.
 */
export function SettingsPanel({ studentId, baseUrl, apiKey, sourcesMax, onSave }: SettingsPanelProps) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [draftStudent, setDraftStudent] = useState(studentId);
  const [draftBase, setDraftBase] = useState(baseUrl);
  const [draftKey, setDraftKey] = useState(apiKey);
  const [draftSources, setDraftSources] = useState(String(sourcesMax));

  function save() {
    // Clamp to a sane range and fall back to the current value on bad input.
    const parsed = Number.parseInt(draftSources, 10);
    const nextSources = Number.isFinite(parsed)
      ? Math.min(SOURCES_MAX_MAX, Math.max(SOURCES_MAX_MIN, parsed))
      : sourcesMax;
    onSave({
      studentId: draftStudent.trim() || studentId,
      baseUrl: draftBase.trim(),
      apiKey: draftKey.trim(),
      sourcesMax: nextSources,
    });
    setOpen(false);
  }

  return (
    <div className="rounded-2xl border border-zinc-200 bg-white shadow-card dark:border-zinc-800 dark:bg-zinc-900">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 rounded-2xl px-5 py-3.5 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 dark:focus-visible:ring-offset-zinc-900"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-zinc-700 dark:text-zinc-200">
          {t("settings.title")}
          <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
            {studentId}
          </span>
        </span>
        <span
          className={cn(
            "text-zinc-400 transition-transform dark:text-zinc-500",
            open ? "rotate-180" : "rotate-0",
          )}
          aria-hidden
        >
          ▾
        </span>
      </button>
      {open && (
        <div className="animate-fade-in space-y-4 border-t border-zinc-100 px-5 py-5 dark:border-zinc-800">
          <TextField
            label={t("settings.studentId")}
            hint={t("settings.studentIdHint")}
            value={draftStudent}
            onChange={(e) => setDraftStudent(e.target.value)}
          />
          <TextField
            label={t("settings.baseUrl")}
            hint={t("settings.baseUrlHint")}
            placeholder="http://localhost:8000"
            value={draftBase}
            onChange={(e) => setDraftBase(e.target.value)}
          />
          <TextField
            label={t("settings.apiKey")}
            hint={t("settings.apiKeyHint")}
            type="password"
            placeholder={t("settings.apiKeyPlaceholder")}
            value={draftKey}
            onChange={(e) => setDraftKey(e.target.value)}
          />
          <TextField
            label={t("settings.sourcesMax")}
            hint={t("settings.sourcesMaxHint")}
            type="number"
            inputMode="numeric"
            min={SOURCES_MAX_MIN}
            max={SOURCES_MAX_MAX}
            value={draftSources}
            onChange={(e) => setDraftSources(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              {t("common.cancel")}
            </Button>
            <Button onClick={save}>{t("common.save")}</Button>
          </div>
        </div>
      )}
    </div>
  );
}
