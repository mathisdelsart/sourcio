"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ApiError,
  clearHistory,
  getExerciseReview,
  getQuizReview,
  getSessionMessages,
  history,
  type ConnectionConfig,
  type ExerciseReview,
  type HistoryItem,
  type QuizReview,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { RefreshButton } from "@/components/RefreshButton";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT, type Locale, type TranslationKey } from "@/lib/i18n";
import { cn } from "@/lib/cn";

/** The translate function returned by ``useT`` (i18n exposes no named type). */
type TFunction = (key: TranslationKey, vars?: Record<string, string | number>) => string;

interface HistoryPanelProps {
  studentId: string;
  config: ConnectionConfig;
  active: boolean;
  /** Active thread id, or null for the unthreaded flat history. */
  activeSessionId: number | null;
}

function formatTime(iso: string, locale: Locale): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Clamp a score to 0..100 for the progress meter (mirrors the tutor panels). */
function clampScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function scoreTone(score: number): string {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

/** The kinds of activity the feed can render, derived from a message role. */
type TurnKind = "user" | "tutor" | "exercise" | "quiz";

/** Classify a persisted role into an activity kind. Unknown roles read as tutor. */
function turnKind(role: string): TurnKind {
  switch (role.toLowerCase()) {
    case "user":
      return "user";
    case "exercise":
      return "exercise";
    case "quiz":
      return "quiz";
    default:
      return "tutor";
  }
}

/** A read-only score meter reused from the tutor panels' grading markup. */
function ScoreMeter({ score, t }: { score: number; t: TFunction }) {
  const clamped = clampScore(score);
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
          {t("history.review.score")}
        </span>
        <span className="text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
          {clamped}/100
        </span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div
          className={cn("h-full rounded-full transition-all", scoreTone(clamped))}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

/** A titled, read-only block of Markdown (problem / reference solution / feedback). */
function ReviewSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
        {label}
      </p>
      {children}
    </div>
  );
}

/** The student's answer, rendered as plain read-only text (never an input). */
function AnswerText({ answer, t }: { answer: string | null; t: TFunction }) {
  return (
    <ReviewSection label={t("history.review.yourAnswer")}>
      {answer && answer.trim() ? (
        <p className="whitespace-pre-wrap text-sm text-zinc-700 dark:text-zinc-300">{answer}</p>
      ) : (
        <p className="text-sm italic text-zinc-400 dark:text-zinc-500">
          {t("history.review.notAnswered")}
        </p>
      )}
    </ReviewSection>
  );
}

/** Render a fetched exercise review read-only: problem, solution, grade. */
function ExerciseReviewView({ review, t }: { review: ExerciseReview; t: TFunction }) {
  return (
    <div className="space-y-4">
      <ReviewSection label={t("history.review.problem")}>
        <Markdown>{review.problem}</Markdown>
      </ReviewSection>
      <ReviewSection label={t("history.review.referenceSolution")}>
        <Markdown>{review.reference_solution}</Markdown>
      </ReviewSection>
      {review.grade ? (
        <div className="space-y-3 border-t border-zinc-100 pt-3 dark:border-zinc-800">
          <AnswerText answer={review.grade.answer} t={t} />
          <ScoreMeter score={review.grade.score} t={t} />
          <ReviewSection label={t("history.review.feedback")}>
            <Markdown>{review.grade.feedback}</Markdown>
          </ReviewSection>
        </div>
      ) : (
        <p className="border-t border-zinc-100 pt-3 text-sm italic text-zinc-400 dark:border-zinc-800 dark:text-zinc-500">
          {t("history.review.notGraded")}
        </p>
      )}
    </div>
  );
}

