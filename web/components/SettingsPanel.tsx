"use client";

import { useState } from "react";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { cn } from "@/lib/cn";

interface SettingsPanelProps {
  studentId: string;
  baseUrl: string;
  apiKey: string;
  onSave: (next: { studentId: string; baseUrl: string; apiKey: string }) => void;
}

/**
 * Collapsible identity + connection settings: editable student id, API base URL
 * override, and an optional API key. Values are persisted by the parent.
 */
export function SettingsPanel({ studentId, baseUrl, apiKey, onSave }: SettingsPanelProps) {
  const [open, setOpen] = useState(false);
  const [draftStudent, setDraftStudent] = useState(studentId);
  const [draftBase, setDraftBase] = useState(baseUrl);
  const [draftKey, setDraftKey] = useState(apiKey);

  function save() {
    onSave({
      studentId: draftStudent.trim() || studentId,
      baseUrl: draftBase.trim(),
      apiKey: draftKey.trim(),
    });
    setOpen(false);
  }

  return (
    <div className="rounded-xl border border-zinc-200 bg-white shadow-card">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-zinc-700">
          Settings
          <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2 py-0.5 text-xs font-normal text-zinc-500">
            {studentId}
          </span>
        </span>
        <span
          className={cn(
            "text-zinc-400 transition-transform",
            open ? "rotate-180" : "rotate-0",
          )}
          aria-hidden
        >
          ▾
        </span>
      </button>
      {open && (
        <div className="animate-fade-in space-y-4 border-t border-zinc-100 px-4 py-4">
          <TextField
            label="Student id"
            hint="Identifies you to the tutor. Persisted in this browser."
            value={draftStudent}
            onChange={(e) => setDraftStudent(e.target.value)}
          />
          <TextField
            label="API base URL"
            hint="Overrides NEXT_PUBLIC_API_BASE_URL. Leave empty to use the default."
            placeholder="http://localhost:8000"
            value={draftBase}
            onChange={(e) => setDraftBase(e.target.value)}
          />
          <TextField
            label="API key"
            hint="Optional — sent as the X-API-Key header when set."
            type="password"
            placeholder="(none)"
            value={draftKey}
            onChange={(e) => setDraftKey(e.target.value)}
          />
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={save}>Save</Button>
          </div>
        </div>
      )}
    </div>
  );
}
