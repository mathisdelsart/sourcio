"use client";

import { useEffect, useMemo, useState } from "react";
import type { AskResponse, ConnectionConfig, ExerciseResponse } from "@/lib/api";
import { KEYS, generateStudentId, readLocal, writeLocal } from "@/lib/storage";
import { Tabs, type TabItem } from "@/components/Tabs";
import { HealthBadge } from "@/components/HealthBadge";
import { AuthMenu } from "@/components/AuthMenu";
import { ThemeToggle } from "@/components/ThemeToggle";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { Features } from "@/components/Features";
import { LandingCta } from "@/components/LandingCta";
import { SettingsPanel } from "@/components/SettingsPanel";
import { AskPanel } from "@/components/panels/AskPanel";
import { ReexplainPanel } from "@/components/panels/ReexplainPanel";
import { ExercisePanel } from "@/components/panels/ExercisePanel";
import { GradePanel } from "@/components/panels/GradePanel";
import { QuizPanel } from "@/components/panels/QuizPanel";
import { ThreadsPanel } from "@/components/panels/ThreadsPanel";
import { HistoryPanel } from "@/components/panels/HistoryPanel";
import { ReviewPanel } from "@/components/panels/ReviewPanel";

export default function Home() {
  const { t } = useT();
  const TABS: TabItem[] = [
    { id: "ask", label: t("tabs.ask") },
    { id: "reexplain", label: t("tabs.reexplain") },
    { id: "exercise", label: t("tabs.exercise") },
    { id: "grade", label: t("tabs.grade") },
    { id: "quiz", label: t("tabs.quiz") },
    { id: "threads", label: t("tabs.threads") },
    { id: "history", label: t("tabs.history") },
    { id: "review", label: t("tabs.review") },
  ];

  const [ready, setReady] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [token, setToken] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [active, setActive] = useState("ask");

  // Cross-tab state lifted to the page so panels can share the last answer
  // and the last exercise (Grade links to it).
  const [lastAnswer, setLastAnswer] = useState<AskResponse | null>(null);
  const [lastExercise, setLastExercise] = useState<ExerciseResponse | null>(null);
  // Active conversation thread shared between the Ask and Threads tabs.
  // null means "All history (unthreaded)" — no session_id is sent.
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);

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
    setToken(readLocal(KEYS.authToken));
    setAuthEmail(readLocal(KEYS.authEmail));
    const storedSession = readLocal(KEYS.sessionId);
    const parsedSession = storedSession ? Number(storedSession) : NaN;
    setActiveSessionId(Number.isInteger(parsedSession) ? parsedSession : null);
    setReady(true);
  }, []);

  // Persist the active thread selection so it survives reloads.
  function selectSession(id: number | null) {
    setActiveSessionId(id);
    writeLocal(KEYS.sessionId, id == null ? "" : String(id));
  }

  const config: ConnectionConfig = useMemo(
    () => ({
      baseUrl: baseUrl || undefined,
      apiKey: apiKey || undefined,
      token: token || undefined,
    }),
    [baseUrl, apiKey, token],
  );

  function onLogin(nextToken: string, nextEmail: string) {
    setToken(nextToken);
    setAuthEmail(nextEmail);
    writeLocal(KEYS.authToken, nextToken);
    writeLocal(KEYS.authEmail, nextEmail);
  }

  function onLogout() {
    setToken("");
    setAuthEmail("");
    writeLocal(KEYS.authToken, "");
    writeLocal(KEYS.authEmail, "");
  }

  function saveSettings(next: { studentId: string; baseUrl: string; apiKey: string }) {
    setStudentId(next.studentId);
    setBaseUrl(next.baseUrl);
    setApiKey(next.apiKey);
    writeLocal(KEYS.studentId, next.studentId);
    writeLocal(KEYS.baseUrl, next.baseUrl);
    writeLocal(KEYS.apiKey, next.apiKey);
  }

  if (!ready) {
    return <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950" />;
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/80 backdrop-blur dark:border-zinc-800 dark:bg-zinc-950/80">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">
              G
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {t("app.name")}
              </p>
              <p className="text-xs text-zinc-500 dark:text-zinc-400">
                {t("app.tagline")}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <span className="hidden sm:inline-flex">
              <HealthBadge config={config} />
            </span>
            <AuthMenu
              config={config}
              email={authEmail || null}
              onLogin={onLogin}
              onLogout={onLogout}
            />
            <LanguageToggle />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main>
        {/* Landing — wider container, generous spacing, leads into the tool. */}
        <div className="mx-auto max-w-5xl space-y-16 px-4 py-16 sm:px-6 sm:py-20">
          <Hero targetId="tool" />
          <HowItWorks />
          <Features />
          <LandingCta targetId="tool" />
        </div>

        {/* Tool — the existing tutor, anchored so the hero CTA scrolls here. */}
        <section
          id="tool"
          aria-label={t("tabs.aria")}
          className="scroll-mt-20 border-t border-zinc-200 bg-zinc-50 dark:border-zinc-800 dark:bg-zinc-950"
        >
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-16 sm:px-6 sm:py-20">
            <div className="flex justify-center sm:hidden">
              <HealthBadge config={config} />
            </div>

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
              sessionId={activeSessionId}
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
          {active === "quiz" && <QuizPanel studentId={studentId} config={config} />}
          {active === "threads" && (
            <ThreadsPanel
              studentId={studentId}
              config={config}
              active={active === "threads"}
              activeSessionId={activeSessionId}
              setActiveSessionId={selectSession}
            />
          )}
          {active === "history" && (
            <HistoryPanel
              studentId={studentId}
              config={config}
              active={active === "history"}
            />
          )}
          {active === "review" && (
            <ReviewPanel
              studentId={studentId}
              config={config}
              active={active === "review"}
            />
          )}
            </div>
          </div>
        </section>

        <footer className="border-t border-zinc-200 dark:border-zinc-800">
          <div className="mx-auto flex max-w-5xl flex-col items-center gap-2 px-4 py-8 text-center sm:px-6">
            <div className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-indigo-600 text-xs font-bold text-white">
                G
              </span>
              <span className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                {t("app.name")}
              </span>
              <span className="text-xs text-zinc-400 dark:text-zinc-500">grounded-rag</span>
            </div>
            <p className="max-w-md text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
              {t("landing.footer.tagline")}
            </p>
            <p className="text-xs text-zinc-500 dark:text-zinc-400">{t("footer.tagline")}</p>
          </div>
        </footer>
      </main>
    </div>
  );
}
