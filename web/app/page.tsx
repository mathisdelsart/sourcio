"use client";

import { useEffect, useMemo, useState } from "react";
import { getConfig, me, type AskResponse, type ConnectionConfig } from "@/lib/api";
import { KEYS, generateStudentId, readLocal, writeLocal } from "@/lib/storage";
import { Tabs, type TabItem } from "@/components/Tabs";
import { HealthBadge } from "@/components/HealthBadge";
import { AuthMenu } from "@/components/AuthMenu";
import { AuthGate } from "@/components/AuthGate";
import { BrandMark } from "@/components/Logo";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";
import { scrollToId } from "@/lib/scroll";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { Features } from "@/components/Features";
import { StatsBand } from "@/components/StatsBand";
import { LandingCta } from "@/components/LandingCta";
import { Reveal } from "@/components/Reveal";
import { SettingsPanel, DEFAULT_SOURCES_MAX } from "@/components/SettingsPanel";
import { ThreadSelect } from "@/components/ThreadSelect";
import { AskPanel } from "@/components/panels/AskPanel";
import { ExercisePanel } from "@/components/panels/ExercisePanel";
import { QuizPanel } from "@/components/panels/QuizPanel";
import { ThreadsPanel } from "@/components/panels/ThreadsPanel";
import { HistoryPanel } from "@/components/panels/HistoryPanel";
import { DocumentsPanel } from "@/components/panels/DocumentsPanel";

