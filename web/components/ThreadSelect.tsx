"use client";

import { useCallback, useEffect, useId, useRef, useState } from "react";
import { listSessions, type ConnectionConfig, type SessionOut } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/cn";

const baseField =
  "w-full rounded-lg border border-zinc-300 bg-white px-3.5 py-2.5 text-sm text-zinc-900 " +
  "transition-colors focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 " +
  "disabled:cursor-not-allowed disabled:bg-zinc-50 disabled:text-zinc-400";

interface ThreadSelectProps {
  studentId: string;
  config: ConnectionConfig;
  /** Active thread id, or null for "All history (no thread)". */
  value: number | null;
  /** Called with the chosen thread id, or null for "All history". */
  onChange: (id: number | null) => void;
  /** Open the Threads tab to create/manage threads (named, not unnamed). */
  onManage: () => void;
}

/**
 * Compact thread switcher rendered in the tool frame so the active conversation
 * thread is visible and changeable from every tab. Threads are fetched via
 * `listSessions`; the list degrades gracefully to just "All history" on an empty
 * result or fetch error. "+ New thread" takes the user to the Threads tab to
 * create a named thread (rather than silently opening an untitled one). The
 * selection lives in the page (`activeSessionId`); this control only reflects
 * `value` and reports changes through `onChange`.
 */
export function ThreadSelect({ studentId, config, value, onChange, onManage }: ThreadSelectProps) {
  const { t } = useT();
  const id = useId();
  const [sessions, setSessions] = useState<SessionOut[]>([]);

  const configRef = useRef(config);
  configRef.current = config;

  const load = useCallback(() => {
    let active = true;
    listSessions(studentId, configRef.current)
      .then((rows) => {
        if (active) setSessions(rows);
      })
      .catch(() => {
        if (active) setSessions([]);
      });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studentId, config.baseUrl, config.apiKey, config.token]);

  useEffect(() => load(), [load]);

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-sm font-medium text-zinc-700">
        {t("threadSelect.label")}
      </label>
      <div className="flex items-center gap-2">
        <select
          id={id}
          className={cn(baseField, "pr-8")}
          value={value == null ? "" : String(value)}
          onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
        >
          <option value="">{t("threadSelect.all")}</option>
          {sessions.map((s) => (
            <option key={s.id} value={s.id}>
              {s.title?.trim() || t("threads.untitled")}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={onManage}
          className="shrink-0 whitespace-nowrap rounded-lg border border-zinc-300 bg-white px-3 py-2.5 text-sm font-medium text-zinc-700 transition-colors hover:bg-zinc-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
        >
          {t("threadSelect.new")}
        </button>
      </div>
    </div>
  );
}
