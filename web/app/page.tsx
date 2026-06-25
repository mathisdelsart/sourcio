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
import { scrollToId } from "@/lib/scroll";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { Features } from "@/components/Features";
import { StatsBand } from "@/components/StatsBand";
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
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-sm font-bold text-white dark:bg-white dark:text-ink">
              G
            </div>
            <div className="leading-tight">
              <p className="text-sm font-semibold text-ink dark:text-zinc-100">
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
        {/* Landing — wide, confident container with generous section padding.
            The hero leads into a full-width navy stats band, then the rest of
            the landing resumes inside the centered column. */}
        <div className="mx-auto max-w-6xl px-4 pt-20 sm:px-6 sm:pt-28">
          <Hero targetId="tool" />
        </div>

        <div className="mt-20 sm:mt-28">
          <StatsBand />
        </div>

        <div className="mx-auto max-w-6xl space-y-24 px-4 py-20 sm:px-6 sm:py-28">
          <HowItWorks />
          <Features />
          <LandingCta targetId="tool" />
        </div>

        {/* Tool — the existing tutor, anchored so the hero CTA scrolls here.
            Wrapped in a subtle app-window frame so it reads as "the product". */}
        <section
          id="tool"
          aria-label={t("tabs.aria")}
          className="scroll-mt-20 border-t border-zinc-200 bg-[#f6f6f3] dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6 sm:py-28">
            <div className="flex justify-center sm:hidden">
              <HealthBadge config={config} />
            </div>

            {/* App window: browser chrome (dots + URL pill) + framed body, so the
                tool reads as a live product demo. */}
            <div className="mt-2 overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-card dark:border-zinc-800 dark:bg-zinc-950">
              <div className="flex items-center gap-3 border-b border-zinc-200 bg-zinc-50/80 px-4 py-3 dark:border-zinc-800 dark:bg-zinc-900/60">
                <div className="flex items-center gap-1.5" aria-hidden>
                  <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
                  <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
                  <span className="h-2.5 w-2.5 rounded-full bg-zinc-300 dark:bg-zinc-600" />
                </div>
                <span className="mx-auto flex max-w-[18rem] flex-1 items-center justify-center gap-1.5 truncate rounded-md border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-zinc-500 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-400">
                  <svg
                    aria-hidden
                    viewBox="0 0 24 24"
                    className="h-3 w-3 shrink-0"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <rect x="5" y="11" width="14" height="9" rx="2" />
                    <path d="M8 11V8a4 4 0 0 1 8 0v3" />
                  </svg>
                  localhost:3000
                </span>
                {/* Spacer balances the traffic-light dots so the pill stays centered. */}
                <span aria-hidden className="w-[42px]" />
              </div>

              <div className="space-y-6 p-6 sm:p-8">
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
            </div>
          </div>
        </section>

        <footer className="bg-navy text-zinc-300">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-12 sm:grid-cols-2 sm:px-6 lg:grid-cols-3">
            {/* Brand mark + tagline. */}
            <div className="lg:col-span-2 lg:max-w-md">
              <div className="flex items-center gap-2">
                <span className="flex h-7 w-7 items-center justify-center rounded-md bg-white text-xs font-bold text-ink">
                  G
                </span>
                <span className="text-sm font-semibold text-white">{t("app.name")}</span>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-zinc-400">
                {t("landing.footer.tagline")}
              </p>
            </div>

            {/* Section links — smooth-scroll to the page sections / tool. */}
            <nav aria-label={t("footer.explore")}>
              <p className="text-xs font-semibold uppercase tracking-wider text-zinc-500">
                {t("footer.explore")}
              </p>
              <ul className="mt-4 space-y-2.5 text-sm">
                {(
                  [
                    ["how", "footer.link.how"],
                    ["features", "footer.link.features"],
                    ["tool", "footer.link.tool"],
                  ] as const
                ).map(([target, key]) => (
                  <li key={target}>
                    <button
                      type="button"
                      onClick={() => scrollToId(target)}
                      className="rounded text-zinc-400 transition-colors hover:text-white focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 focus-visible:ring-offset-2 focus-visible:ring-offset-navy"
                    >
                      {t(key)}
                    </button>
                  </li>
                ))}
              </ul>
            </nav>
          </div>

          <div className="border-t border-white/10">
            <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-5 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <p>{t("footer.tagline")}</p>
              <p>{t("footer.credit")}</p>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
