/** Small, SSR-safe localStorage helpers used for client-persisted preferences. */

const PREFIX = "sourcio:";
/** The pre-rename prefix. Kept only so existing browsers can be migrated once. */
const LEGACY_PREFIX = "grounded-rag:";

const NAMES = [
  "student_id",
  "base_url",
  "api_key",
  // The visitor's own OpenAI key. When set it is sent on every request so all
  // LLM calls (Ask, re-explain, exercises, quizzes, grading, the router and
  // scanned-PDF import) run on their premium model. Kept in the browser only,
  // never stored on the server; cleared on sign-out.
  "openai_key",
  "auth_token",
  "auth_username",
  "theme",
  "locale",
  "course",
  "session_id",
  "sources_max",
  "active_ask_job",
] as const;

export const KEYS = {
  studentId: `${PREFIX}student_id`,
  baseUrl: `${PREFIX}base_url`,
  apiKey: `${PREFIX}api_key`,
  openaiKey: `${PREFIX}openai_key`,
  authToken: `${PREFIX}auth_token`,
  authUsername: `${PREFIX}auth_username`,
  theme: `${PREFIX}theme`,
  locale: `${PREFIX}locale`,
  course: `${PREFIX}course`,
  sessionId: `${PREFIX}session_id`,
  sourcesMax: `${PREFIX}sources_max`,
  activeAskJob: `${PREFIX}active_ask_job`,
} as const;

/**
 * Carry pre-rename values over to the new key prefix, once.
 *
 * The project was renamed grounded-rag -> sourcio. These keys hold the auth
 * token, the student id and every preference, so simply renaming them would sign
 * out every existing visitor and drop their settings on the next deploy — a
 * rename is not supposed to be a logout. Each value is copied only when the new
 * key is absent, so this never overwrites fresher state, and it is a no-op once
 * every browser has been through it.
 */
function migrateLegacyKeys(): void {
  if (typeof window === "undefined") return;
  try {
    for (const name of NAMES) {
      const legacy = window.localStorage.getItem(`${LEGACY_PREFIX}${name}`);
      if (legacy !== null && window.localStorage.getItem(`${PREFIX}${name}`) === null) {
        window.localStorage.setItem(`${PREFIX}${name}`, legacy);
      }
      window.localStorage.removeItem(`${LEGACY_PREFIX}${name}`);
    }
  } catch {
    /* ignore: storage may be disabled */
  }
}

migrateLegacyKeys();

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
