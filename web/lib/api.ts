/**
 * Typed client for the grounded-rag FastAPI backend.
 *
 * One function per endpoint. The base URL and an optional API key are read from
 * public environment variables; the key may also be overridden at runtime via
 * the settings panel (passed through `overrides`). Every function throws an
 * `ApiError` on a non-2xx response so callers can surface a clean message.
 */

export type Level = "beginner" | "intermediate" | "advanced";

export const LEVELS: readonly Level[] = ["beginner", "intermediate", "advanced"] as const;

export interface AskRequest {
  student_id: string;
  question: string;
  k?: number;
  course?: string | null;
  chapter?: string | null;
  /** When set, the turn is attached to this conversation thread. */
  session_id?: number | null;
}

/** A conversation thread (session) for a student. `title` may be unset. */
export interface SessionOut {
  id: number;
  title: string | null;
  created_at: string;
}

/** A cited source: the chunk id (to fetch its excerpt) and its display label. */
export interface Citation {
  id: string;
  label: string;
}

export interface AskResponse {
  answer: string;
  refused: boolean;
  sources: string[];
  citations?: Citation[];
}

/** A source chunk's full excerpt, resolved from a citation via GET /source/{id}. */
export interface SourceChunk {
  id: string;
  course: string;
  chapter?: string | null;
  page: number;
  text: string;
}

export interface ReexplainResponse {
  answer: string;
}

export interface ExerciseResponse {
  problem: string;
  refused: boolean;
  id: number | null;
}

export interface GradeResponse {
  score: number;
  feedback: string;
}

export interface QuizQuestionOut {
  id: number | null;
  problem: string;
}

export interface QuizResponse {
  quiz_id: number | null;
  notion: string;
  questions: QuizQuestionOut[];
  refused: boolean;
}

export interface QuizGradeAllItem {
  question_id: number;
  answer: string;
}

export interface QuizGradeResult {
  question_id: number;
  score: number;
  feedback: string;
}

export interface QuizSummaryResponse {
  total: number;
  results: QuizGradeResult[];
  recommendation: string;
}

export interface HistoryItem {
  role: string;
  content: string;
  created_at: string;
}

/** Spaced-repetition recall quality, from 0 (forgot) to 5 (perfect). */
export type ReviewQuality = 0 | 1 | 2 | 3 | 4 | 5;

/** A notion scheduled for spaced-repetition review. */
export interface ReviewItem {
  notion: string;
  ease: number;
  interval_days: number;
  due_at: string;
}

/** A student's thumbs up (1) or down (-1) on a tutor answer. */
export type FeedbackRating = 1 | -1;

export interface FeedbackRequest {
  student_id: string;
  rating: FeedbackRating;
  question: string;
  answer: string;
  note?: string | null;
}

export interface FeedbackResponse {
  id: number;
}

/** Runtime overrides for the connection, sourced from the settings panel. */
export interface ConnectionConfig {
  baseUrl?: string;
  apiKey?: string;
  /** Bearer JWT for the logged-in user. Sent in addition to the API key. */
  token?: string;
}

/** Minimal public view of an authenticated user. */
export interface AuthUser {
  id: number;
  email: string;
}

/** Token returned by a successful login. */
export interface TokenResponse {
  access_token: string;
  token_type: string;
}

/** Error thrown for any failed request, carrying the HTTP status when known. */
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status = 0) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const DEFAULT_BASE_URL = "http://localhost:8000";

function envBaseUrl(): string {
  return process.env.NEXT_PUBLIC_API_BASE_URL || DEFAULT_BASE_URL;
}

function envApiKey(): string {
  return process.env.NEXT_PUBLIC_API_KEY || "";
}

function resolveBaseUrl(config?: ConnectionConfig): string {
  const raw = (config?.baseUrl ?? envBaseUrl()).trim() || DEFAULT_BASE_URL;
  return raw.replace(/\/+$/, "");
}

function resolveApiKey(config?: ConnectionConfig): string {
  return (config?.apiKey ?? envApiKey()).trim();
}

