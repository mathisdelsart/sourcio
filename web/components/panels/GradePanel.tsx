"use client";

import { useState } from "react";
import { grade, type ConnectionConfig, type ExerciseResponse, type GradeResponse } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextArea } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
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
  const { t } = useT();
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
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }

  const score = result ? clampScore(result.score) : 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("grade.title")}
          description={t("grade.description")}
        />
        <CardBody className="space-y-4">
          {linkable && (
            <div className="rounded-lg border border-brand-100 bg-brand-50/60 p-4 dark:border-brand-500/30 dark:bg-brand-500/10">
              <p className="text-xs font-semibold uppercase tracking-wide text-brand-500 dark:text-brand-300">
                {t("grade.against", { id: String(linkable.id) })}
              </p>
              <div className="mt-2">
                <Markdown>{linkable.problem}</Markdown>
              </div>
            </div>
          )}
          <TextArea
            label={t("grade.answerLabel")}
            placeholder={t("grade.answerPlaceholder")}
            rows={6}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={submitOnCmdEnter(run)}
          />
          <div className="flex items-center justify-between">
            <p className="text-xs text-zinc-400 dark:text-zinc-500">
              {t("common.submitHint")}
            </p>
            <Button onClick={run} loading={loading} disabled={!canGrade}>
              {t("grade.submit")}
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("grade.verdictTitle")} />
        <CardBody>
          {loading ? (
            <Skeleton lines={3} />
          ) : result == null ? (
            <EmptyState
              title={t("grade.empty.title")}
              description={t("grade.empty.description")}
            />
          ) : (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <div className="flex items-baseline justify-between">
                  <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">{t("grade.score")}</span>
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
