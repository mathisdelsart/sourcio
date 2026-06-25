"use client";

import { useMemo, useState } from "react";
import {
  quiz as fetchQuiz,
  gradeQuizAnswer,
  type ConnectionConfig,
  type GradeResponse,
  type QuizResponse,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField, TextArea } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
import { EmptyState, RefusalBanner, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { submitOnCmdEnter } from "@/lib/keys";
import { cn } from "@/lib/cn";

interface QuizPanelProps {
  studentId: string;
  config: ConnectionConfig;
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

export function QuizPanel({ studentId, config }: QuizPanelProps) {
  const toast = useToast();
  const [notion, setNotion] = useState("");
  const [count, setCount] = useState<number>(3);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<QuizResponse | null>(null);

  // Per-question answer text and verdict, keyed by question id.
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [verdicts, setVerdicts] = useState<Record<number, GradeResponse>>({});
  const [grading, setGrading] = useState<Record<number, boolean>>({});

  const canGenerate = notion.trim().length > 0 && !loading;

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
    try {
      const data = await fetchQuiz(studentId, notion.trim(), count, config);
      setResult(data);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "Request failed.", "error");
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
        config,
      );
      setVerdicts((v) => ({ ...v, [questionId]: verdict }));
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "Request failed.", "error");
    } finally {
      setGrading((g) => ({ ...g, [questionId]: false }));
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Generate a quiz"
          description="A set of practice questions grounded in the course, using its notation."
        />
        <CardBody className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <TextField
                label="Notion to quiz on"
                placeholder="e.g. continuous wavelet transform"
                value={notion}
                onChange={(e) => setNotion(e.target.value)}
                onKeyDown={submitOnCmdEnter(generate)}
              />
            </div>
            <div className="space-y-1.5">
              <span className="block text-sm font-medium text-zinc-700">Questions</span>
              <div className="inline-flex rounded-lg border border-zinc-200 p-0.5">
                {COUNTS.map((c) => (
                  <button
                    key={c}
                    type="button"
                    onClick={() => setCount(c)}
                    className={cn(
                      "rounded-md px-3 py-1.5 text-sm font-medium tabular-nums transition-colors",
                      count === c
                        ? "bg-indigo-600 text-white"
                        : "text-zinc-600 hover:bg-zinc-100",
                    )}
                  >
                    {c}
                  </button>
                ))}
              </div>
            </div>
            <Button onClick={generate} loading={loading} disabled={!canGenerate}>
              Generate
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Quiz"
          action={
            total != null ? (
              <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium tabular-nums text-zinc-500">
                Total {total}/100
              </span>
            ) : undefined
          }
        />
        <CardBody>
          {loading ? (
            <Skeleton lines={5} />
          ) : result == null ? (
            <EmptyState
              title="No quiz yet"
              description="Enter a notion above to generate a course-grounded quiz."
            />
          ) : result.refused || result.questions.length === 0 ? (
            <RefusalBanner message="This notion is not covered by the course material." />
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
                      <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-indigo-50 text-xs font-semibold tabular-nums text-indigo-600">
                        {i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <Markdown>{q.problem}</Markdown>
                      </div>
                    </div>
                    <div className="pl-9">
                      <TextArea
                        label="Your answer"
                        placeholder="Write your solution here…"
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
                          Grade answer
                        </Button>
                      </div>
                      {verdict && (
                        <div className="mt-3 space-y-3 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4">
                          <div className="space-y-1.5">
                            <div className="flex items-baseline justify-between">
                              <span className="text-sm font-medium text-zinc-700">Score</span>
                              <span className="text-sm font-semibold tabular-nums text-zinc-900">
                                {score}/100
                              </span>
                            </div>
                            <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-100">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-all",
                                  scoreTone(score),
                                )}
                                style={{ width: `${score}%` }}
                              />
                            </div>
                          </div>
                          <div className="border-t border-zinc-100 pt-3">
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
        </CardBody>
      </Card>
    </div>
  );
}