export default function Home() {
  const { t } = useT();
  const TABS: TabItem[] = [
    { id: "ask", label: t("tabs.ask") },
    { id: "exercise", label: t("tabs.exercise") },
    { id: "quiz", label: t("tabs.quiz") },
    { id: "threads", label: t("tabs.threads") },
    { id: "history", label: t("tabs.history") },
    { id: "documents", label: t("tabs.documents") },
  ];

  const [ready, setReady] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  // Max candidate-source pool (`k`) for Ask; configurable in Settings.
  const [sourcesMax, setSourcesMax] = useState(DEFAULT_SOURCES_MAX);
  const [token, setToken] = useState("");
  const [authEmail, setAuthEmail] = useState("");
  const [active, setActive] = useState("ask");
  // Enforced multi-user mode, learned from GET /config. When true and the user
  // is not signed in, a blocking login gate replaces the app. Defaults to false
  // so an unreachable backend never locks the anonymous MVP flow.
  const [requireAuth, setRequireAuth] = useState(false);
  // The signed-in user's id, used to derive an account-scoped student id in
  // enforced mode so two accounts on one browser never share data.
  const [authUserId, setAuthUserId] = useState<number | null>(null);

  // Cross-tab state lifted to the page so the Ask and Re-explain flows can share
  // the last answer. The Exercise panel owns its own exercise/grade state.
  const [lastAnswer, setLastAnswer] = useState<AskResponse | null>(null);
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
    const storedSources = Number.parseInt(readLocal(KEYS.sourcesMax), 10);
    if (Number.isFinite(storedSources)) setSourcesMax(storedSources);
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

  // Learn whether the backend enforces authentication (once ready, and whenever
  // the connection target changes). getConfig swallows errors and returns
  // require_auth:false, so a down backend keeps the anonymous flow usable.
  useEffect(() => {
    if (!ready) return;
    let cancelled = false;
    getConfig({ baseUrl: baseUrl || undefined, apiKey: apiKey || undefined })
      .then((cfg) => {
        if (!cancelled) setRequireAuth(cfg.require_auth);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [ready, baseUrl, apiKey]);

  // In enforced mode, resolve the signed-in user's id so the student id can be
  // scoped to the account. Cleared when signed out or when enforcement is off.
  useEffect(() => {
    if (!requireAuth || !token) {
      setAuthUserId(null);
      return;
    }
    let cancelled = false;
    me({ ...config, token })
      .then((user) => {
        if (!cancelled) setAuthUserId(user.id);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
    // `config` is derived from token/baseUrl/apiKey; re-run when those change.
  }, [requireAuth, token, config]);

  // The student id the tool actually uses. In enforced mode it is scoped to the
  // account ("u<id>") so the same account is consistent across devices and two
  // accounts on one browser never collide; otherwise the device id is kept
  // exactly as before.
  const effectiveStudentId =
    requireAuth && authUserId != null ? `u${authUserId}` : studentId;

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

  function saveSettings(next: {
    studentId: string;
    baseUrl: string;
    apiKey: string;
    sourcesMax: number;
  }) {
    setStudentId(next.studentId);
    setBaseUrl(next.baseUrl);
    setApiKey(next.apiKey);
    setSourcesMax(next.sourcesMax);
    writeLocal(KEYS.studentId, next.studentId);
    writeLocal(KEYS.baseUrl, next.baseUrl);
    writeLocal(KEYS.apiKey, next.apiKey);
    writeLocal(KEYS.sourcesMax, String(next.sourcesMax));
  }

  if (!ready) {
    return <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950" />;
  }

  // Enforced multi-user mode: block the whole app behind a sign-in gate until
  // the visitor has a token. Signing in sets `token`, which removes the gate.
  if (requireAuth && !token) {
    return <AuthGate config={config} onLogin={onLogin} />;
  }

  return (
    <div className="min-h-screen bg-zinc-50">
      <header className="sticky top-0 z-20 border-b border-zinc-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-4 py-4 sm:px-6 sm:py-5">
          <div className="flex items-center gap-3">
            <BrandMark className="h-10 w-10" />
            <div className="leading-tight">
              <p className="text-sm font-semibold text-ink">{t("app.name")}</p>
              <p className="text-xs text-zinc-500">{t("app.tagline")}</p>
            </div>
          </div>

          {/* Primary nav — smooth-scrolls to the landing sections (desktop only). */}
          <nav aria-label={t("footer.explore")} className="hidden items-center gap-8 md:flex">
            {(
              [
                ["how", "footer.link.how"],
                ["features", "footer.link.features"],
                ["tool", "footer.link.tool"],
              ] as const
            ).map(([target, key]) => (
              <button
                key={target}
                type="button"
                onClick={() => scrollToId(target)}
                className="rounded text-sm font-medium text-zinc-600 transition-colors hover:text-ink focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2"
              >
                {t(key)}
              </button>
            ))}
          </nav>

          {/* Language + sign-in are direct flex children, so `justify-between`
              spreads logo · nav · language · sign-in with equal gaps between
              each — generous breathing room on both sides of the language. */}
          <LanguageToggle />
          <AuthMenu
            config={config}
            email={authEmail || null}
            onLogin={onLogin}
            onLogout={onLogout}
          />
        </div>
      </header>

      <main>
        {/* Landing — wide, confident container. The hero leads into a full-width
            navy stats band, then the rest of the landing resumes inside the
            centered column. */}
        <div className="mx-auto max-w-6xl px-4 pt-6 sm:px-6 sm:pt-8">
          <Reveal>
            <Hero targetId="tool" />
          </Reveal>
        </div>

        <div className="mt-20 sm:mt-28">
          <Reveal>
            <StatsBand />
          </Reveal>
        </div>

        <div className="mx-auto max-w-6xl space-y-24 px-4 py-20 sm:px-6 sm:py-28">
          <HowItWorks />
          <Features />
          <Reveal>
            <LandingCta targetId="tool" />
          </Reveal>
        </div>

        {/* Tool — the existing tutor, anchored so the hero CTA scrolls here.
            Wrapped in a subtle app-window frame so it reads as "the product". */}
        <section
          id="tool"
          aria-label={t("tabs.aria")}
          className="scroll-mt-20 border-t border-zinc-200 bg-paper dark:border-zinc-800 dark:bg-zinc-900"
        >
          <div className="mx-auto max-w-4xl px-4 py-20 sm:px-6 sm:py-28">
            {/* App window: browser chrome (dots + URL pill) + framed body, so the
                tool reads as a live product demo. */}
            <div className="overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-card">
              <div className="flex items-center gap-3 border-b border-zinc-200 bg-zinc-50/80 px-4 py-3">
                <div className="flex items-center gap-1.5" aria-hidden>
                  <span className="h-3 w-3 rounded-full bg-[#ff5f57]" />
                  <span className="h-3 w-3 rounded-full bg-[#febc2e]" />
                  <span className="h-3 w-3 rounded-full bg-[#28c840]" />
                </div>
                <span className="mx-auto flex max-w-[18rem] flex-1 items-center justify-center gap-1.5 truncate rounded-md border border-zinc-200 bg-white px-3 py-1 text-[11px] font-medium text-zinc-500">
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
                  sourcio.app
                </span>
                {/* Spacer balances the traffic-light dots so the pill stays centered. */}
                <span aria-hidden className="w-[52px]" />
              </div>

              <div className="space-y-6 p-6 sm:p-8">
                <SettingsPanel
                  studentId={effectiveStudentId}
                  baseUrl={baseUrl}
                  apiKey={apiKey}
                  sourcesMax={sourcesMax}
                  onSave={saveSettings}
                />

                {/* Thread switcher in the tool frame — visible on every tab so
                    the active conversation thread can be seen and changed from
                    anywhere, sharing the page's activeSessionId/selectSession. */}
                <ThreadSelect
                  studentId={effectiveStudentId}
                  config={config}
                  value={activeSessionId}
                  onChange={selectSession}
                  onManage={() => setActive("threads")}
                />

                <Tabs tabs={TABS} active={active} onChange={setActive} />

                {/* Every panel stays mounted across tab switches so in-progress
                    work (a drafted question, a running quiz, a generated
                    exercise) survives — inactive panels are hidden with the
                    `hidden` attribute (display:none, and removed from the
                    accessibility tree, so exactly one tabpanel is exposed) rather
                    than unmounted. The fade-in is applied to the active panel
                    only, so it still replays on each switch without forcing a
                    remount that would wipe local state. */}
                <div
                  id="tabpanel-ask"
                  role="tabpanel"
                  aria-labelledby="tab-ask"
                  hidden={active !== "ask"}
                  className={active === "ask" ? "animate-fade-in" : undefined}
                >
                  <AskPanel
                    studentId={effectiveStudentId}
                    config={config}
                    lastAnswer={lastAnswer}
                    setLastAnswer={setLastAnswer}
                    sessionId={activeSessionId}
                    sourcesMax={sourcesMax}
                  />
                </div>
                <div
                  id="tabpanel-exercise"
                  role="tabpanel"
                  aria-labelledby="tab-exercise"
                  hidden={active !== "exercise"}
                  className={active === "exercise" ? "animate-fade-in" : undefined}
                >
                  <ExercisePanel
                    studentId={effectiveStudentId}
                    config={config}
                    sessionId={activeSessionId}
                  />
                </div>
                <div
                  id="tabpanel-quiz"
                  role="tabpanel"
                  aria-labelledby="tab-quiz"
                  hidden={active !== "quiz"}
                  className={active === "quiz" ? "animate-fade-in" : undefined}
                >
                  <QuizPanel
                    studentId={effectiveStudentId}
                    config={config}
                    sessionId={activeSessionId}
                  />
                </div>
                <div
                  id="tabpanel-threads"
                  role="tabpanel"
                  aria-labelledby="tab-threads"
                  hidden={active !== "threads"}
                  className={active === "threads" ? "animate-fade-in" : undefined}
                >
                  <ThreadsPanel
                    studentId={effectiveStudentId}
                    config={config}
                    active={active === "threads"}
                    activeSessionId={activeSessionId}
                    setActiveSessionId={selectSession}
                  />
                </div>
                <div
                  id="tabpanel-history"
                  role="tabpanel"
                  aria-labelledby="tab-history"
                  hidden={active !== "history"}
                  className={active === "history" ? "animate-fade-in" : undefined}
                >
                  <HistoryPanel
                    studentId={effectiveStudentId}
                    config={config}
                    active={active === "history"}
                    activeSessionId={activeSessionId}
                  />
                </div>
                <div
                  id="tabpanel-documents"
                  role="tabpanel"
                  aria-labelledby="tab-documents"
                  hidden={active !== "documents"}
                  className={active === "documents" ? "animate-fade-in" : undefined}
                >
                  <DocumentsPanel studentId={effectiveStudentId} config={config} />
                </div>
              </div>
            </div>
          </div>
        </section>

        <footer className="bg-navy text-zinc-300">
          <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-14 sm:flex-row sm:justify-between sm:px-6">
            {/* Brand mark + tagline. */}
            <div className="sm:max-w-md">
              <div className="flex items-center gap-2.5">
                <BrandMark className="h-9 w-9" />
                <span className="text-base font-semibold text-white">{t("app.name")}</span>
              </div>
              <p className="mt-4 text-sm leading-relaxed text-zinc-400">
                {t("landing.footer.tagline")}
              </p>
            </div>

            {/* Section links — smooth-scroll to the page sections / tool. Right-
                aligned so the block sits directly above the status line below. */}
            <nav aria-label={t("footer.explore")} className="sm:text-right">
              <p className="text-sm font-semibold text-white">{t("footer.explore")}</p>
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
            <div className="mx-auto flex max-w-6xl flex-col gap-3 px-4 py-5 text-xs text-zinc-500 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <p>{t("footer.credit")}</p>
              {/* Discreet backend status — to be removed once a public API is live. */}
              <HealthBadge config={config} variant="bare" />
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}
