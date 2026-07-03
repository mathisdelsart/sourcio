"use client";

import { useState } from "react";
import {
  exercise,
  grade,
  type ConnectionConfig,
  type ExerciseResponse,
  type GradeResponse,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextArea, TextField } from "@/components/TextField";
import { CourseSelect } from "@/components/CourseSelect";
import { Markdown } from "@/components/Markdown";
import { EmptyState, RefusalBanner } from "@/components/States";
import { ThinkingIndicator } from "@/components/ThinkingIndicator";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { submitOnCmdEnter } from "@/lib/keys";
import { KEYS, readLocal, writeLocal } from "@/lib/storage";
import { cn } from "@/lib/cn";

interface ExercisePanelProps {
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

/**
 * Generate a course-grounded exercise and grade an answer against it in the
 * same flow. Grading depends on a persisted exercise, so it lives here rather
 * than in a separate tab and only appears once a real exercise exists.
 */
export function ExercisePanel({ studentId, config }: ExercisePanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [notion, setNotion] = useState("");
  // Course/chapter scope retrieval so the exercise stays on the requested topic.
  // Lazy-init the course from localStorage so a choice is shared across tabs.
  const [course, setCourse] = useState(() => readLocal(KEYS.course));
  const [chapter, setChapter] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastExercise, setLastExercise] = useState<ExerciseResponse | null>(null);

  // Grading state, reset whenever a new exercise is generated.
  const [answer, setAnswer] = useState("");
  const [grading, setGrading] = useState(false);
  const [result, setResult] = useState<GradeResponse | null>(null);

  const canGenerate = notion.trim().length > 0 && !loading;

  // Grading is offered only for a real, persisted exercise (not a refusal).
  const gradable =
    lastExercise && !lastExercise.refused && lastExercise.id != null ? lastExercise : null;
  const canGrade = answer.trim().length > 0 && !grading;

  function selectCourse(next: string) {
    setCourse(next);
    writeLocal(KEYS.course, next);
  }

  async function run() {
    if (!canGenerate) return;
    setLoading(true);
    try {
      const generated = await exercise(
        studentId,
        notion.trim(),
        config,
        course.trim() || null,
        chapter.trim() || null,
      );
      setLastExercise(generated);
      // A fresh exercise invalidates any answer/verdict from the previous one.
      setAnswer("");
      setResult(null);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }

  async function runGrade() {
    if (!canGrade || !gradable) return;
    setGrading(true);
    try {
      const payload = { id: gradable.id, problem: gradable.problem } as Record<string, unknown>;
      const verdict = await grade(studentId, answer.trim(), payload, config);
      setResult(verdict);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setGrading(false);
    }
  }

  const score = result ? clampScore(result.score) : 0;

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("exercise.title")}
          description={t("exercise.description")}
        />
        <CardBody className="space-y-4">
          <TextArea
            label={t("exercise.notionLabel")}
            placeholder={t("exercise.notionPlaceholder")}
            rows={3}
            value={notion}
            onChange={(e) => setNotion(e.target.value)}
            onKeyDown={submitOnCmdEnter(run)}
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
          <div className="flex justify-end">
            <Button onClick={run} loading={loading} disabled={!canGenerate}>
              {t("exercise.generate")}
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title={t("exercise.resultTitle")}
          action={
            lastExercise && !lastExercise.refused && lastExercise.id != null ? (
              <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium tabular-nums text-zinc-500 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400">
                #{lastExercise.id}
              </span>
            ) : undefined
          }
        />
        <CardBody>
          {loading ? (
            <ThinkingIndicator variant="exercise" />
          ) : lastExercise == null ? (
            <EmptyState
              title={t("exercise.empty.title")}
              description={t("exercise.empty.description")}
            />
          ) : lastExercise.refused ? (
            <RefusalBanner message={lastExercise.problem} />
          ) : (
            <div className="space-y-3">
              <Markdown>{lastExercise.problem}</Markdown>
              <p className="text-xs text-zinc-400 dark:text-zinc-500">
                {t("exercise.solveHint")}
              </p>
            </div>
          )}
        </CardBody>
      </Card>

      {/* Grading — only once a gradable exercise exists, so the answer is always
          linked to the exercise shown above. */}
      {gradable && (
        <>
          <Card>
            <CardHeader title={t("grade.title")} description={t("grade.description")} />
            <CardBody className="space-y-4">
              <TextArea
                label={t("grade.answerLabel")}
                placeholder={t("grade.answerPlaceholder")}
                rows={6}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                onKeyDown={submitOnCmdEnter(runGrade)}
              />
              <div className="flex items-center justify-between">
                <p className="text-xs text-zinc-400 dark:text-zinc-500">
                  {t("common.submitHint")}
                </p>
                <Button onClick={runGrade} loading={grading} disabled={!canGrade}>
                  {t("grade.submit")}
                </Button>
              </div>
            </CardBody>
          </Card>

          {/* The correction card only appears once grading starts — no empty
              "not graded yet" placeholder. */}
          {(grading || result) && (
            <Card>
              <CardHeader title={t("grade.verdictTitle")} />
              <CardBody>
                {grading ? (
                  <ThinkingIndicator variant="grade" />
                ) : result ? (
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <div className="flex items-baseline justify-between">
                        <span className="text-sm font-medium text-zinc-700 dark:text-zinc-300">
                          {t("grade.score")}
                        </span>
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
                ) : null}
              </CardBody>
            </Card>
          )}
        </>
      )}
    </div>
  );
}
