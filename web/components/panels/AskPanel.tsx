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
import { Markdown } from "@/components/Markdown";
import { CitationChip } from "@/components/CitationChip";
import { ExportActions } from "@/components/ExportActions";
import { EmptyState, RefusalBanner, Skeleton } from "@/components/States";
import { LevelSelector } from "@/components/LevelSelector";
import { useToast } from "@/components/Toast";
import { submitOnCmdEnter } from "@/lib/keys";

interface AskPanelProps {
  studentId: string;
  config: ConnectionConfig;
  /** Lifted so the Re-explain tab can act on the last answer too. */
  lastAnswer: AskResponse | null;
  setLastAnswer: (a: AskResponse | null) => void;
}

export function AskPanel({ studentId, config, lastAnswer, setLastAnswer }: AskPanelProps) {
  const toast = useToast();
  const [question, setQuestion] = useState("");
  const [course, setCourse] = useState("");
  const [chapter, setChapter] = useState("");
  const [k, setK] = useState(5);
  const [loading, setLoading] = useState(false);
  /** Text accumulated from the live token stream, before the final event lands. */
  const [streaming, setStreaming] = useState<string | null>(null);

  const [reexplained, setReexplained] = useState<string | null>(null);
  const [level, setLevel] = useState<Level>("beginner");
  const [reLoading, setReLoading] = useState(false);

  const canAsk = question.trim().length > 0 && !loading;

  async function runAsk() {
    if (!canAsk) return;
    setLoading(true);
    setReexplained(null);
    setLastAnswer(null);
    setStreaming("");
    const req = {
      student_id: studentId,
      question: question.trim(),
      k,
      course: course.trim() || null,
      chapter: chapter.trim() || null,
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
          setLastAnswer({ answer: buffer, refused: done.refused, sources: done.sources });
        },
        config,
      );
    } catch {
      // Streaming failed (e.g. proxy buffering, older backend): fall back to the
      // non-streaming endpoint so the user still gets a complete answer.
      try {
        const result = await ask(req, config);
        setLastAnswer(result);
      } catch (err) {
        toast.push(err instanceof Error ? err.message : "Request failed.", "error");
      }
    } finally {
      setStreaming(null);
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
          title="Ask a question"
          description="Answers come strictly from your indexed course material."
        />
        <CardBody className="space-y-4">
          <TextArea
            label="Question"
            placeholder="e.g. What is the admissibility condition for a wavelet?"
            rows={4}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={submitOnCmdEnter(runAsk)}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <TextField
              label="Course filter"
              hint="Optional — restrict retrieval to one course."
              placeholder="e.g. ELEC2885 Wavelet Transform"
              value={course}
              onChange={(e) => setCourse(e.target.value)}
            />
            <TextField
              label="Chapter filter"
              hint="Optional — restrict to a single chapter."
              placeholder="e.g. Chapter 3"
              value={chapter}
              onChange={(e) => setChapter(e.target.value)}
            />
          </div>
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="w-full max-w-xs space-y-1.5">
              <label
                htmlFor="ask-k"
                className="block text-sm font-medium text-zinc-700 dark:text-zinc-300"
              >
                Sources to retrieve:{" "}
                <span className="tabular-nums text-zinc-500 dark:text-zinc-400">{k}</span>
              </label>
              <input
                id="ask-k"
                type="range"
                min={1}
                max={10}
                value={k}
                onChange={(e) => setK(Number(e.target.value))}
                className="w-full accent-indigo-600 dark:accent-indigo-400"
              />
            </div>
            <Button onClick={runAsk} loading={loading} disabled={!canAsk}>
              Ask
            </Button>
          </div>
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            Press ⌘/Ctrl + Enter to submit.
          </p>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Answer" />
        <CardBody>
          {streaming != null ? (
            streaming.length === 0 ? (
              <Skeleton lines={4} />
            ) : (
              <div className="space-y-2" aria-live="polite" aria-busy="true">
                <Markdown>{streaming}</Markdown>
                <span className="inline-block h-4 w-2 animate-pulse bg-indigo-400 align-middle dark:bg-indigo-300" />
              </div>
            )
          ) : loading ? (
            <Skeleton lines={4} />
          ) : lastAnswer == null ? (
            <EmptyState
              title="No answer yet"
              description="Ask a question above to see a grounded, cited explanation."
            />
          ) : lastAnswer.refused ? (
            <RefusalBanner message={lastAnswer.answer} />
          ) : (
            <div className="space-y-5">
              <Markdown>{lastAnswer.answer}</Markdown>
              <div>
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                  Sources
                </p>
                {lastAnswer.sources.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {lastAnswer.sources.map((source, i) => (
                      <CitationChip key={`${source}-${i}`} label={source} />
                    ))}
                  </div>
                ) : (
                  <p className="text-sm text-zinc-400 dark:text-zinc-500">No sources cited.</p>
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
                <p className="mb-2 text-sm font-medium text-zinc-700 dark:text-zinc-300">
                  Didn&apos;t get it? Re-explain at a level:
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <LevelSelector value={level} onChange={setLevel} disabled={reLoading} />
                  <Button variant="secondary" onClick={runReexplain} loading={reLoading}>
                    Re-explain
                  </Button>
                </div>
                {reexplained && (
                  <div className="mt-4 rounded-lg border border-zinc-100 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
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
