"use client";

import { useEffect, useMemo, useState } from "react";
import type { AskResponse, ConnectionConfig, ExerciseResponse } from "@/lib/api";
import { KEYS, generateStudentId, readLocal, writeLocal } from "@/lib/storage";
import { Tabs, type TabItem } from "@/components/Tabs";
import { HealthBadge } from "@/components/HealthBadge";
import { SettingsPanel } from "@/components/SettingsPanel";
import { AskPanel } from "@/components/panels/AskPanel";
import { ReexplainPanel } from "@/components/panels/ReexplainPanel";
import { ExercisePanel } from "@/components/panels/ExercisePanel";
import { GradePanel } from "@/components/panels/GradePanel";
import { HistoryPanel } from "@/components/panels/HistoryPanel";

const TABS: TabItem[] = [
  { id: "ask", label: "Ask" },
  { id: "reexplain", label: "Re-explain" },
  { id: "exercise", label: "Exercise" },
  { id: "grade", label: "Grade" },
  { id: "history", label: "History" },
];

export default function Home() {
  const [ready, setReady] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [active, setActive] = useState("ask");

  // Cross-tab state lifted to the page so panels can share the last answer
  // and the last exercise (Grade links to it).
  const [lastAnswer, setLastAnswer] = useState<AskResponse | null>(null);
  const [lastExercise, setLastExercise] = useState<ExerciseResponse | null>(null);

  // Hydrate identity + connection overrides from localStorage on first mount,
  // generating a fresh student id when none exists yet.
  useEffect(() => {
    let id = readLocal(KEYS.studentId);
    if (!id) {
      id = generateStudentId();
      writeLocal(KEYS.studentId, id);
    }
    setStudentId(id);
    setBaseUrl(readLocal(KEYS.baseUrl));
    setApiKey(readLocal(KEYS.apiKey));
    setReady(true);
  }, []);

  const config: ConnectionConfig = useMemo(
    () => ({ baseUrl: baseUrl || undefined, apiKey: apiKey || undefined }),
    [baseUrl, apiKey],
  );

  function saveSettings(next: { studentId: string; baseUrl: string; apiKey: string }) {
    setStudentId(next.studentId);
    setBaseUrl(next.baseUrl);
    setApiKey(next.apiKey);
    writeLocal(KEYS.studentId, next.studentId);
    writeLocal(KEYS.baseUrl, next.baseUrl);
    writeLocal(KEYS.apiKey, next.apiKey);
  }

  if (!ready) {
    return <div className="min-h-screen bg-zinc-50" />;
  }

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
              G
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-zinc-900">Grounded Tutor</p>
              <p className="text-xs text-zinc-400">Answers only from your course</p>
            </div>
          </div>
          <HealthBadge config={config} />
        </div>
      </header>

      <main className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-6">
        <SettingsPanel
          studentId={studentId}
          baseUrl={baseUrl}
          apiKey={apiKey}
          onSave={saveSettings}
        />

        <Tabs tabs={TABS} active={active} onChange={setActive} />

        <div className="animate-fade-in">
          {active === "ask" && (
            <AskPanel
              studentId={studentId}
              config={config}
              lastAnswer={lastAnswer}
              setLastAnswer={setLastAnswer}
            />
          )}
          {active === "reexplain" && (
            <ReexplainPanel studentId={studentId} config={config} lastAnswer={lastAnswer} />
          )}
          {active === "exercise" && (
            <ExercisePanel
              studentId={studentId}
              config={config}
              lastExercise={lastExercise}
              setLastExercise={setLastExercise}
            />
          )}
          {active === "grade" && (
            <GradePanel studentId={studentId} config={config} lastExercise={lastExercise} />
          )}
          {active === "history" && (
            <HistoryPanel
              studentId={studentId}
              config={config}
              active={active === "history"}
            />
          )}
        </div>

        <footer className="pt-2 text-center text-xs text-zinc-400">
          Grounded retrieval · citations by construction · honest refusals
        </footer>
      </main>
    </div>
  );
}
