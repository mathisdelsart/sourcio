"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { KEYS, readLocal, writeLocal } from "@/lib/storage";

/** Supported UI locales. UI strings only — never API-returned content. */
export type Locale = "en" | "fr";

/** Stable, English dictionary. Keys are stable ids; English doubles as fallback. */
const en = {
  // Header / chrome
  "app.name": "Grounded Tutor",
  "app.tagline": "Answers only from your course",
  "header.signIn": "Sign in",
  "footer.tagline": "Grounded retrieval · citations by construction · honest refusals",

  // Language toggle
  "lang.label": "Language",
  "lang.switchToFrench": "Switch to French",
  "lang.switchToEnglish": "Switch to English",

  // Theme toggle
  "theme.switchToLight": "Switch to light theme",
  "theme.switchToDark": "Switch to dark theme",

  // Hero
  "hero.title": "Grounded Tutor",
  "hero.description":
    "An AI tutor grounded strictly in your own course material — always cited, refuses what it can't support.",
  "hero.principles": "Key principles",
  "hero.chip.grounded": "Grounded",
  "hero.chip.cited": "Cited",
  "hero.chip.refuses": "Refuses to hallucinate",

  // Tabs
  "tabs.aria": "Tutor sections",
  "tabs.ask": "Ask",
  "tabs.reexplain": "Re-explain",
  "tabs.exercise": "Exercise",
  "tabs.grade": "Grade",
  "tabs.quiz": "Quiz",
  "tabs.history": "History",

  // Health badge
  "health.online": "Backend online",
  "health.offline": "Backend offline",
  "health.checking": "Checking…",

  // Auth menu
  "auth.aria": "Account",
  "auth.signIn": "Sign in",
  "auth.register": "Register",
  "auth.signOut": "Sign out",
  "auth.createAccount": "Create account",
  "auth.signedInAs": "Signed in as",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.passwordHint": "At least 8 characters.",
  "auth.accountCreated": "Account created. Signing you in…",
  "auth.signedInToast": "Signed in as {email}.",
  "auth.signedOutToast": "Signed out.",
  "auth.failed": "Authentication failed.",

  // Settings panel
  "settings.title": "Settings",
  "settings.studentId": "Student id",
  "settings.studentIdHint": "Identifies you to the tutor. Persisted in this browser.",
  "settings.baseUrl": "API base URL",
  "settings.baseUrlHint": "Overrides NEXT_PUBLIC_API_BASE_URL. Leave empty to use the default.",
  "settings.apiKey": "API key",
  "settings.apiKeyHint": "Optional — sent as the X-API-Key header when set.",
  "settings.apiKeyPlaceholder": "(none)",
  "common.cancel": "Cancel",
  "common.save": "Save",

  // Shared
  "common.requestFailed": "Request failed.",
  "common.submitHint": "Press ⌘/Ctrl + Enter to submit.",
  "common.sources": "Sources",
  "common.noSources": "No sources cited.",
  "refusal.title": "Refused — not covered by the course",

  // Level selector
  "level.aria": "Re-explanation level",
  "level.beginner": "beginner",
  "level.intermediate": "intermediate",
  "level.advanced": "advanced",

  // Ask panel
  "ask.title": "Ask a question",
  "ask.description": "Answers come strictly from your indexed course material.",
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder": "e.g. What is the admissibility condition for a wavelet?",
  "ask.courseLabel": "Course filter",
  "ask.courseHint": "Optional — restrict retrieval to one course.",
  "ask.coursePlaceholder": "e.g. ELEC2885 Wavelet Transform",

  // Course picker
  "course.allCourses": "All courses",
  "course.loading": "Loading courses…",
  "course.fetchFailed": "Could not load courses — enter a course name.",
  "ask.chapterLabel": "Chapter filter",
  "ask.chapterHint": "Optional — restrict to a single chapter.",
  "ask.chapterPlaceholder": "e.g. Chapter 3",
  "ask.kLabel": "Sources to retrieve:",
  "ask.submit": "Ask",
  "ask.answerTitle": "Answer",
  "ask.empty.title": "No answer yet",
  "ask.empty.description": "Ask a question above to see a grounded, cited explanation.",
  "ask.reexplainPrompt": "Didn't get it? Re-explain at a level:",
  "ask.reexplain": "Re-explain",

  // Answer feedback
  "feedback.prompt": "Was this answer helpful?",
  "feedback.up": "Helpful",
  "feedback.upAria": "Mark this answer as helpful",
  "feedback.down": "Not helpful",
  "feedback.downAria": "Mark this answer as not helpful",
  "feedback.notePlaceholder": "Optional: what was wrong?",
  "feedback.send": "Send feedback",
  "feedback.thanks": "Thanks for your feedback.",
  "feedback.failed": "Could not send feedback.",

  // Re-explain panel
  "reexplain.title": "Re-explain the last answer",
  "reexplain.description":
    "Hear your most recent answer again, tuned to a different audience level.",
  "reexplain.lastAnswer": "Last answer",
  "reexplain.action": "Re-explain",
  "reexplain.resultTitle": "Re-explanation",
  "reexplain.empty.title": "Nothing re-explained yet",
  "reexplain.empty.description":
    "Pick a level and press Re-explain. Ask a question first if you have not yet.",

  // Exercise panel
  "exercise.title": "Generate an exercise",
  "exercise.description": "A practice problem grounded in the course, using its notation.",
  "exercise.notionLabel": "Notion to practice",
  "exercise.notionPlaceholder": "e.g. continuous wavelet transform",
  "exercise.generate": "Generate",
  "exercise.resultTitle": "Exercise",
  "exercise.empty.title": "No exercise yet",
  "exercise.empty.description": "Enter a notion above to generate a course-grounded problem.",
  "exercise.solveHint":
    "Solve it, then head to the Grade tab — your answer is linked to this exercise.",

  // Grade panel
  "grade.title": "Grade your answer",
  "grade.description": "An LLM judge scores your answer and explains why.",
  "grade.against": "Grading against exercise #{id}",
  "grade.answerLabel": "Your answer",
  "grade.answerPlaceholder": "Write your solution here…",
  "grade.submit": "Grade",
  "grade.verdictTitle": "Verdict",
  "grade.empty.title": "Not graded yet",
  "grade.empty.description": "Submit an answer above to get a score and feedback.",
  "grade.score": "Score",

  // Quiz panel
  "quiz.title": "Generate a quiz",
  "quiz.description":
    "A set of practice questions grounded in the course, using its notation.",
  "quiz.notionLabel": "Notion to quiz on",
  "quiz.notionPlaceholder": "e.g. continuous wavelet transform",
  "quiz.questions": "Questions",
  "quiz.generate": "Generate",
  "quiz.resultTitle": "Quiz",
  "quiz.total": "Total {total}/100",
  "quiz.empty.title": "No quiz yet",
  "quiz.empty.description": "Enter a notion above to generate a course-grounded quiz.",
  "quiz.refused": "This notion is not covered by the course material.",
  "quiz.answerLabel": "Your answer",
  "quiz.answerPlaceholder": "Write your solution here…",
  "quiz.gradeAnswer": "Grade answer",
  "quiz.score": "Score",

  // History panel
  "history.title": "Conversation history",
  "history.description": "Your recent turns with the tutor, oldest first.",
  "history.refresh": "Refresh",
  "history.empty.title": "No history yet",
  "history.empty.description":
    "Ask a question or generate an exercise — your turns will appear here.",

  // Export actions
  "export.copy": "Copy as Markdown",
  "export.copyAria": "Copy answer and citations as Markdown",
  "export.download": "Download .md",
  "export.downloadAria": "Download answer and citations as a Markdown file",
  "export.copied": "Copied to clipboard.",
  "export.copyFailed": "Could not copy to clipboard.",
  "export.downloadStarted": "Download started.",
  "export.downloadFailed": "Could not prepare the download.",

  // Misc
  "common.loading": "Loading",
} as const;

