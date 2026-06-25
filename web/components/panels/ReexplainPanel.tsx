"use client";

import { useState } from "react";
import { reexplain, type AskResponse, type ConnectionConfig, type Level } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { LevelSelector } from "@/components/LevelSelector";
import { useToast } from "@/components/Toast";

interface ReexplainPanelProps {
  studentId: string;
  config: ConnectionConfig;
  lastAnswer: AskResponse | null;
}

/**
 * Re-explains the student's last tutor answer at a chosen level. The backend
 * rebuilds context from persisted history, so this works even when `lastAnswer`
 * is not in memory; the friendly "nothing to re-explain" message comes straight
 * from the API and is rendered as-is.
 */
export function ReexplainPanel({ studentId, config, lastAnswer }: ReexplainPanelProps) {
  const toast = useToast();
  const [level, setLevel] = useState<Level>("beginner");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    try {
      const result = await reexplain(studentId, level, config);
      setAnswer(result.answer);
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
          title="Re-explain the last answer"
          description="Hear your most recent answer again, tuned to a different audience level."
        />
        <CardBody className="space-y-4">
          {lastAnswer && !lastAnswer.refused && (
            <div className="rounded-lg border border-zinc-100 bg-zinc-50/60 p-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400">
                Last answer
              </p>
              <Markdown>{lastAnswer.answer}</Markdown>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <LevelSelector value={level} onChange={setLevel} disabled={loading} />
            <Button onClick={run} loading={loading}>
              Re-explain
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Re-explanation" />
        <CardBody>
          {loading ? (
            <Skeleton lines={4} />
          ) : answer == null ? (
            <EmptyState
              title="Nothing re-explained yet"
              description="Pick a level and press Re-explain. Ask a question first if you have not yet."
            />
          ) : (
            <Markdown>{answer}</Markdown>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
