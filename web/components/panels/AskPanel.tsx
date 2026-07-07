"use client";

import { useState } from "react";
import {
  ask,
  askStream,
  reexplain,
  reexplainStream,
  type AskResponse,
  type ConnectionConfig,
  type Level,
} from "@/lib/api";
import { Card, CardBody, CardHeader } from "@/components/Card";
import { Button } from "@/components/Button";
import { TextField, TextArea } from "@/components/TextField";
import { CourseSelect } from "@/components/CourseSelect";
import { ChapterSelect } from "@/components/ChapterSelect";
import { Markdown } from "@/components/Markdown";
import { CitationChip } from "@/components/CitationChip";
import { Spinner } from "@/components/Spinner";
import { ExportActions } from "@/components/ExportActions";
import { AnswerFeedback } from "@/components/AnswerFeedback";
import { EmptyState, NoCoursesState, RefusalBanner } from "@/components/States";
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
  /** Max candidate sources to retrieve (the ceiling `k`); surfaced below. */
  sourcesMax: number;
  /** Persist a new max-sources ceiling (clamped by the parent). */
  onSourcesMaxChange: (next: number) => void;
  /** The user's indexed courses, lifted to the page and shared across panels. */
  courses: string[];
  /** True while the shared course list is still loading. */
  coursesLoading: boolean;
  /** True when the shared course list failed to load. */
  coursesError: boolean;
  /** Switch to the Documents tab so the user can import a course. */
  onImport: () => void;
}

// Bounds for the max-sources control (mirrors the parent's clamp).
const SOURCES_MAX_MIN = 1;
const SOURCES_MAX_MAX = 50;