/** Render a fetched quiz review read-only: each question, solution, grade. */
function QuizReviewView({ review, t }: { review: QuizReview; t: TFunction }) {
  return (
    <div className="space-y-4">
      {review.questions.map((q, i) => (
        <div
          key={q.position}
          className="space-y-3 rounded-lg border border-zinc-100 bg-white/60 p-3 dark:border-zinc-800 dark:bg-zinc-900/40"
        >
          <ReviewSection label={`${t("history.review.question")} ${i + 1}`}>
            <Markdown>{q.problem}</Markdown>
          </ReviewSection>
          <ReviewSection label={t("history.review.referenceSolution")}>
            <Markdown>{q.reference_solution}</Markdown>
          </ReviewSection>
          <AnswerText answer={q.answer} t={t} />
          {q.score != null && <ScoreMeter score={q.score} t={t} />}
          {q.feedback && (
            <ReviewSection label={t("history.review.feedback")}>
              <Markdown>{q.feedback}</Markdown>
            </ReviewSection>
          )}
        </div>
      ))}
    </div>
  );
}

interface HistoryTurnProps {
  turn: HistoryItem;
  studentId: string;
  config: ConnectionConfig;
  t: TFunction;
  locale: Locale;
}

/** One feed entry: a chat bubble for Q&A, or an expandable card for activity. */
function HistoryTurn({ turn, studentId, config, t, locale }: HistoryTurnProps) {
  const kind = turnKind(turn.role);
  const isConversation = kind === "user" || kind === "tutor";
  const isActivity = kind === "exercise" || kind === "quiz";
  // An activity turn is reviewable only when it carries the id of its persisted
  // exercise/quiz (older turns recorded before ref_id existed stay non-clickable).
  const canReview = isActivity && turn.ref_id != null;

  const [open, setOpen] = useState(false);
  const [exReview, setExReview] = useState<ExerciseReview | null>(null);
  const [quizReview, setQuizReview] = useState<QuizReview | null>(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function toggle() {
    const next = !open;
    setOpen(next);
    // Fetch the full item once, on first expand.
    if (next && canReview && !exReview && !quizReview && !loading) {
      setLoading(true);
      setFailed(false);
      try {
        if (kind === "exercise") {
          setExReview(await getExerciseReview(turn.ref_id as number, studentId, config));
        } else {
          setQuizReview(await getQuizReview(turn.ref_id as number, studentId, config));
        }
      } catch {
        setFailed(true);
      } finally {
        setLoading(false);
      }
    }
  }

  const badge =
    kind === "exercise"
      ? { label: t("history.kind.exercise"), icon: "✎" }
      : kind === "quiz"
        ? { label: t("history.kind.quiz"), icon: "✓" }
        : null;

  return (
    <li className={cn("flex flex-col gap-1", kind === "user" ? "items-end" : "items-start")}>
      <div className="flex items-center gap-2 text-xs text-zinc-400 dark:text-zinc-500">
        {badge ? (
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide",
              kind === "exercise"
                ? "bg-amber-100 text-amber-700 dark:bg-amber-500/15 dark:text-amber-300"
                : "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300",
            )}
          >
            <span aria-hidden>{badge.icon}</span>
            {badge.label}
          </span>
        ) : (
          <span className="font-medium text-zinc-500 dark:text-zinc-400">
            {kind === "user" ? t("role.you") : t("role.tutor")}
          </span>
        )}
        {turn.created_at && <span>· {formatTime(turn.created_at, locale)}</span>}
      </div>

      {canReview ? (
        <div
          className={cn(
            "w-full rounded-xl border",
            kind === "exercise"
              ? "border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/5"
              : "border-violet-200 bg-violet-50/60 dark:border-violet-500/30 dark:bg-violet-500/5",
          )}
        >
          <button
            type="button"
            onClick={toggle}
            aria-expanded={open}
            className="flex w-full items-start gap-3 rounded-xl px-4 py-3 text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
          >
            <div className="min-w-0 flex-1">
              <Markdown>{turn.content}</Markdown>
            </div>
            <span className="shrink-0 pt-0.5 text-xs font-medium text-zinc-500 dark:text-zinc-400">
              {open ? t("history.review.hide") : t("history.review.show")}
            </span>
            <span
              aria-hidden
              className={cn(
                "shrink-0 pt-0.5 text-zinc-400 transition-transform dark:text-zinc-500",
                open && "rotate-180",
              )}
            >
              ▾
            </span>
          </button>
          {open && (
            <div className="border-t border-black/5 px-4 py-4 dark:border-white/10">
              {loading ? (
                <Skeleton lines={4} />
              ) : failed ? (
                <p className="text-sm text-red-600 dark:text-red-400">
                  {t("history.review.loadFailed")}
                </p>
              ) : exReview ? (
                <ExerciseReviewView review={exReview} t={t} />
              ) : quizReview ? (
                <QuizReviewView review={quizReview} t={t} />
              ) : null}
            </div>
          )}
        </div>
      ) : (
        <div
          className={cn(
            "rounded-xl border px-4 py-3",
            isConversation ? "max-w-[85%]" : "w-full",
            kind === "user" &&
              "border-brand-100 bg-brand-50/70 dark:border-brand-500/30 dark:bg-brand-500/10",
            kind === "tutor" &&
              "border-zinc-200 bg-white dark:border-zinc-700 dark:bg-zinc-800/60",
            kind === "exercise" &&
              "border-amber-200 bg-amber-50/60 dark:border-amber-500/30 dark:bg-amber-500/5",
            kind === "quiz" &&
              "border-violet-200 bg-violet-50/60 dark:border-violet-500/30 dark:bg-violet-500/5",
          )}
        >
          <Markdown>{turn.content}</Markdown>
        </div>
      )}
    </li>
  );
}

