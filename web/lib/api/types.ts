/** Data shapes for the grounded-rag API client (requests, responses, config). */

export type Level = "beginner" | "intermediate" | "advanced";

export const LEVELS: readonly Level[] = ["beginner", "intermediate", "advanced"] as const;

/** Marking strictness applied when grading a student's answer. */
export type Rigor = "lenient" | "standard" | "strict";

export const RIGORS: readonly Rigor[] = ["lenient", "standard", "strict"] as const;

export interface AskRequest {
  student_id: string;
  question: string;
  k?: number;
  course?: string | null;
  chapter?: string | null;
  /** When set, the turn is attached to this conversation thread. */
  session_id?: number | null;
  /** Locale code ('en'/'fr'/'nl') to force the default answer language. */
  language?: string | null;
}

/** A conversation thread (session) for a student. `title` may be unset. */
export interface SessionOut {
  id: number;
  title: string | null;
  created_at: string;
}

/**
 * A cited source: its inline marker number, the chunk id (to fetch its excerpt)
 * and its display label. `n` is the 1-based index exactly as written inline in
 * the answer (`[n]`), so the UI can render a numbered legend matching the markers.
 */
export interface Citation {
  n: number;
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
  /** Id of the linked exercise/quiz for activity turns; null for plain Q&A. */
  ref_id?: number | null;
}

/** The latest grade on an exercise, surfaced for after-the-fact review. */
export interface ExerciseGradeReview {
  answer: string;
  score: number;
  feedback: string;
  created_at: string;
}

/** A generated exercise reviewed after the fact (reference solution included). */
export interface ExerciseReview {
  problem: string;
  reference_solution: string;
  grade: ExerciseGradeReview | null;
}

/** One quiz question reviewed after the fact, with the student's latest grade. */
export interface QuizQuestionReview {
  position: number;
  problem: string;
  reference_solution: string;
  answer: string | null;
  score: number | null;
  feedback: string | null;
}

/** A generated quiz reviewed after the fact (reference solutions included). */
export interface QuizReview {
  notion: string;
  questions: QuizQuestionReview[];
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
  /**
   * The visitor's own OpenAI key. When set it is sent as the `X-OpenAI-Key`
   * header on every request, so all LLM calls (Ask, Re-explain, Exercise, Quiz,
   * grading) — and document upload — run on the visitor's own premium OpenAI
   * model instead of the free default. Kept only in the browser; never persisted
   * server-side.
   */
  openaiKey?: string;
}

/** Minimal public view of an authenticated user. */
export interface AuthUser {
  id: number;
  /** The pseudonym: both the login identifier and the display name. */
  username: string;
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
