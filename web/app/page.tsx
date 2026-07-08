"use client";

import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { me, type AskResponse, type ConnectionConfig } from "@/lib/api";
import { KEYS, generateStudentId, readLocal, writeLocal } from "@/lib/storage";
import { Tabs, type TabItem } from "@/components/Tabs";
import { HealthBadge } from "@/components/HealthBadge";
import { AuthMenu } from "@/components/AuthMenu";
import { AuthCard } from "@/components/AuthCard";
import { Button } from "@/components/Button";
import { BrandMark } from "@/components/Logo";
import { LanguageToggle } from "@/components/LanguageToggle";
import { useT } from "@/lib/i18n";
import { useCourses } from "@/lib/useCourses";
import { scrollToId } from "@/lib/scroll";
import { Hero } from "@/components/Hero";
import { HowItWorks } from "@/components/HowItWorks";
import { Features } from "@/components/Features";
import { StatsBand } from "@/components/StatsBand";
import { LandingCta } from "@/components/LandingCta";
import { Reveal } from "@/components/Reveal";
import { DEFAULT_SOURCES_MAX, SOURCES_MAX_MAX, SOURCES_MAX_MIN } from "@/components/SettingsPanel";
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
  // The visitor's own OpenAI key. When set it is sent on every request so all
  // LLM calls use their premium OpenAI model instead of the free one. Kept in the
  // browser (localStorage) only; shared with the Documents upload card and the
  // account menu via the same storage key.
  const [openaiKey, setOpenaiKey] = useState("");
  // Max candidate-source pool (`k`) for Ask; configurable in Settings.
  const [sourcesMax, setSourcesMax] = useState(DEFAULT_SOURCES_MAX);
  const [token, setToken] = useState("");
  const [authUsername, setAuthUsername] = useState("");
  const [active, setActive] = useState("ask");
  // Opens the shared sign-in / register card as a centered modal from the
  // locked tool area (the header AuthMenu owns its own separate modal).
  const [authModalOpen, setAuthModalOpen] = useState(false);
  // The signed-in user's id, used to derive an account-scoped student id so two
  // accounts on one browser never share data. Resolved whenever a token exists,
  // so being logged in always isolates the view.
  const [authUserId, setAuthUserId] = useState<number | null>(null);
  // True while a stored token is being resolved to a user (the `me()` call is in
  // flight). The tool's data render is gated behind this so the first requests
  // never fire on the device id and then flip to the account-scoped id.
  const [authResolving, setAuthResolving] = useState(false);

  // Cross-tab state lifted to the page so the Ask and Re-explain flows can share
  // the last answer. The Exercise panel owns its own exercise/grade state.
  const [lastAnswer, setLastAnswer] = useState<AskResponse | null>(null);
  // Active conversation thread shared between the Ask and Threads tabs.
  // null means "All history (unthreaded)" — no session_id is sent.
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  // Bumped whenever a document upload indexes new material, so every course
  // selector (Ask/Exercise/Quiz) re-fetches GET /courses and shows the new
  // course without a manual page refresh.
  const [coursesRefreshKey, setCoursesRefreshKey] = useState(0);

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
    setOpenaiKey(readLocal(KEYS.openaiKey));
    const storedToken = readLocal(KEYS.authToken);
    setToken(storedToken);
    setAuthUsername(readLocal(KEYS.authUsername));
    // A stored token must resolve before the tool renders any data, so start in
    // the resolving state when one is present (cleared by the me() effect).
    if (storedToken) setAuthResolving(true);
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
      openaiKey: openaiKey || undefined,
    }),
    [baseUrl, apiKey, token, openaiKey],
  );

  // Update the visitor's own OpenAI key (from the account menu or the Documents
  // upload card) and persist it so it survives reloads and stays in sync across
  // both places. Trimmed on write so a blank value clears it.
  function updateOpenaiKey(next: string) {
    const trimmed = next.trim();
    setOpenaiKey(trimmed);
    writeLocal(KEYS.openaiKey, trimmed);
  }

  // Resolve the signed-in user's id whenever a token exists, so being logged in
  // always isolates the view. The resolved
  // username is refreshed from the canonical `me()` response. A stored token
  // that no longer resolves is treated as logged-out (cleared) rather than
  // silently falling back to the device id.
  useEffect(() => {
    if (!token) {
      setAuthUserId(null);
      setAuthResolving(false);
      return;
    }
    let cancelled = false;
    setAuthResolving(true);
    me({ ...config, token })
      .then((user) => {
        if (cancelled) return;
        setAuthUserId(user.id);
        setAuthUsername(user.username);
        writeLocal(KEYS.authUsername, user.username);
        setAuthResolving(false);
      })
      .catch(() => {
        if (cancelled) return;
        // Stored token is stale/invalid: revert to the anonymous device flow.
        onLogout();
        setAuthResolving(false);
      });
    return () => {
      cancelled = true;
    };
    // `config` is derived from token/baseUrl/apiKey; re-run when those change.
    // `onLogout` is a stable in-component callback, deliberately not a dep.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, config]);

  // The student id the tool actually uses. Once logged in it is scoped to the
  // account ("u<id>") so the same account is consistent across devices and two
  // accounts on one browser never collide; logged out, the device id is kept
  // exactly as before.
  const effectiveStudentId = authUserId != null ? `u${authUserId}` : studentId;

  // Single source of truth for the user's indexed courses. Fetched once here and
  // fed to every course selector (so the list is not fetched once per panel) and
  // used to gate the Ask/Exercise/Quiz tools: with nothing indexed, grounding is
  // impossible, so those tools show an import call-to-action instead of a form.
  // Re-fetches on account switch (effectiveStudentId) and after an upload.
  const {
    courses,
    loading: coursesLoading,
    error: coursesError,
  } = useCourses(config, effectiveStudentId, coursesRefreshKey);
  const goToDocuments = () => setActive("documents");

  // Close the sign-in modal on Escape so keyboard users are never stranded.
  useEffect(() => {
    if (!authModalOpen) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setAuthModalOpen(false);
    }
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [authModalOpen]);

  function onLogin(nextToken: string, nextUsername: string) {
    setToken(nextToken);
    setAuthUsername(nextUsername);
    writeLocal(KEYS.authToken, nextToken);
    writeLocal(KEYS.authUsername, nextUsername);
  }

  function onLogout() {
    setToken("");
    setAuthUsername("");
    writeLocal(KEYS.authToken, "");
    writeLocal(KEYS.authUsername, "");
    // Clear the visitor's own OpenAI key on sign-out so their paid credential
    // never lingers in this browser for the next person on a shared machine to
    // read from storage and spend against.
    updateOpenaiKey("");
    // Drop the active thread so a stale account thread id never lingers into the
    // anonymous (device-scoped) view after signing out.
    selectSession(null);
  }

  // Update the max candidate-source ceiling (surfaced on the Ask panel).
  // Clamped to a sane range and persisted so it survives reloads.
  function updateSourcesMax(next: number) {
    const clamped = Math.min(SOURCES_MAX_MAX, Math.max(SOURCES_MAX_MIN, next));
    setSourcesMax(clamped);
    writeLocal(KEYS.sourcesMax, String(clamped));
  }

  if (!ready) {
    return <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950" />;
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
          {/* When a personal OpenAI key is set, show a discreet badge so it is
              obvious the free model is replaced by a premium one everywhere. */}
          {openaiKey && (
            <span
              className="hidden items-center gap-1.5 rounded-full border border-brand-200 bg-brand-50 px-3 py-1 text-xs font-semibold text-brand-700 sm:inline-flex dark:border-brand-500/30 dark:bg-brand-500/10 dark:text-brand-300"
              title={t("settings.openaiKey.badgeTitle")}
            >
              <svg
                aria-hidden
                viewBox="0 0 24 24"
                className="h-3.5 w-3.5"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />
              </svg>
              {t("settings.openaiKey.badge")}
            </span>
          )}
          <LanguageToggle />
          <AuthMenu
            config={config}
            username={authUsername || null}
            onLogin={onLogin}
            onLogout={onLogout}
            openaiKey={openaiKey}
            onOpenaiKeyChange={updateOpenaiKey}
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

              {authResolving ? (
                // A stored token is still resolving to an account. Hold the tool
                // behind a light skeleton so no request fires on the device id
                // and then flips to the account-scoped id once it resolves.
                <div className="space-y-6 p-6 sm:p-8" aria-busy="true">
                  <div className="h-10 animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-800" />
                  <div className="h-10 animate-pulse rounded-lg bg-zinc-100 dark:bg-zinc-800" />
                  <div className="h-64 animate-pulse rounded-xl bg-zinc-100 dark:bg-zinc-800" />
                </div>
              ) : !token ? (
                // The landing above stays public for visitors, but the tool
                // itself requires an account — nothing is usable without signing
                // in. This locked panel replaces the tabs with a clear sign-in
                // CTA that opens the shared login/register card.
                <div className="flex flex-col items-center justify-center px-6 py-16 text-center sm:py-24">
                  <span
                    className="flex h-14 w-14 items-center justify-center rounded-2xl bg-brand-50 text-brand-600 dark:bg-brand-500/15 dark:text-brand-300"
                    aria-hidden
                  >
                    <svg
                      viewBox="0 0 24 24"
                      className="h-7 w-7"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <rect x="4" y="11" width="16" height="10" rx="2" />
                      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
                    </svg>
                  </span>
                  <h3 className="mt-5 text-xl font-bold tracking-tight text-ink">
                    {t("toolGate.title")}
                  </h3>
                  <p className="mt-2 max-w-md text-sm leading-relaxed text-zinc-500 dark:text-zinc-400">
                    {t("toolGate.subtitle")}
                  </p>
                  <Button className="mt-6" onClick={() => setAuthModalOpen(true)}>
                    {t("toolGate.button")}
                  </Button>
                </div>
              ) : (
              <div className="space-y-6 p-6 sm:p-8">
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
                    onSourcesMaxChange={updateSourcesMax}
                    courses={courses}
                    coursesLoading={coursesLoading}
                    coursesError={coursesError}
                    onImport={goToDocuments}
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
                    courses={courses}
                    coursesLoading={coursesLoading}
                    coursesError={coursesError}
                    onImport={goToDocuments}
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
                    courses={courses}
                    coursesLoading={coursesLoading}
                    coursesError={coursesError}
                    onImport={goToDocuments}
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
                  <DocumentsPanel
                    studentId={effectiveStudentId}
                    config={config}
                    onCoursesChanged={() => setCoursesRefreshKey((k) => k + 1)}
                    openaiKey={openaiKey}
                    onOpenaiKeyChange={updateOpenaiKey}
                  />
                </div>
              </div>
              )}
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

      {/* Sign-in / register modal opened from the locked tool CTA. Rendered
          through a portal on document.body so the sticky header's transform
          can't capture the fixed overlay. Reuses the shared AuthCard, so it
          never drifts from the header menu and the full-screen gate. */}
      {authModalOpen &&
        createPortal(
          <div
            className="animate-fade-in fixed inset-0 z-50 flex items-center justify-center bg-ink/40 px-4 backdrop-blur-sm"
            onMouseDown={(e) => {
              if (e.target === e.currentTarget) setAuthModalOpen(false);
            }}
          >
            <div role="dialog" aria-modal="true" aria-label={t("auth.aria")}>
              <AuthCard
                config={config}
                onLogin={onLogin}
                onSuccess={() => setAuthModalOpen(false)}
                onClose={() => setAuthModalOpen(false)}
              />
            </div>
          </div>,
          document.body,
        )}
    </div>
  );
}
