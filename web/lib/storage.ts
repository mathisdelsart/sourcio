/** Small, SSR-safe localStorage helpers used for client-persisted preferences. */

export const KEYS = {
  studentId: "grounded-rag:student_id",
  baseUrl: "grounded-rag:base_url",
  apiKey: "grounded-rag:api_key",
  authToken: "grounded-rag:auth_token",
  authEmail: "grounded-rag:auth_email",
  theme: "grounded-rag:theme",
  locale: "grounded-rag:locale",
  course: "grounded-rag:course",
  sessionId: "grounded-rag:session_id",
} as const;

/** Read a string from localStorage, returning `fallback` when unavailable. */
export function readLocal(key: string, fallback = ""): string {
  if (typeof window === "undefined") return fallback;
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Write a string to localStorage, ignoring quota/availability errors. */
export function writeLocal(key: string, value: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* ignore: storage may be disabled */
  }
}

/** Generate a short, readable, unique student id for a fresh browser. */
export function generateStudentId(): string {
  const rand =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().slice(0, 8)
      : Math.random().toString(36).slice(2, 10);
  return `student-${rand}`;
}
