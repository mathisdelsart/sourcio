"use client";

import { useState } from "react";
import { exercise, type ConnectionConfig, type ExerciseResponse } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
import { EmptyState, RefusalBanner, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { submitOnCmdEnter } from "@/lib/keys";

interface ExercisePanelProps {
  studentId: string;
  config: ConnectionConfig;
  /** Lifted so the Grade tab can link an answer to this exercise. */
  lastExercise: ExerciseResponse | null;
  setLastExercise: (e: ExerciseResponse | null) => void;
}

export function ExercisePanel({
  studentId,
  config,
  lastExercise,
  setLastExercise,
}: ExercisePanelProps) {
  const toast = useToast();
  const { t } = useT();
  const [notion, setNotion] = useState("");
  const [loading, setLoading] = useState(false);

  const canGenerate = notion.trim().length > 0 && !loading;

  async function run() {
    if (!canGenerate) return;
    setLoading(true);
    try {
      const result = await exercise(studentId, notion.trim(), config);
      setLastExercise(result);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("exercise.title")}
          description={t("exercise.description")}
        />
        <CardBody className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <TextField
                label={t("exercise.notionLabel")}
                placeholder={t("exercise.notionPlaceholder")}
                value={notion}
                onChange={(e) => setNotion(e.target.value)}
                onKeyDown={submitOnCmdEnter(run)}
              />
            </div>
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
            <Skeleton lines={4} />
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
    </div>
  );
}
