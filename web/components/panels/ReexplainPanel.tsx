"use client";

import { useState } from "react";
import { reexplain, type AskResponse, type ConnectionConfig, type Level } from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { Markdown } from "@/components/Markdown";
import { EmptyState, Skeleton } from "@/components/States";
import { LevelSelector } from "@/components/LevelSelector";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";

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
  const { t } = useT();
  const [level, setLevel] = useState<Level>("beginner");
  const [answer, setAnswer] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function run() {
    setLoading(true);
    try {
      const result = await reexplain(studentId, level, config);
      setAnswer(result.answer);
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
          title={t("reexplain.title")}
          description={t("reexplain.description")}
        />
        <CardBody className="space-y-4">
          {lastAnswer && !lastAnswer.refused && (
            <div className="rounded-lg border border-zinc-100 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                {t("reexplain.lastAnswer")}
              </p>
              <Markdown>{lastAnswer.answer}</Markdown>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <LevelSelector value={level} onChange={setLevel} disabled={loading} />
            <Button onClick={run} loading={loading}>
              {t("reexplain.action")}
            </Button>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("reexplain.resultTitle")} />
        <CardBody>
          {loading ? (
            <Skeleton lines={4} />
          ) : answer == null ? (
            <EmptyState
              title={t("reexplain.empty.title")}
              description={t("reexplain.empty.description")}
            />
          ) : (
            <Markdown>{answer}</Markdown>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