function buildHeaders(config?: ConnectionConfig, json = false): Headers {
  const headers = new Headers();
  if (json) {
    headers.set("Content-Type", "application/json");
  }
  const key = resolveApiKey(config);
  if (key) {
    headers.set("X-API-Key", key);
  }
  // Additive to the API key: when a user is logged in, also send the bearer JWT.
  const token = config?.token?.trim();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return headers;
}

async function readError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: unknown };
    if (typeof data?.detail === "string") {
      return data.detail;
    }
    if (data?.detail != null) {
      return JSON.stringify(data.detail);
    }
  } catch {
    /* fall through to status text */
  }
  return response.statusText || `Request failed (${response.status})`;
}

async function request<T>(
  path: string,
  init: RequestInit,
  config?: ConnectionConfig,
): Promise<T> {
  const url = `${resolveBaseUrl(config)}${path}`;
  let response: Response;
  try {
    response = await fetch(url, init);
  } catch {
    throw new ApiError(
      "Could not reach the backend. Check that it is running and the base URL is correct.",
    );
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  return (await response.json()) as T;
}

/** Liveness probe. Returns true only when the backend reports `status: ok`. */
export async function checkHealth(config?: ConnectionConfig): Promise<boolean> {
  try {
    const data = await request<{ status: string }>(
      "/health",
      { method: "GET", headers: buildHeaders(config) },
      config,
    );
    return data.status === "ok";
  } catch {
    return false;
  }
}

/** List the distinct courses currently indexed, sorted. Empty when none. */
export async function getCourses(config?: ConnectionConfig): Promise<string[]> {
  const data = await request<{ courses?: string[] }>(
    "/courses",
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
  return Array.isArray(data.courses) ? data.courses : [];
}

/** Ask a grounded question. `course`/`chapter` are only sent when truthy. */
export async function ask(
  body: AskRequest,
  config?: ConnectionConfig,
): Promise<AskResponse> {
  const payload: AskRequest = {
    student_id: body.student_id,
    question: body.question,
    k: body.k ?? 5,
  };
  if (body.course) payload.course = body.course;
  if (body.chapter) payload.chapter = body.chapter;
  if (body.session_id != null) payload.session_id = body.session_id;
  return request<AskResponse>(
    "/ask",
    { method: "POST", headers: buildHeaders(config, true), body: JSON.stringify(payload) },
    config,
  );
}

/** The final event of a streamed answer: resolved citations and refusal flag. */
export interface AskStreamDone {
  sources: string[];
  citations: Citation[];
  refused: boolean;
}

/**
 * Ask a grounded question and stream the answer token by token over SSE.
 *
 * `onToken` is called with each text delta as it arrives (for a typing effect);
 * `onDone` is called once with the resolved sources and refusal flag. Throws an
 * `ApiError` if the request cannot be reached or returns a non-2xx status, so
 * callers can fall back to the non-streaming `ask`.
 */
export async function askStream(
  body: AskRequest,
  onToken: (text: string) => void,
  onDone: (done: AskStreamDone) => void,
  config?: ConnectionConfig,
  onStage?: (stage: string, sources?: number) => void,
): Promise<void> {
  const payload: AskRequest = {
    student_id: body.student_id,
    question: body.question,
    k: body.k ?? 5,
  };
  if (body.course) payload.course = body.course;
  if (body.chapter) payload.chapter = body.chapter;
  if (body.session_id != null) payload.session_id = body.session_id;

  const url = `${resolveBaseUrl(config)}/ask/stream`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(
      "Could not reach the backend. Check that it is running and the base URL is correct.",
    );
  }
  if (!response.ok) {
    throw new ApiError(await readError(response), response.status);
  }
  if (!response.body) {
    throw new ApiError("Streaming is not supported by this response.", response.status);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const handleEvent = (raw: string) => {
    // Each SSE event is a block of lines; collect the `data:` payload(s).
    const data = raw
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("");
    if (!data) return;
    let event: {
      type?: string;
      text?: string;
      stage?: string;
      sources?: number | string[];
      citations?: Citation[];
      refused?: boolean;
    };
    try {
      event = JSON.parse(data);
    } catch {
      return; // ignore malformed frames rather than crashing the stream
    }
    if (event.type === "token" && typeof event.text === "string") {
      onToken(event.text);
    } else if (event.type === "stage" && typeof event.stage === "string") {
      onStage?.(event.stage, typeof event.sources === "number" ? event.sources : undefined);
    } else if (event.type === "sources") {
      onDone({
        sources: Array.isArray(event.sources) ? event.sources : [],
        citations: event.citations ?? [],
        refused: event.refused ?? false,
      });
    }
  };

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    // Events are separated by a blank line ("\n\n").
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      handleEvent(chunk);
    }
  }
  // Flush any trailing event that arrived without a terminating blank line.
  if (buffer.trim()) handleEvent(buffer);
}