export function AskPanel({
  studentId,
  config,
  lastAnswer,
  setLastAnswer,
  sessionId,
  sourcesMax,
  onSourcesMaxChange,
  courses,
  coursesLoading,
  coursesError,
  onImport,
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
  // `sourcesMax` is the candidate pool ceiling (`k`), configurable in Settings.
  // A generous pool gives the answer more sources to ground in; the similarity
  // threshold still prunes irrelevant chunks and the answer cites only useful
  // ones. It is a tunable ceiling rather than unbounded because a very high
  // value slows a LOCAL model (larger context, higher latency).
  const [loading, setLoading] = useState(false);
  /** Text accumulated from the live token stream, before the final event lands. */
  const [streaming, setStreaming] = useState<string | null>(null);
  // Real progress stage from the stream, with the source count once retrieved.
  const [stage, setStage] = useState<"retrieving" | "reading" | null>(null);
  const [sourceCount, setSourceCount] = useState<number | null>(null);

  const [reexplained, setReexplained] = useState<string | null>(null);
  const [level, setLevel] = useState<Level>("beginner");
  const [reLoading, setReLoading] = useState(false);
  /** Text accumulated from the live re-explanation stream, before it completes. */
  const [reStreaming, setReStreaming] = useState<string | null>(null);

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
      k: sourcesMax,
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
    setReexplained(null);
    setReStreaming("");
    try {
      let buffer = "";
      await reexplainStream(
        studentId,
        level,
        (text) => {
          buffer += text;
          setReStreaming(buffer);
        },
        (answer) => {
          setReexplained(answer || buffer);
        },
        config,
      );
    } catch {
      // Streaming failed (e.g. proxy buffering, older backend): fall back to the
      // non-streaming endpoint so the user still gets a re-explanation.
      try {
        const result = await reexplain(studentId, level, config);
        setReexplained(result.answer);
      } catch (err) {
        toast.push(err instanceof Error ? err.message : t("common.requestFailed"), "error");
      }
    } finally {
      setReStreaming(null);
      setReLoading(false);
    }
  }

  // With no indexed courses there is nothing to ground an answer in, so the
  // tool refuses to take a question and points the user to import a course.
  if (!coursesLoading && courses.length === 0) {
    return (
      <Card>
        <CardHeader title={t("ask.title")} description={t("ask.description")} />
        <CardBody>
          <NoCoursesState onImport={onImport} />
        </CardBody>
      </Card>
    );
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
          {/* Course · Chapter · Max sources on one compact row (they stack on
              mobile). Max sources stays narrow since it is a small number. */}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <CourseSelect
              value={course}
              onChange={selectCourse}
              courses={courses}
              loading={coursesLoading}
              error={coursesError}
            />
            <ChapterSelect
              course={course}
              studentId={studentId}
              config={config}
              value={chapter}
              onChange={setChapter}
            />
            <TextField
              label={t("ask.maxSources")}
              hint={t("ask.maxSourcesHint")}
              type="number"
              inputMode="numeric"
              min={SOURCES_MAX_MIN}
              max={SOURCES_MAX_MAX}
              value={String(sourcesMax)}
              onChange={(e) => {
                const parsed = Number.parseInt(e.target.value, 10);
                if (Number.isFinite(parsed)) onSourcesMaxChange(parsed);
              }}
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
              <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-700 dark:bg-emerald-500/10 dark:text-emerald-400">
                <svg viewBox="0 0 20 20" fill="currentColor" className="h-3.5 w-3.5" aria-hidden>
                  <path
                    fillRule="evenodd"
                    d="M16.7 5.3a1 1 0 0 1 0 1.4l-7.5 7.5a1 1 0 0 1-1.4 0l-3.5-3.5a1 1 0 1 1 1.4-1.4l2.8 2.79 6.8-6.79a1 1 0 0 1 1.4 0Z"
                    clipRule="evenodd"
                  />
                </svg>
                {t("hero.app.answered")}
              </span>
              <Markdown>{lastAnswer.answer}</Markdown>
              <div className="border-t border-zinc-100 pt-4 dark:border-zinc-800">
                <p className="mb-2.5 text-xs font-semibold uppercase tracking-wider text-brand-600 dark:text-brand-400">
                  {t("common.sources")}
                  {/* Show the count of CITED (useful) sources, not the request k. */}
                  {(lastAnswer.citations?.length || lastAnswer.sources.length) > 0 && (
                    <span className="ml-1.5 font-normal text-zinc-400 dark:text-zinc-500">
                      ({lastAnswer.citations?.length || lastAnswer.sources.length})
                    </span>
                  )}
                </p>
                {lastAnswer.citations && lastAnswer.citations.length > 0 ? (
                  // Numbered legend: each entry leads with the inline marker [n]
                  // and stays clickable to open the exact source excerpt.
                  <ol className="space-y-1.5">
                    {lastAnswer.citations.map((c, i) => (
                      <li key={`${c.id}-${i}`}>
                        <CitationChip
                          label={c.label}
                          id={c.id}
                          n={c.n}
                          config={config}
                          studentId={studentId}
                          // Highlight, inside the opened excerpt, the words the
                          // answer (and the asked question) drew on. Purely
                          // client-side: neither is sent to the backend.
                          highlightSource={`${question} ${lastAnswer.answer}`}
                        />
                      </li>
                    ))}
                  </ol>
                ) : lastAnswer.sources.length > 0 ? (
                  <div className="flex flex-wrap gap-2">
                    {lastAnswer.sources.map((source, i) => (
                      <CitationChip key={`${source}-${i}`} label={source} n={i + 1} />
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
                {reStreaming != null ? (
                  <div className="mt-4 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
                    {reStreaming.length === 0 ? (
                      <p className="flex items-center gap-2 text-sm text-zinc-500 dark:text-zinc-400">
                        <Spinner /> {t("ask.rephrasing")}
                      </p>
                    ) : (
                      <div className="streaming-answer" aria-live="polite" aria-busy="true">
                        <Markdown>{reStreaming}</Markdown>
                      </div>
                    )}
                  </div>
                ) : (
                  reexplained && (
                    <div className="mt-4 rounded-xl border border-zinc-200 bg-zinc-50/60 p-4 dark:border-zinc-800 dark:bg-zinc-800/40">
                      <Markdown>{reexplained}</Markdown>
                    </div>
                  )
                )}
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
