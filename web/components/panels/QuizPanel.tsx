"use client";

import { useMemo, useState } from "react";
import {
  quiz as fetchQuiz,
  gradeQuizAnswer,
  gradeQuizAll,
  type ConnectionConfig,
  type GradeResponse,
  type QuizResponse,
  type QuizSummaryResponse,
  type Rigor,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField, TextArea } from "@/components/TextField";
import { CourseSelect } from "@/components/CourseSelect";
import { RigorSelector } from "@/components/RigorSelector";
import { Markdown } from "@/components/Markdown";
import { EmptyState, RefusalBanner } from "@/components/States";
import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { submitOnCmdEnter } from "@/lib/keys";
import { KEYS, readLocal, writeLocal } from "@/lib/storage";
import { cn } from "@/lib/cn";

interface QuizPanelProps {
  studentId: string;
  config: ConnectionConfig;
  /** Active thread id, or null; the generated quiz is filed under it. */
  sessionId: number | null;
}

/** Clamp a score to 0..100 for the progress meter. */
function clampScore(score: number): number {
  if (!Number.isFinite(score)) return 0;
  return Math.max(0, Math.min(100, Math.round(score)));
}

function scoreTone(score: number): string {
  if (score >= 70) return "bg-emerald-500";
  if (score >= 40) return "bg-amber-500";
  return "bg-red-500";
}

const COUNTS = [3, 5, 7] as const;

