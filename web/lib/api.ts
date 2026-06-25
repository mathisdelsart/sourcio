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
}

export interface AskResponse {
  answer: string;
  refused: boolean;
  sources: string[];
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

export interface HistoryItem {
  role: string;
  content: string;
  created_at: string;
}

/** Runtime overrides for the connection, sourced from the settings panel. */
export interface ConnectionConfig {
  baseUrl?: string;
  apiKey?: string;
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
  return request<AskResponse>(
    "/ask",
    { method: "POST", headers: buildHeaders(config, true), body: JSON.stringify(payload) },
    config,
  );
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