/** Re-explain the student's last tutor answer at the requested level. */
export async function reexplain(
  studentId: string,
  level: Level,
  config?: ConnectionConfig,
): Promise<ReexplainResponse> {
  return request<ReexplainResponse>(
    "/reexplain",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, level }),
    },
    config,
  );
}

/** Generate a course-grounded exercise on a notion. */
export async function exercise(
  studentId: string,
  notion: string,
  config?: ConnectionConfig,
): Promise<ExerciseResponse> {
  return request<ExerciseResponse>(
    "/exercise",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, notion }),
    },
    config,
  );
}

/** Grade a student's answer, optionally against a prior exercise. */
export async function grade(
  studentId: string,
  message: string,
  exercisePayload: Record<string, unknown> | null,
  config?: ConnectionConfig,
): Promise<GradeResponse> {
  const body: Record<string, unknown> = { student_id: studentId, message };
  if (exercisePayload != null) {
    body.exercise = exercisePayload;
  }
  return request<GradeResponse>(
    "/grade",
    { method: "POST", headers: buildHeaders(config, true), body: JSON.stringify(body) },
    config,
  );
}

/** Generate a course-grounded quiz of `n` questions on a notion. */
export async function quiz(
  studentId: string,
  notion: string,
  n: number,
  config?: ConnectionConfig,
): Promise<QuizResponse> {
  return request<QuizResponse>(
    "/quiz",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, notion, n }),
    },
    config,
  );
}

/** Grade one quiz answer against the question's stored reference solution. */
export async function gradeQuizAnswer(
  studentId: string,
  quizId: number,
  questionId: number,
  answer: string,
  config?: ConnectionConfig,
): Promise<GradeResponse> {
  return request<GradeResponse>(
    `/quiz/${quizId}/grade`,
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, question_id: questionId, answer }),
    },
    config,
  );
}

/** Grade every answered question of a quiz at once for a final score. */
export async function gradeQuizAll(
  studentId: string,
  quizId: number,
  answers: QuizGradeAllItem[],
  config?: ConnectionConfig,
): Promise<QuizSummaryResponse> {
  return request<QuizSummaryResponse>(
    `/quiz/${quizId}/grade-all`,
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, answers }),
    },
    config,
  );
}

/** Create a new account. Returns the created user (id + email). */
export async function register(
  email: string,
  password: string,
  config?: ConnectionConfig,
): Promise<AuthUser> {
  return request<AuthUser>(
    "/auth/register",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ email, password }),
    },
    config,
  );
}

/** Log in and obtain a bearer access token. */
export async function login(
  email: string,
  password: string,
  config?: ConnectionConfig,
): Promise<TokenResponse> {
  return request<TokenResponse>(
    "/auth/login",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ email, password }),
    },
    config,
  );
}

/** Return the currently authenticated user for the supplied bearer token. */
export async function me(config?: ConnectionConfig): Promise<AuthUser> {
  return request<AuthUser>("/auth/me", { method: "GET", headers: buildHeaders(config) }, config);
}