export function HistoryPanel({ studentId, config, active, activeSessionId }: HistoryPanelProps) {
  const toast = useToast();
  const { t, locale } = useT();
  const [messages, setMessages] = useState<HistoryItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const [clearing, setClearing] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    // Drop any previously loaded turns up front so a failed or empty load can
    // never leave a different thread's content on screen.
    setMessages([]);
    try {
      // With an active thread, show only that thread's turns; otherwise show the
      // unthreaded flat history.
      const rows =
        activeSessionId != null
          ? await getSessionMessages(studentId, activeSessionId, config)
          : await history(studentId, 100, config);
      setMessages(rows);
    } catch (err) {
      // A 404 (e.g. a stale/empty thread id after a DB reset) is not an error:
      // treat it as an empty thread and let the empty state render.
      if (err instanceof ApiError && err.status === 404) {
        setMessages([]);
      } else {
        toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
      }
    } finally {
      setLoading(false);
    }
  }, [studentId, config, activeSessionId, toast, t]);

  // Reload when the tab becomes active or the selected thread changes.
  useEffect(() => {
    if (active) {
      load();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, activeSessionId]);

  async function onClear() {
    setConfirmClear(false);
    setClearing(true);
    try {
      await clearHistory(studentId, activeSessionId, config);
      setMessages([]);
      toast.push(t("history.cleared"), "success");
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("history.clearFailed"), "error");
    } finally {
      setClearing(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title={t("history.title")}
        description={t("history.description")}
        action={
          <div className="flex items-center gap-2">
            {confirmClear ? (
              <>
                <button
                  type="button"
                  onClick={onClear}
                  className="rounded-lg bg-red-600 px-3 py-1.5 text-xs font-semibold text-white transition-colors hover:bg-red-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500"
                >
                  {t("history.clear.yes")}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmClear(false)}
                  className="text-xs font-medium text-zinc-500 transition-colors hover:text-zinc-800 dark:hover:text-zinc-200"
                >
                  {t("common.cancel")}
                </button>
              </>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmClear(true)}
                disabled={clearing || messages.length === 0}
                className="rounded-lg border border-zinc-200 px-3 py-1.5 text-xs font-medium text-zinc-500 transition-colors hover:border-red-300 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 disabled:opacity-50 dark:border-zinc-700"
              >
                {t("history.clear")}
              </button>
            )}
            <RefreshButton onRefresh={load} label={t("history.refresh")} size="sm" />
          </div>
        }
      />
      <CardBody>
        {loading && messages.length === 0 ? (
          <Skeleton lines={5} />
        ) : messages.length === 0 ? (
          <EmptyState
            title={t("history.empty.title")}
            description={t("history.empty.description")}
          />
        ) : (
          <ol className="space-y-4">
            {messages.map((turn, i) => (
              <HistoryTurn
                key={`${turn.created_at}-${turn.role}-${i}`}
                turn={turn}
                studentId={studentId}
                config={config}
                t={t}
                locale={locale}
              />
            ))}
          </ol>
        )}
      </CardBody>
    </Card>
  );
}
