"use client";

import { useState } from "react";
import { grade, type ConnectionConfig, type ExerciseResponse, type GradeResponse } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextArea } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { submitOnCmdEnter } from "@/lib/keys";
import { cn } from "@/lib/cn";

interface GradePanelProps {
  studentId: string;
  config: ConnectionConfig;
  lastExercise: ExerciseResponse | null;
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

export function GradePanel({ studentId, config, lastExercise }: GradePanelProps) {
  const toast = useToast();
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<GradeResponse | null>(null);
  const [loading, setLoading] = useState(false);

  // Link the grade to the last exercise only when it is a real, persisted one.
  const linkable =
    lastExercise && !lastExercise.refused && lastExercise.id != null ? lastExercise : null;

  const canGrade = answer.trim().length > 0 && !loading;

  async function run() {
    if (!canGrade) return;
    setLoading(true);
    try {
      const payload = linkable
        ? ({ id: linkable.id, problem: linkable.problem } as Record<string, unknown>)
        : null;
      const verdict = await grade(studentId, answer.trim(), payload, config);
      setResult(verdict);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "Request failed.", "error");
    } finally {
      setLoading(false);
    }
  }

  const score = result ? clampScore(result.score) : 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Grade your answer"
          description="An LLM judge scores your answer and explains why."
        />
        <CardBody className="space-y-4">
          {linkable && (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/60 p-4 dark:border-indigo-500/30 dark:bg-indigo-500/10">
              <p className="text-xs font-semibold uppercase tracking-wide text-indigo-500 dark:text-indigo-300">
                Grading against exercise #{linkable.id}
              </p>
              <div className="mt-2">
                <Markdown>{linkable.problem}</Markdown>
              </div>
            </div>
          )}
          <TextArea
            label="Your answer"
            placeholder="Write your solution here…"
            rows={6}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={submitOnCmdEnter(run)}
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-400 dark:text-zinc-500">
              Press ⌘/Ctrl + Enter to submit.
            </p>
            <Button onClick={run} loading={loading} disabled={!canGrade}>
              Grade
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Verdict" />
        <CardBody>
          {loading ? (
            <Skeleton lines={3} />
          ) : result == null ? (
            <EmptyState
              title="Not graded yet"
              description="Submit an answer above to get a score and feedback."
            />
          ) : (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">Score</span>
                  <span className="text-sm font-semibold tabular-nums text-zinc-900 dark:text-zinc-100">
                    {score}/100
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
                  <div
                    className={cn("h-full rounded-full transition-all", scoreTone(score))}
                    style={{ width: `${score}%` }}
                  />
                </div>
              </div>
              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <Markdown>{result.feedback}</Markdown>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
