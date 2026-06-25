"use client";

import { useState } from "react";
import { exercise, type ConnectionConfig, type ExerciseResponse } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField } from "@/components/TextField";
import { Markdown } from "@/components/Markdown";
import { EmptyState, RefusalBanner, Skeleton } from "@/components/States";
import { useToast } from "@/components/Toast";
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
      toast.push(err instanceof Error ? err.message : "Request failed.", "error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title="Generate an exercise"
          description="A practice problem grounded in the course, using its notation."
        />
        <CardBody className="space-y-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-end">
            <div className="flex-1">
              <TextField
                label="Notion to practice"
                placeholder="e.g. continuous wavelet transform"
                value={notion}
                onChange={(e) => setNotion(e.target.value)}
                onKeyDown={submitOnCmdEnter(run)}
              />
            </div>
            <Button onClick={run} loading={loading} disabled={!canGenerate}>
              Generate
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Exercise"
          action={
            lastExercise && !lastExercise.refused && lastExercise.id != null ? (
              <span className="rounded-full border border-zinc-200 bg-zinc-50 px-2.5 py-1 text-xs font-medium tabular-nums text-zinc-500">
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
              title="No exercise yet"
              description="Enter a notion above to generate a course-grounded problem."
            />
          ) : lastExercise.refused ? (
            <RefusalBanner message={lastExercise.problem} />
          ) : (
            <div className="space-y-3">
              <Markdown>{lastExercise.problem}</Markdown>
              <p className="text-xs text-zinc-400">
                Solve it, then head to the Grade tab — your answer is linked to this exercise.
              </p>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