export function QuizPanel({ studentId, config, sessionId }: QuizPanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [notion, setNotion] = useState("");
  // Course/chapter scope retrieval so the quiz stays on the requested topic.
  // Lazy-init the course from localStorage so a choice is shared across tabs.
  const [course, setCourse] = useState(() => readLocal(KEYS.course));
  const [chapter, setChapter] = useState("");
  const [count, setCount] = useState<number>(3);
  // Marking strictness applied when correcting answers, shared with the exercise
  // grade flow. Chosen before grading so it applies to both per-question and
  // grade-all corrections.
  const [rigor, setRigor] = useState<Rigor>("standard");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QuizResponse | null>(null);

  // Per-question answer text and verdict, keyed by question id.
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [verdicts, setVerdicts] = useState<Record<number, GradeResponse>>({});
  const [grading, setGrading] = useState<Record<number, boolean>>({});

  // Whole-quiz grading: a final score plus a global recommendation.
  const [summary, setSummary] = useState<QuizSummaryResponse | null>(null);
  const [gradingAll, setGradingAll] = useState(false);

  const canGenerate = notion.trim().length > 0 && !loading;

  function selectCourse(next: string) {
    setCourse(next);
    writeLocal(KEYS.course, next);
  }

  const answeredCount = useMemo(
    () =>
      (result?.questions ?? []).filter(
        (q) => q.id != null && (answers[q.id] ?? "").trim().length > 0,
      ).length,
    [result, answers],
  );
  const hasAnyAnswer = answeredCount > 0;

  const gradedScores = useMemo(
    () => Object.values(verdicts).map((v) => clampScore(v.score)),
    [verdicts],
  );
  const total = gradedScores.length
    ? Math.round(gradedScores.reduce((a, b) => a + b, 0) / gradedScores.length)
    : null;

  async function generate() {
    if (!canGenerate) return;
    setLoading(true);
    setResult(null);
    setAnswers({});
    setVerdicts({});
    setGrading({});
    setSummary(null);
    try {
      const data = await fetchQuiz(
        studentId,
        notion.trim(),
        count,
        config,
        course.trim() || null,
        chapter.trim() || null,
        sessionId,
      );
      setResult(data);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }

  async function gradeOne(questionId: number) {
    if (!result?.quiz_id) return;
    const answer = (answers[questionId] ?? "").trim();
    if (!answer || grading[questionId]) return;
    setGrading((g) => ({ ...g, [questionId]: true }));
    try {
      const verdict = await gradeQuizAnswer(
        studentId,
        result.quiz_id,
        questionId,
        answer,
        rigor,
        config,
      );
      setVerdicts((v) => ({ ...v, [questionId]: verdict }));
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setGrading((g) => ({ ...g, [questionId]: false }));
    }
  }

  async function gradeAll() {
    if (!result?.quiz_id || gradingAll) return;
    const quizId = result.quiz_id;
    const payload = result.questions
      .map((q) => ({
        question_id: q.id,
        answer: (q.id != null ? (answers[q.id] ?? "") : "").trim(),
      }))
      .filter(
        (a): a is { question_id: number; answer: string } =>
          a.question_id != null && a.answer.length > 0,
      );
    if (payload.length === 0) return;
    setGradingAll(true);
    try {
      const data = await gradeQuizAll(studentId, quizId, payload, rigor, config);
      setSummary(data);
      // Reflect per-question scores in the existing per-question cards.
      setVerdicts((v) => {
        const next = { ...v };
        for (const r of data.results) {
          next[r.question_id] = { score: r.score, feedback: r.feedback };
        }
        return next;
      });
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setGradingAll(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("quiz.title")}
          description={t("quiz.description")}
        />
        <CardBody className="space-y-4">
          <TextArea
            label={t("quiz.notionLabel")}
            placeholder={t("quiz.notionPlaceholder")}
            rows={3}
            value={notion}
            onChange={(e) => setNotion(e.target.value)}
            onKeyDown={submitOnCmdEnter(generate)}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <CourseSelect value={course} onChange={selectCourse} config={config} />
            <TextField
              label={t("ask.chapterLabel")}
              hint={t("ask.chapterHint")}
              placeholder={t("ask.chapterPlaceholder")}
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
            />
          </div>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
            <div className="space-y-1.5">
              <span className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                {t("quiz.questions")}
              </span>
              <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-700">
                {COUNTS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setCount(c)}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-sm font-medium tabular-nums transition-colors",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500",
                      count === c
                        ? "bg-brand-600 text-white dark:bg-brand-500"
                        : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-300 dark:hover:bg-zinc-800",
                    )}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
            <Button onClick={generate} loading={loading} disabled={!canGenerate}>
              {t("quiz.generate")}
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("quiz.resultTitle")}
          action={
            total != null ? (
              <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium tabular-nums text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
                {t("quiz.total", { total })}
              </span>
            ) : undefined
          }
        />
        <CardBody>
          {loading ? (
            <ThinkingIndicator variant="quiz" />
          ) : result == null ? (
            <EmptyState
              title={t("quiz.empty.title")}
              description={t("quiz.empty.description")}
            />
          ) : result.refused || result.questions.length === 0 ? (
            <RefusalBanner message={t("quiz.refused")} />
          ) : (
            <ol className="space-y-6">
              {result.questions.map((q, i) => {
                const qid = q.id;
                const verdict = qid != null ? verdicts[qid] : undefined;
                const score = verdict ? clampScore(verdict.score) : 0;
                const answer = qid != null ? (answers[qid] ?? "") : "";
                const isGrading = qid != null ? grading[qid] : false;
                const canGrade = qid != null && answer.trim().length > 0 && !isGrading;
                return (
                  <li key={qid ?? i} className="space-y-3">
                    <div className="flex items-start gap-3">
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-50 text-xs font-semibold tabular-nums text-brand-600 dark:bg-brand-500/15 dark:text-brand-300">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <Markdown>{q.problem}</Markdown>
                      </div>
                    </div>
                    <div className="pl-9">
                      <TextArea
                        label={t("quiz.answerLabel")}
                        placeholder={t("quiz.answerPlaceholder")}
                        rows={4}
                        value={answer}
                        disabled={qid == null}
                        onChange={(e) =>
                          qid != null &&
                          setAnswers((a) => ({ ...a, [qid]: e.target.value }))
                        }
                        onKeyDown={submitOnCmdEnter(() => qid != null && gradeOne(qid))}
                      />
                      <div className="mt-2 flex justify-end">
                        <Button
                          variant="secondary"
                          loading={isGrading}
                          disabled={!canGrade}
                          onClick={() => qid != null && gradeOne(qid)}
                        >
                          {t("quiz.gradeAnswer")}
                        </Button>
                      </div>
                      {isGrading && !verdict && (
                        <div className="mt-3">
                          <ThinkingIndicator variant="grade" />
                        </div>
                      )}
                      {verdict && (
                        <div className="mt-3 space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
                          <div className="space-y-1.5">
                            <div className="flex items-baseline justify-between">
                              <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                                {t("quiz.score")}
                              </span>
                              <span className="text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                                {score}/100
                              </span>
                            </div>
                            <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-all",
                                  scoreTone(score),
                                )}
                                style={{ width: `${score}%` }}
                              />
                            </div>
                          </div>
                          <div className="border-t border-zinc-100 pt-3 dark:border-zinc-700">
                            <Markdown>{verdict.feedback}</Markdown>
                          </div>
                        </div>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          )}
          {result && !result.refused && result.questions.length > 0 && (
            <div className="mt-6 flex flex-col gap-3 border-t border-zinc-100 pt-4 dark:border-zinc-800 sm:flex-row sm:items-end sm:justify-between">
              <div className="space-y-1.5">
                <span className="block text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  {t("rigor.label")}
                </span>
                <RigorSelector value={rigor} onChange={setRigor} disabled={gradingAll} />
              </div>
              <Button
                loading={gradingAll}
                disabled={!hasAnyAnswer || gradingAll}
                onClick={gradeAll}
              >
                {t("quiz.gradeAll")}
              </Button>
            </div>
          )}
        </CardBody>
      </Card>

      {gradingAll && (
        <Card>
          <CardHeader title={t("quiz.finalScore")} />
          <CardBody>
            <ThinkingIndicator
              variant="grade"
              label={t("quiz.gradingAll", { count: answeredCount })}
            />
          </CardBody>
        </Card>
      )}

      {!gradingAll && summary && (
        <Card>
          <CardHeader title={t("quiz.finalScore")} />
          <CardBody className="space-y-4">
            <div className="space-y-1.5">
              <div className="flex items-baseline justify-between">
                <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  {t("quiz.score")}
                </span>
                <span className="text-lg font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                  {clampScore(summary.total)}/100
                </span>
              </div>
              <div className="h-2.5 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                <div
                  className={cn(
                    "h-full rounded-full transition-all",
                    scoreTone(clampScore(summary.total)),
                  )}
                  style={{ width: `${clampScore(summary.total)}%` }}
                />
              </div>
            </div>
            {summary.recommendation.trim().length > 0 && (
              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <h3 className="mb-2 text-sm font-semibold text-zinc-900 dark:text-zinc-100">
                  {t("quiz.recommendationTitle")}
                </h3>
                <Markdown>{summary.recommendation}</Markdown>
              </div>
            )}
          </CardBody>
        </Card>
      )}
    </div>
  );
}