/** Resolve a citation's chunk id into its full source excerpt (GET /source/{id}). */
export async function getSource(id: string, config?: ConnectionConfig): Promise<SourceChunk> {
  return request<SourceChunk>(
    `/source/${encodeURIComponent(id)}`,
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/** Record a thumbs up/down on a tutor answer. The note is only sent when set. */
export async function sendFeedback(
  body: FeedbackRequest,
  config?: ConnectionConfig,
): Promise<FeedbackResponse> {
  const payload: FeedbackRequest = {
    student_id: body.student_id,
    rating: body.rating,
    question: body.question,
    answer: body.answer,
  };
  if (body.note && body.note.trim()) payload.note = body.note.trim();
  return request<FeedbackResponse>(
    "/feedback",
    { method: "POST", headers: buildHeaders(config, true), body: JSON.stringify(payload) },
    config,
  );
}

/** List a student's conversation threads, newest first. Empty when none. */
export async function listSessions(
  studentId: string,
  config?: ConnectionConfig,
): Promise<SessionOut[]> {
  return request<SessionOut[]>(
    `/sessions/${encodeURIComponent(studentId)}`,
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/** Open a new conversation thread for a student. The title is only sent when set. */
export async function createSession(
  studentId: string,
  title?: string | null,
  config?: ConnectionConfig,
): Promise<SessionOut> {
  const body: Record<string, unknown> = { student_id: studentId };
  if (title && title.trim()) body.title = title.trim();
  return request<SessionOut>(
    "/sessions",
    { method: "POST", headers: buildHeaders(config, true), body: JSON.stringify(body) },
    config,
  );
}

/** Return the messages of one thread, chronological. */
export async function getSessionMessages(
  studentId: string,
  sessionId: number,
  config?: ConnectionConfig,
): Promise<HistoryItem[]> {
  return request<HistoryItem[]>(
    `/sessions/${encodeURIComponent(studentId)}/${sessionId}/messages`,
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/**
 * Delete a conversation thread together with its messages, so deleting a thread
 * clears that conversation rather than leaving orphaned turns in the history.
 */
export async function deleteSession(
  studentId: string,
  sessionId: number,
  config?: ConnectionConfig,
): Promise<{ deleted: boolean }> {
  return request<{ deleted: boolean }>(
    `/sessions/${encodeURIComponent(studentId)}/${sessionId}`,
    { method: "DELETE", headers: buildHeaders(config) },
    config,
  );
}

/** List the notions due for spaced-repetition review now, soonest first. */
export async function getDueReviews(
  studentId: string,
  config?: ConnectionConfig,
): Promise<ReviewItem[]> {
  return request<ReviewItem[]>(
    `/reviews/due?student_id=${encodeURIComponent(studentId)}`,
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/**
 * Record a recall rating for a notion and reschedule it. `quality` is 0..5;
 * the response carries the updated ease, interval and next due date.
 */
export async function recordReview(
  studentId: string,
  notion: string,
  quality: ReviewQuality,
  config?: ConnectionConfig,
): Promise<ReviewItem> {
  return request<ReviewItem>(
    "/reviews",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, notion, quality }),
    },
    config,
  );
}

/**
 * Add a notion to the spaced-repetition queue, due immediately. Unlike
 * {@link recordReview} this applies no SM-2 step: the notion is seeded at the
 * defaults with `due_at` set to now, so it appears in the due queue right away.
 */
export async function enqueueReview(
  studentId: string,
  notion: string,
  config?: ConnectionConfig,
): Promise<ReviewItem> {
  return request<ReviewItem>(
    "/reviews/enqueue",
    {
      method: "POST",
      headers: buildHeaders(config, true),
      body: JSON.stringify({ student_id: studentId, notion }),
    },
    config,
  );
}

/** Return the student's most recent turns, chronological. */
export async function history(
  studentId: string,
  limit = 20,
  config?: ConnectionConfig,
): Promise<HistoryItem[]> {
  return request<HistoryItem[]>(
    `/history/${encodeURIComponent(studentId)}?limit=${limit}`,
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/**
 * Delete a student's conversation messages. When `sessionId` is given, only
 * that thread's messages are cleared; otherwise the whole (unthreaded) history
 * is cleared. Returns how many rows were removed.
 */
export async function clearHistory(
  studentId: string,
  sessionId?: number | null,
  config?: ConnectionConfig,
): Promise<{ deleted: number }> {
  const query = sessionId != null ? `?session_id=${sessionId}` : "";
  return request<{ deleted: number }>(
    `/history/${encodeURIComponent(studentId)}${query}`,
    { method: "DELETE", headers: buildHeaders(config) },
    config,
  );
}

// --- Documents ---------------------------------------------------------------

/** One chapter of an indexed course and its page count. `chapter` may be null. */
export interface DocumentChapter {
  chapter: string | null;
  pages: number;
}

/** A course's indexed inventory: its chapters, page count and stored files. */
export interface DocumentCourse {
  course: string;
  total_pages: number;
  chapters: DocumentChapter[];
  /** Names of original uploaded files kept for this course (viewable). */
  files: string[];
}

/** A progress event streamed while a document is ingested. */
export interface DocumentProgress {
  type: "start" | "progress" | "done" | "error";
  total?: number;
  skipped?: number;
  done?: number;
  indexed?: number;
  elapsed?: number;
  message?: string;
}

/** How many indexed points a delete request removed. */
export interface DocumentDeleteResult {
  deleted: number;
}

/** List the indexed material organized by course and chapter. Empty when none. */
export async function listDocuments(config?: ConnectionConfig): Promise<DocumentCourse[]> {
  return request<DocumentCourse[]>(
    "/documents",
    { method: "GET", headers: buildHeaders(config) },
    config,
  );
}

/**
 * Upload a file and ingest it under `course`/`chapter`, streaming progress.
 *
 * The body is `multipart/form-data` (Content-Type left unset so the browser adds
 * the boundary). `onEvent` is called for each ingestion event (`start`,
 * `progress`, `done`, `error`) so the UI can show a live progress bar. Throws an
 * `ApiError` if the request cannot be reached or returns a non-2xx status.
 */
export async function uploadDocument(
  file: File,
  course: string,
  chapter: string | null,
  onEvent: (event: DocumentProgress) => void,
  config?: ConnectionConfig,
): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  form.append("course", course);
  if (chapter && chapter.trim()) form.append("chapter", chapter.trim());

  const url = `${resolveBaseUrl(config)}/documents/upload`;
  let response: Response;
  try {
    response = await fetch(url, { method: "POST", headers: buildHeaders(config), body: form });
  } catch {
    throw new ApiError(
      "Could not reach the backend. Check that it is running and the base URL is correct.",
    );
  }
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  if (!response.body) throw new ApiError("Streaming is not supported by this response.", response.status);

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const handle = (raw: string) => {
    const data = raw
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trim())
      .join("");
    if (!data) return;
    try {
      onEvent(JSON.parse(data) as DocumentProgress);
    } catch {
      // ignore malformed frames
    }
  };
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      handle(buffer.slice(0, sep));
      buffer = buffer.slice(sep + 2);
    }
  }
}

/** Fetch a stored original file as a Blob (sends auth headers, unlike a plain link). */
export async function fetchDocumentFile(
  course: string,
  name: string,
  config?: ConnectionConfig,
): Promise<Blob> {
  const params = new URLSearchParams({ course, name });
  const url = `${resolveBaseUrl(config)}/documents/file?${params.toString()}`;
  const response = await fetch(url, { method: "GET", headers: buildHeaders(config) });
  if (!response.ok) throw new ApiError(await readError(response), response.status);
  return response.blob();
}

/** Delete a course's indexed points, optionally narrowed to one chapter. */
export async function deleteDocument(
  course: string,
  chapter: string | null,
  config?: ConnectionConfig,
): Promise<DocumentDeleteResult> {
  const params = new URLSearchParams({ course });
  if (chapter) params.set("chapter", chapter);
  return request<DocumentDeleteResult>(
    `/documents?${params.toString()}`,
    { method: "DELETE", headers: buildHeaders(config) },
    config,
  );
}
