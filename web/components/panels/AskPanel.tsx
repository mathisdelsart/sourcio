"use client";

import { useState } from "react";
import {
  ask,
  askStream,
  reexplain,
  type AskResponse,
  type ConnectionConfig,
  type Level,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField, TextArea } from "@/components/TextField";
import { CourseSelect } from "@/components/CourseSelect";
import { Markdown } from "@/components/Markdown";
import { CitationChip } from "@/components/CitationChip";
import { ExportActions } from "@/components/ExportActions";
import { AnswerFeedback } from "@/components/AnswerFeedback";
import { EmptyState, RefusalBanner } from "@/components/States";
import { AnswerProgress } from "@/components/AnswerProgress";
import { LevelSelector } from "@/components/LevelSelector";
import { useToast } from "@/components/Toast";
import { useT } from "@/lib/i18n";
import { submitOnCmdEnter } from "@/lib/keys";
import { KEYS, readLocal, writeLocal } from "@/lib/storage";

interface AskPanelProps {
  studentId: string;
  config: ConnectionConfig;
  /** Lifted so the Re-explain tab can act on the last answer too. */
  lastAnswer: AskResponse | null;
  setLastAnswer: (a: AskResponse | null) => void;
  /** Active conversation thread; when set, questions attach to it. */
  sessionId: number | null;
}

export function AskPanel({
  studentId,
  config,
  lastAnswer,
  setLastAnswer,
  sessionId,
}: AskPanelProps) {
  const toast = useToast();
  const { t, locale } = useT();
  // Start empty so the hero example shows only as the grey placeholder and
  // disappears as soon as the user types. The course/chapter filters stay empty
  // so retrieval searches every indexed course.
  const [question, setQuestion] = useState("");
  // Lazy-init from localStorage so the last chosen course survives a reload.
  const [course, setCourse] = useState(() => readLocal(KEYS.course));
  const [chapter, setChapter] = useState("");
  // Always retrieve the maximum: more candidate sources means more links to
  // ground the answer in. The threshold still filters out irrelevant ones.
  const MAX_SOURCES = 10;
  const [loading, setLoading] = useState(false);
  /** Text accumulated from the live token stream, before the final event lands. */
  const [streaming, setStreaming] = useState<string | null>(null);
  // Real progress stage from the stream, with the source count once retrieved.
  const [stage, setStage] = useState<"retrieving" | "reading" | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);

  const [reexplained, setReexplained] = useState<string | null>(null);
  const [level, setLevel] = useState<Level>("beginner");
  const [reLoading, setReLoading] = useState(false);

  const canAsk = question.trim().length > 0 && !loading;

  function selectCourse(next: string) {
    setCourse(next);
    writeLocal(KEYS.course, next);
  }

  async function runAsk() {
    if (!canAsk) return;
    setLoading(true);
    setReexplained(null);
    setLastAnswer(null);
    setStreaming("");
    setStage("retrieving");
    setSourceCount(null);
    const req = {
      student_id: studentId,
      question: question.trim(),
      k: MAX_SOURCES,
      course: course.trim() || null,
      chapter: chapter.trim() || null,
      session_id: sessionId,
      // Force the answer to default to the current UI language.
      language: locale,
    };
    try {
      let buffer = "";
      await askStream(
        req,
        (text) => {
          buffer += text;
          setStreaming(buffer);
        },
        (done) => {
          setLastAnswer({
            // Prefer the server-cleaned final answer (e.g. a trailing refusal
            // the model wrongly appended is stripped); fall back to the raw
            // token buffer for an older backend that does not send it.
            answer: done.answer ?? buffer,
            refused: done.refused,
            sources: done.sources,
            citations: done.citations,
          });
        },
        config,
        (s, n) => {
          setStage(s === "reading" ? "reading" : "retrieving");
          if (typeof n === "number") setSourceCount(n);
        },
      );
    } catch {
      // Streaming failed (e.g. proxy buffering, older backend): fall back to the
      // non-streaming endpoint so the user still gets a complete answer.
      try {
        const result = await ask(req, config);
        setLastAnswer(result);
      } catch (err) {
        toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
      }
    } finally {
      setStreaming(null);
      setStage(null);
      setLoading(false);
    }
  }

  async function runReexplain() {
    setReLoading(true);
    try {
      const result = await reexplain(studentId, level, config);
      setReexplained(result.answer);
    } catch (err) {
      toast.push(err instanceof Error ? err.message : "Request failed.", "error");
    } finally {
      setReLoading(false);
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <CardHeader
          title={t("ask.title")}
          description={t("ask.description")}
        />
        <CardBody className="space-y-4">
          <TextArea
            label={t("ask.questionLabel")}
            placeholder={t("ask.questionPlaceholder")}
            rows={4}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={submitOnCmdEnter(runAsk)}
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
            <Button onClick={runAsk} loading={loading} disabled={!canAsk}>
              {t("ask.submit")}
            </Button>
          </div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {t("common.submitHint")}
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title={t("ask.answerTitle")} />
        <CardBody>
          {streaming != null ? (
            streaming.length === 0 ? (
              <AnswerProgress stage={stage} sources={sourceCount} />
            ) : (
              <div className="streaming-answer" aria-live="polite" aria-busy="true">
                <Markdown>{streaming}</Markdown>
              </div>
            )
          ) : loading ? (
            <AnswerProgress stage={stage} sources={sourceCount} />
          ) : lastAnswer == null ? (
            <EmptyState
              title={t("ask.empty.title")}
              description={t("ask.empty.description")}
            />
          ) : lastAnswer.refused ? (
            <RefusalBanner message={lastAnswer.answer} />
          ) : (
            <div className="space-y-5">
              <Markdown>{lastAnswer.answer}</Markdown>
              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400">
                  {t("common.sources")}
                </p>
                {lastAnswer.citations && lastAnswer.citations.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {lastAnswer.citations.map((c, i) => (
                      <CitationChip key={`${c.id}-${i}`} label={c.label} id={c.id} config={config} />
                    ))}
                  </div>
                ) : lastAnswer.sources.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {lastAnswer.sources.map((source, i) => (
                      <CitationChip key={`${source}-${i}`} label={source} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-zinc-500 dark:text-zinc-400">{t("common.noSources")}</p>
                )}
              </div>

              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <ExportActions
                  question={question}
                  answer={lastAnswer.answer}
                  sources={lastAnswer.sources}
                />
              </div>

              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <AnswerFeedback
                  key={lastAnswer.answer}
                  studentId={studentId}
                  question={question}
                  answer={lastAnswer.answer}
                  config={config}
                />
              </div>

              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <p className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  {t("ask.reexplainPrompt")}
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <LevelSelector value={level} onChange={setLevel} disabled={reLoading} />
                  <Button variant="secondary" onClick={runReexplain} loading={reLoading}>
                    {t("ask.reexplain")}
                  </Button>
                </div>
                {reexplained && (
                  <div className="mt-4 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
                    <Markdown>{reexplained}</Markdown>
                  </div>
                )}
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