/** Translation key set, derived from the English dictionary. */
export type TranslationKey = keyof typeof en;

/** French dictionary. Same keys as `en`; values are translations. */
const fr: Record<TranslationKey, string> = {
  // Header / chrome
  "app.name": "Grounded Tutor",
  "app.tagline": "Répond uniquement à partir de votre cours",
  "header.signIn": "Se connecter",
  "footer.tagline":
    "Récupération ancrée · citations par construction · refus honnêtes",

  // Language toggle
  "lang.label": "Langue",
  "lang.switchToFrench": "Passer en français",
  "lang.switchToEnglish": "Passer en anglais",

  // Theme toggle
  "theme.switchToLight": "Passer en thème clair",
  "theme.switchToDark": "Passer en thème sombre",

  // Hero
  "hero.title": "Grounded Tutor",
  "hero.description":
    "Un tuteur IA strictement ancré dans votre propre matériel de cours — toujours cité, refuse ce qu'il ne peut pas étayer.",
  "hero.principles": "Principes clés",
  "hero.chip.grounded": "Ancré",
  "hero.chip.cited": "Cité",
  "hero.chip.refuses": "Refuse d'halluciner",

  // Tabs
  "tabs.aria": "Sections du tuteur",
  "tabs.ask": "Demander",
  "tabs.reexplain": "Réexpliquer",
  "tabs.exercise": "Exercice",
  "tabs.grade": "Corriger",
  "tabs.quiz": "Quiz",
  "tabs.history": "Historique",

  // Health badge
  "health.online": "Backend en ligne",
  "health.offline": "Backend hors ligne",
  "health.checking": "Vérification…",

  // Auth menu
  "auth.aria": "Compte",
  "auth.signIn": "Se connecter",
  "auth.register": "S'inscrire",
  "auth.signOut": "Se déconnecter",
  "auth.createAccount": "Créer un compte",
  "auth.signedInAs": "Connecté en tant que",
  "auth.email": "E-mail",
  "auth.password": "Mot de passe",
  "auth.passwordHint": "Au moins 8 caractères.",
  "auth.accountCreated": "Compte créé. Connexion en cours…",
  "auth.signedInToast": "Connecté en tant que {email}.",
  "auth.signedOutToast": "Déconnecté.",
  "auth.failed": "Échec de l'authentification.",

  // Settings panel
  "settings.title": "Paramètres",
  "settings.studentId": "Identifiant étudiant",
  "settings.studentIdHint":
    "Vous identifie auprès du tuteur. Conservé dans ce navigateur.",
  "settings.baseUrl": "URL de base de l'API",
  "settings.baseUrlHint":
    "Remplace NEXT_PUBLIC_API_BASE_URL. Laisser vide pour utiliser la valeur par défaut.",
  "settings.apiKey": "Clé API",
  "settings.apiKeyHint": "Optionnel — envoyée comme en-tête X-API-Key si définie.",
  "settings.apiKeyPlaceholder": "(aucune)",
  "common.cancel": "Annuler",
  "common.save": "Enregistrer",

  // Shared
  "common.requestFailed": "La requête a échoué.",
  "common.submitHint": "Appuyez sur ⌘/Ctrl + Entrée pour envoyer.",
  "common.sources": "Sources",
  "common.noSources": "Aucune source citée.",
  "refusal.title": "Refusé — non couvert par le cours",

  // Level selector
  "level.aria": "Niveau de réexplication",
  "level.beginner": "débutant",
  "level.intermediate": "intermédiaire",
  "level.advanced": "avancé",

  // Ask panel
  "ask.title": "Poser une question",
  "ask.description":
    "Les réponses proviennent strictement de votre matériel de cours indexé.",
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder":
    "ex. Quelle est la condition d'admissibilité pour une ondelette ?",
  "ask.courseLabel": "Filtre par cours",
  "ask.courseHint": "Optionnel — restreindre la récupération à un seul cours.",
  "ask.coursePlaceholder": "ex. ELEC2885 Wavelet Transform",

  // Course picker
  "course.allCourses": "Tous les cours",
  "course.loading": "Chargement des cours…",
  "course.fetchFailed": "Impossible de charger les cours — saisissez un nom de cours.",
  "ask.chapterLabel": "Filtre par chapitre",
  "ask.chapterHint": "Optionnel — restreindre à un seul chapitre.",
  "ask.chapterPlaceholder": "ex. Chapitre 3",
  "ask.kLabel": "Sources à récupérer :",
  "ask.submit": "Demander",
  "ask.answerTitle": "Réponse",
  "ask.empty.title": "Pas encore de réponse",
  "ask.empty.description":
    "Posez une question ci-dessus pour voir une explication ancrée et citée.",
  "ask.reexplainPrompt": "Pas compris ? Réexpliquer à un niveau :",
  "ask.reexplain": "Réexpliquer",

  // Answer feedback
  "feedback.prompt": "Cette réponse vous a-t-elle été utile ?",
  "feedback.up": "Utile",
  "feedback.upAria": "Marquer cette réponse comme utile",
  "feedback.down": "Pas utile",
  "feedback.downAria": "Marquer cette réponse comme non utile",
  "feedback.notePlaceholder": "Optionnel : qu'est-ce qui n'allait pas ?",
  "feedback.send": "Envoyer le retour",
  "feedback.thanks": "Merci pour votre retour.",
  "feedback.failed": "Impossible d'envoyer le retour.",

  // Re-explain panel
  "reexplain.title": "Réexpliquer la dernière réponse",
  "reexplain.description":
    "Réécoutez votre réponse la plus récente, adaptée à un autre niveau d'audience.",
  "reexplain.lastAnswer": "Dernière réponse",
  "reexplain.action": "Réexpliquer",
  "reexplain.resultTitle": "Réexplication",
  "reexplain.empty.title": "Rien de réexpliqué pour l'instant",
  "reexplain.empty.description":
    "Choisissez un niveau et appuyez sur Réexpliquer. Posez d'abord une question si ce n'est pas déjà fait.",

  // Exercise panel
  "exercise.title": "Générer un exercice",
  "exercise.description":
    "Un problème d'entraînement ancré dans le cours, utilisant sa notation.",
  "exercise.notionLabel": "Notion à travailler",
  "exercise.notionPlaceholder": "ex. transformée en ondelettes continue",
  "exercise.generate": "Générer",
  "exercise.resultTitle": "Exercice",
  "exercise.empty.title": "Pas encore d'exercice",
  "exercise.empty.description":
    "Saisissez une notion ci-dessus pour générer un problème ancré dans le cours.",
  "exercise.solveHint":
    "Résolvez-le, puis allez à l'onglet Corriger — votre réponse est liée à cet exercice.",

  // Grade panel
  "grade.title": "Corriger votre réponse",
  "grade.description": "Un juge LLM note votre réponse et explique pourquoi.",
  "grade.against": "Correction selon l'exercice #{id}",
  "grade.answerLabel": "Votre réponse",
  "grade.answerPlaceholder": "Rédigez votre solution ici…",
  "grade.submit": "Corriger",
  "grade.verdictTitle": "Verdict",
  "grade.empty.title": "Pas encore corrigé",
  "grade.empty.description":
    "Soumettez une réponse ci-dessus pour obtenir une note et un retour.",
  "grade.score": "Note",

  // Quiz panel
  "quiz.title": "Générer un quiz",
  "quiz.description":
    "Un ensemble de questions d'entraînement ancrées dans le cours, utilisant sa notation.",
  "quiz.notionLabel": "Notion à tester",
  "quiz.notionPlaceholder": "ex. transformée en ondelettes continue",
  "quiz.questions": "Questions",
  "quiz.generate": "Générer",
  "quiz.resultTitle": "Quiz",
  "quiz.total": "Total {total}/100",
  "quiz.empty.title": "Pas encore de quiz",
  "quiz.empty.description":
    "Saisissez une notion ci-dessus pour générer un quiz ancré dans le cours.",
  "quiz.refused": "Cette notion n'est pas couverte par le matériel de cours.",
  "quiz.answerLabel": "Votre réponse",
  "quiz.answerPlaceholder": "Rédigez votre solution ici…",
  "quiz.gradeAnswer": "Corriger la réponse",
  "quiz.score": "Note",

  // History panel
  "history.title": "Historique de conversation",
  "history.description": "Vos échanges récents avec le tuteur, du plus ancien au plus récent.",
  "history.refresh": "Actualiser",
  "history.empty.title": "Pas encore d'historique",
  "history.empty.description":
    "Posez une question ou générez un exercice — vos échanges apparaîtront ici.",

  // Export actions
  "export.copy": "Copier en Markdown",
  "export.copyAria": "Copier la réponse et les citations en Markdown",
  "export.download": "Télécharger .md",
  "export.downloadAria":
    "Télécharger la réponse et les citations dans un fichier Markdown",
  "export.copied": "Copié dans le presse-papiers.",
  "export.copyFailed": "Impossible de copier dans le presse-papiers.",
  "export.downloadStarted": "Téléchargement démarré.",
  "export.downloadFailed": "Impossible de préparer le téléchargement.",

  // Misc
  "common.loading": "Chargement",
};

const DICTIONARIES: Record<Locale, Record<TranslationKey, string>> = { en, fr };

/** Pick a sensible default locale from the browser language (fr → fr, else en). */
function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const lang = (navigator.language || "").toLowerCase();
  return lang.startsWith("fr") ? "fr" : "en";
}

/** Resolve the persisted locale, falling back to browser detection. */
function resolveLocale(): Locale {
  const stored = readLocal(KEYS.locale);
  if (stored === "en" || stored === "fr") return stored;
  return detectLocale();
}

/**
 * Translate `key` for `locale`, substituting `{name}` placeholders from `vars`.
 * Missing keys fall back to the English value, then to the raw id — never throws.
 */
function translate(
  locale: Locale,
  key: TranslationKey,
  vars?: Record<string, string | number>,
): string {
  const dict = DICTIONARIES[locale] ?? en;
  let value: string = dict[key] ?? en[key] ?? key;
  if (vars) {
    for (const [name, replacement] of Object.entries(vars)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
  }
  return value;
}

interface I18nContextValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: TranslationKey, vars?: Record<string, string | number>) => string;
}

const I18nContext = createContext<I18nContextValue | null>(null);

/**
 * Provides the active locale + translator. The initial render uses the default
 * (`en`) so SSR and the first client paint match; the persisted/detected locale
 * is resolved in an effect on mount, mirroring the theme's no-flash approach.
 */
export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>("en");

  useEffect(() => {
    setLocaleState(resolveLocale());
  }, []);

  // Keep <html lang> in sync for accessibility once a locale is resolved.
  useEffect(() => {
    if (typeof document !== "undefined") {
      document.documentElement.lang = locale;
    }
  }, [locale]);

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next);
    writeLocal(KEYS.locale, next);
  }, []);

  const value = useMemo<I18nContextValue>(
    () => ({
      locale,
      setLocale,
      t: (key, vars) => translate(locale, key, vars),
    }),
    [locale, setLocale],
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

/**
 * Access the translator and locale. Falls back to English with no persistence
 * when used outside the provider, so components never crash in isolation.
 */
export function useT(): I18nContextValue {
  const ctx = useContext(I18nContext);
  if (ctx) return ctx;
  return {
    locale: "en",
    setLocale: () => {},
    t: (key, vars) => translate("en", key, vars),
  };
}
