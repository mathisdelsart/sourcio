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
export type Locale = "en" | "fr" | "nl";

/** Stable, English dictionary. Keys are stable ids; English doubles as fallback. */
const en = {
  // Header / chrome
  "app.name": "Sourcio",
  "app.tagline": "Answers only from your course",
  "header.signIn": "Sign in",

  // Language toggle
  "lang.label": "Language",

  // Hero
  "hero.description":
    "Index your slides and notes once, then ask in plain language. Every answer is backed by a citation, or honestly refused when the course doesn't cover it.",
  "hero.cta": "Try it",
  "hero.ctaAria": "Scroll to the tutor",
  "hero.principles": "Key principles",
  // Two-tone headline: a leading part in ink, an emphasized part in brand.
  "hero.headline.lead": "An AI tutor grounded in your course —",
  "hero.headline.accent": "always cited, never invented.",
  // Trust badges row — the keywords Sourcio leads with.
  "hero.badge.cited": "Always cited",
  "hero.badge.refuses": "Never invented",
  "hero.badge.fromCourse": "From your courses",
  "hero.badge.verifiable": "100% verifiable",
  // Right-side answer-preview mock card.
  "hero.preview.question": "What does the Pythagorean theorem state?",
  "hero.preview.answer":
    "In a right triangle, the square of the hypotenuse equals the sum of the squares of the other two sides: a² + b² = c².",
  "hero.preview.citation": "(Mathematics, Ch. 3, p.21)",
  "hero.preview.refusal": "Not in the course material.",
  // App-window mockup (right of the hero).
  "hero.app.context": "Mathematics · Chapter 3",
  "hero.app.tab.ask": "Ask",
  "hero.app.tab.exercise": "Exercise",
  "hero.app.tab.grade": "Grade",
  "hero.app.answered": "Answered from your material",
  "hero.app.refusalQuestion": "What's the weather tomorrow?",

  // Stats band — benefit-first figures, no internal jargon.
  "stats.eyebrow": "Why students trust it",
  "stats.title": "Built for answers you can rely on",
  "stats.subtitle":
    "Every answer comes from your own courses and shows where it's from — so you can revise without second-guessing.",
  "stats.cited.value": "100%",
  "stats.cited.label": "Answers cited — never made up",
  "stats.fromCourse.value": "82%",
  "stats.fromCourse.label": "Questions answered straight from your own courses",
  "stats.tools.value": "8",
  "stats.tools.label": "Ways to study: ask, quiz, practice, grade and more",
  "stats.free.value": "0 €",
  "stats.free.label": "To get started — no credit card needed",

  // How it works
  "how.eyebrow": "How it works",
  "how.title": "From your course to a cited answer",
  "how.subtitle":
    "Three steps from raw slides to an answer you can trust — add once, ask anything, get the source.",
  "how.step1.title": "Add your course",
  "how.step1.body":
    "Drop in your slides, notes and exercises. They become a private space only your tutor can read.",
  "how.step2.title": "Ask your questions",
  "how.step2.body":
    "Ask the way you'd ask a tutor. It pulls the most relevant passages straight from your own material.",
  "how.step3.title": "A cited answer, or a refusal",
  "how.step3.body":
    "Each answer shows its exact source. If your course doesn't cover it, the tutor says so instead of guessing.",

  // Features
  "features.eyebrow": "Why it's different",
  "features.title": "Reliable answers, every time",
  "features.subtitle":
    "Every answer comes from your course and shows its source — so you can revise with peace of mind.",
  "features.cited.title": "Every answer cites its source",
  "features.cited.body":
    "You always see where an answer comes from — the course, the chapter, the page. Never an answer out of nowhere.",
  "features.refusal.title": "It refuses rather than invent",
  "features.refusal.body":
    "If the answer isn't in your course, the tutor says so honestly instead of guessing.",
  "features.retrieval.title": "It finds the right passage",
  "features.retrieval.body":
    "Ask in plain language and the tutor pulls the exact extract from your course that answers you.",
  "features.private.title": "Your courses stay private",
  "features.private.body":
    "Your material stays yours — nothing is shared or reused anywhere else.",
  "features.quiz.title": "Practice and revise",
  "features.quiz.body":
    "Generate exercises and quizzes from your courses, and revise each notion at the right moment.",
  "features.bilingual.title": "Multilingual",
  "features.bilingual.body": "Works with your courses in French, English and Dutch.",
  // Mini visual inside the highlighted bento tile.
  "features.cited.demo.answer": "…so a² + b² = c²",
  "features.cited.demo.chip": "(Mathematics, Ch. 3, p.21)",

  // Landing CTA / footer
  "landing.cta.title": "Ready to revise from your own course?",
  "landing.cta.body":
    "No setup to read this far. Open the tutor below, point it at your material, and ask your first question.",
  "landing.cta.button": "Start now",
  "landing.footer.tagline": "An AI tutor grounded strictly in your course — cited, or honest about what it can't answer.",
  "footer.explore": "Explore",
  "footer.link.how": "How it works",
  "footer.link.features": "Features",
  "footer.link.tool": "Open the tutor",
  "footer.credit": "Sourcio — built by Mathis Delsart.",

  // Tabs
  "tabs.aria": "Tutor sections",
  "tabs.ask": "Ask",
  "tabs.reexplain": "Re-explain",
  "tabs.exercise": "Exercise",
  "tabs.grade": "Grade",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Threads",
  "tabs.history": "History",
  "tabs.review": "Review",
  // Documents
  "tabs.documents": "Documents",

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

  // Source excerpt modal (opened from a citation chip)
  "source.view": "View the source",
  "source.title": "Source excerpt",
  "source.close": "Close",
  "source.failed": "Could not load the source.",

  // Level selector
  "level.aria": "Re-explanation level",
  "level.beginner": "beginner",
  "level.intermediate": "intermediate",
  "level.advanced": "advanced",

  // Ask panel
  "ask.title": "Ask a question",
  "ask.description": "Answers come strictly from your indexed course material.",
  // Pre-filled example (mirrors the hero) so the tool is instantly clear.
  "ask.example.question": "What does the Pythagorean theorem state?",
  "ask.example.course": "Mathematics",
  "ask.example.chapter": "Chapter 3",
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder": "e.g. What does the Pythagorean theorem state?",
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
    "Solve it, then grade your answer just below — it is linked to this exercise.",

  // Grade panel
  "grade.title": "Correct your answer",
  "grade.description":
    "Get a detailed correction: a score, what you got right, what to fix, and a complete model answer.",
  "grade.against": "Grading against exercise #{id}",
  "grade.answerLabel": "Your answer",
  "grade.answerPlaceholder": "Write your solution here…",
  "grade.submit": "Grade",
  "grade.verdictTitle": "Correction",
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
  "quiz.gradeAll": "Grade all",
  "quiz.finalScore": "Final score",
  "quiz.recommendationTitle": "Recommendation",

  // History panel
  "history.title": "Conversation history",
  "history.description": "Your turns with the tutor, grouped by thread.",
  "history.refresh": "Refresh",
  "history.empty.title": "No history yet",
  "history.empty.description":
    "Ask a question or generate an exercise — your turns will appear here.",
  "history.unthreaded": "Unthreaded",
  "history.unthreadedHint": "Turns not attached to any thread.",
  "history.turnCount": "{count} messages",

  // Threads (conversation sessions)
  "threads.title": "Conversation threads",
  "threads.description":
    "Group your questions into threads. The active thread is attached to new questions in the Ask tab.",
  "threads.refresh": "Refresh",
  "threads.list.title": "Threads",
  "threads.new": "New thread",
  "threads.newTitleLabel": "Thread title",
  "threads.newTitlePlaceholder": "Optional — e.g. Wavelet basics",
  "threads.create": "Create",
  "threads.created": "Thread created.",
  "threads.createFailed": "Could not create the thread.",
  "threads.none": "All history (unthreaded)",
  "threads.noneHint": "New questions are not attached to any thread.",
  "threads.untitled": "Untitled thread",
  "threads.active": "Active",
  "threads.activeBanner": "New questions are attached to this thread.",
  "threads.select": "Select thread {title}",
  "threads.empty.title": "No threads yet",
  "threads.empty.description":
    "Create a thread to group related questions, or keep asking without one.",
  "threads.messages.title": "Thread messages",
  "threads.messages.empty.title": "No messages in this thread yet",
  "threads.messages.empty.description":
    "Select this thread, then ask a question in the Ask tab to start it.",
  "threads.loadFailed": "Could not load threads.",
  "threads.messagesFailed": "Could not load the thread's messages.",

  // Review panel (spaced repetition)
  "review.title": "Spaced repetition",
  "review.description":
    "Rate how well you recalled each notion. Your rating reschedules it for the right time.",
  "review.refresh": "Refresh",
  "review.dueTitle": "Due now",
  "review.dueCount": "{count} due",
  "review.add.title": "Add a notion",
  "review.add.label": "Notion to review",
  "review.add.placeholder": "e.g. continuous wavelet transform",
  "review.add.button": "Add",
  "review.add.hint": "Adds the notion to your review queue, due immediately.",
  "review.added": "Added “{notion}” to your review queue.",
  "review.rateLabel": "How well did you recall this?",
  "review.rate.again": "Again",
  "review.rate.hard": "Hard",
  "review.rate.good": "Good",
  "review.rate.easy": "Easy",
  "review.rate.againAria": "Rate “{notion}” as forgotten",
  "review.rate.hardAria": "Rate “{notion}” as hard",
  "review.rate.goodAria": "Rate “{notion}” as good",
  "review.rate.easyAria": "Rate “{notion}” as easy",
  "review.rescheduled": "“{notion}” — next review in {days}.",
  "review.day": "1 day",
  "review.days": "{days} days",
  "review.empty.title": "Nothing due — well done.",
  "review.empty.description":
    "You're all caught up. Add a notion above to start tracking it.",
  "review.helper":
    "Spaced repetition shows each notion just before you would forget it. Rate your recall (Again, Hard, Good, Easy) and it is rescheduled for the optimal time.",

  // Export actions
  "export.copy": "Copy as Markdown",
  "export.copyAria": "Copy answer and citations as Markdown",
  "export.download": "Download .md",
  "export.downloadAria": "Download answer and citations as a Markdown file",
  "export.copied": "Copied to clipboard.",
  "export.copyFailed": "Could not copy to clipboard.",
  "export.downloadStarted": "Download started.",
  "export.downloadFailed": "Could not prepare the download.",

  // Documents
  "doc.upload.title": "Add course material",
  "doc.upload.description":
    "Upload a PDF, Markdown or text file. It is indexed and becomes searchable in the tutor.",
  "doc.upload.file": "File",
  "doc.upload.fileHint": "PDF, Markdown (.md) or text (.txt).",
  "doc.upload.course": "Course",
  "doc.upload.coursePlaceholder": "e.g. Wavelet Transform",
  "doc.upload.chapter": "Chapter (optional)",
  "doc.upload.chapterHint": "Groups the material; leave empty for none.",
  "doc.upload.chapterPlaceholder": "e.g. Chapter 1",
  "doc.upload.button": "Upload & index",
  "doc.upload.success": "Indexed {pages} page(s) into “{course}”.",
  "doc.library.title": "Indexed material",
  "doc.library.description": "Everything currently searchable, by course and chapter.",
  "doc.refresh": "Refresh",
  "doc.empty.title": "Nothing indexed yet.",
  "doc.empty.description": "Upload a file above to make it searchable in the tutor.",
  "doc.pageCount": "{count} page(s)",
  "doc.uncategorized": "Uncategorized",
  "doc.delete.course": "Delete course",
  "doc.delete.chapter": "Delete",
  "doc.delete.confirm": "Delete “{target}” from the index? This cannot be undone.",
  "doc.delete.success": "Removed {count} item(s) from “{target}”.",
  "doc.progress.starting": "Preparing…",
  "doc.progress.pages": "{done} / {total} pages",
  "doc.progress.elapsed": "Elapsed {time}",
  "doc.progress.eta": "~{time} left",
  "doc.progress.skipped": "{count} already indexed",
  "doc.progress.done": "Done — {indexed} pages indexed.",
  "doc.progress.error": "Import failed: {message}",
  "doc.upToDate": "Up to date",
  "doc.viewFailed": "Could not open the file.",
  "doc.delete.confirmShort": "Delete?",
  "doc.delete.confirmYes": "Yes, delete",

  // Misc
  "common.loading": "Loading",
} as const;

/** Translation key set, derived from the English dictionary. */
export type TranslationKey = keyof typeof en;

/** French dictionary. Same keys as `en`; values are translations. */
const fr: Record<TranslationKey, string> = {
  // Header / chrome
  "app.name": "Sourcio",
  "app.tagline": "Répond uniquement à partir de votre cours",
  "header.signIn": "Se connecter",

  // Language toggle
  "lang.label": "Langue",

  // Hero
  "hero.description":
    "Indexez vos slides et vos notes une seule fois, puis posez vos questions en langage naturel. Chaque réponse est étayée par une citation, ou honnêtement refusée si le cours ne la couvre pas.",
  "hero.cta": "Essayer",
  "hero.ctaAria": "Faire défiler jusqu'au tuteur",
  "hero.principles": "Principes clés",
  // Two-tone headline: a leading part in ink, an emphasized part in brand.
  "hero.headline.lead": "Un tuteur IA ancré dans votre cours —",
  "hero.headline.accent": "toujours cité, jamais inventé.",
  // Trust badges row — the keywords Sourcio leads with.
  "hero.badge.cited": "Toujours cité",
  "hero.badge.refuses": "Jamais inventé",
  "hero.badge.fromCourse": "Depuis vos cours",
  "hero.badge.verifiable": "100% vérifiable",
  // Right-side answer-preview mock card.
  "hero.preview.question": "Que dit le théorème de Pythagore ?",
  "hero.preview.answer":
    "Dans un triangle rectangle, le carré de l'hypoténuse est égal à la somme des carrés des deux autres côtés : a² + b² = c².",
  "hero.preview.citation": "(Mathématiques, Chap. 3, p.21)",
  "hero.preview.refusal": "Absent du matériel de cours.",
  // App-window mockup (right of the hero).
  "hero.app.context": "Mathématiques · Chapitre 3",
  "hero.app.tab.ask": "Demander",
  "hero.app.tab.exercise": "Exercice",
  "hero.app.tab.grade": "Corriger",
  "hero.app.answered": "Répondu à partir de votre matériel",
  "hero.app.refusalQuestion": "Quel temps fera-t-il demain ?",

  // Stats band — chiffres orientés bénéfice, sans jargon interne.
  "stats.eyebrow": "Pourquoi lui faire confiance",
  "stats.title": "Conçu pour des réponses fiables",
  "stats.subtitle":
    "Chaque réponse vient de vos propres cours et indique sa source — pour réviser sans douter.",
  "stats.cited.value": "100 %",
  "stats.cited.label": "Réponses citées — jamais inventées",
  "stats.fromCourse.value": "82 %",
  "stats.fromCourse.label": "Questions répondues directement depuis vos cours",
  "stats.tools.value": "8",
  "stats.tools.label": "Façons de réviser : demander, quiz, exercices, correction…",
  "stats.free.value": "0 €",
  "stats.free.label": "Pour commencer — sans carte bancaire",

  // How it works
  "how.eyebrow": "Comment ça marche",
  "how.title": "De votre cours à une réponse citée",
  "how.subtitle":
    "Trois étapes, de vos slides à une réponse fiable — ajoutez une fois, demandez tout, obtenez la source.",
  "how.step1.title": "Ajoutez votre cours",
  "how.step1.body":
    "Déposez vos slides, notes et exercices. Ils deviennent un espace privé que seul votre tuteur peut consulter.",
  "how.step2.title": "Posez vos questions",
  "how.step2.body":
    "Demandez comme à un tuteur. Il retrouve les passages les plus pertinents directement dans votre matériel.",
  "how.step3.title": "Une réponse citée, ou un refus",
  "how.step3.body":
    "Chaque réponse indique sa source exacte. Si votre cours ne le couvre pas, le tuteur le dit au lieu de deviner.",

  // Features
  "features.eyebrow": "Ce qui le distingue",
  "features.title": "Des réponses fiables, à chaque fois",
  "features.subtitle":
    "Chaque réponse vient de votre cours et indique sa source — pour réviser l'esprit tranquille.",
  "features.cited.title": "Chaque réponse cite sa source",
  "features.cited.body":
    "Vous voyez toujours d'où vient la réponse : le cours, le chapitre, la page. Jamais de réponse sortie de nulle part.",
  "features.refusal.title": "Il refuse plutôt que d'inventer",
  "features.refusal.body":
    "Si la réponse n'est pas dans votre cours, le tuteur le dit honnêtement au lieu de deviner.",
  "features.retrieval.title": "Il trouve le bon passage",
  "features.retrieval.body":
    "Posez votre question normalement : le tuteur retrouve l'extrait exact de votre cours qui y répond.",
  "features.private.title": "Vos cours restent privés",
  "features.private.body":
    "Votre matériel reste à vous — rien n'est partagé ni réutilisé ailleurs.",
  "features.quiz.title": "Entraînez-vous et révisez",
  "features.quiz.body":
    "Générez des exercices et des quiz sur vos cours, et révisez chaque notion au bon moment.",
  "features.bilingual.title": "Multilingue",
  "features.bilingual.body":
    "Fonctionne avec vos cours en français, anglais et néerlandais.",
  // Mini visual inside the highlighted bento tile.
  "features.cited.demo.answer": "…donc a² + b² = c²",
  "features.cited.demo.chip": "(Mathématiques, Chap. 3, p.21)",

  // Landing CTA / footer
  "landing.cta.title": "Prêt à réviser à partir de votre propre cours ?",
  "landing.cta.body":
    "Aucune configuration nécessaire pour en arriver là. Ouvrez le tuteur ci-dessous, pointez-le vers votre matériel et posez votre première question.",
  "landing.cta.button": "Commencer",
  "landing.footer.tagline": "Un tuteur IA strictement ancré dans votre cours — cité, ou honnête sur ce qu'il ne peut pas répondre.",
  "footer.explore": "Explorer",
  "footer.link.how": "Comment ça marche",
  "footer.link.features": "Fonctionnalités",
  "footer.link.tool": "Ouvrir le tuteur",
  "footer.credit": "Sourcio — réalisé par Mathis Delsart.",

  // Tabs
  "tabs.aria": "Sections du tuteur",
  "tabs.ask": "Demander",
  "tabs.reexplain": "Réexpliquer",
  "tabs.exercise": "Exercice",
  "tabs.grade": "Corriger",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Fils",
  "tabs.history": "Historique",
  "tabs.review": "Révision",
  // Documents
  "tabs.documents": "Documents",

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

  // Source excerpt modal (opened from a citation chip)
  "source.view": "Voir la source",
  "source.title": "Extrait de la source",
  "source.close": "Fermer",
  "source.failed": "Impossible de charger la source.",

  // Level selector
  "level.aria": "Niveau de réexplication",
  "level.beginner": "débutant",
  "level.intermediate": "intermédiaire",
  "level.advanced": "avancé",

  // Ask panel
  "ask.title": "Poser une question",
  "ask.description":
    "Les réponses proviennent strictement de votre matériel de cours indexé.",
  // Exemple pré-rempli (identique au hero) pour que l'outil soit clair d'emblée.
  "ask.example.question": "Que dit le théorème de Pythagore ?",
  "ask.example.course": "Mathématiques",
  "ask.example.chapter": "Chapitre 3",
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder": "ex. Que dit le théorème de Pythagore ?",
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
    "Résolvez-le, puis corrigez votre réponse juste en dessous — elle est liée à cet exercice.",

  // Grade panel
  "grade.title": "Corriger votre réponse",
  "grade.description":
    "Obtenez une correction détaillée : une note, ce qui est juste, ce qu'il faut corriger, et une réponse modèle complète.",
  "grade.against": "Correction selon l'exercice #{id}",
  "grade.answerLabel": "Votre réponse",
  "grade.answerPlaceholder": "Rédigez votre solution ici…",
  "grade.submit": "Corriger",
  "grade.verdictTitle": "Correction",
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
  "quiz.gradeAll": "Tout corriger",
  "quiz.finalScore": "Note finale",
  "quiz.recommendationTitle": "Recommandation",

  // History panel
  "history.title": "Historique de conversation",
  "history.description": "Vos échanges avec le tuteur, regroupés par fil.",
  "history.refresh": "Actualiser",
  "history.empty.title": "Pas encore d'historique",
  "history.empty.description":
    "Posez une question ou générez un exercice — vos échanges apparaîtront ici.",
  "history.unthreaded": "Sans fil",
  "history.unthreadedHint": "Échanges rattachés à aucun fil.",
  "history.turnCount": "{count} messages",

  // Threads (conversation sessions)
  "threads.title": "Fils de conversation",
  "threads.description":
    "Regroupez vos questions en fils. Le fil actif est rattaché aux nouvelles questions de l'onglet Demander.",
  "threads.refresh": "Actualiser",
  "threads.list.title": "Fils",
  "threads.new": "Nouveau fil",
  "threads.newTitleLabel": "Titre du fil",
  "threads.newTitlePlaceholder": "Optionnel — ex. Bases des ondelettes",
  "threads.create": "Créer",
  "threads.created": "Fil créé.",
  "threads.createFailed": "Impossible de créer le fil.",
  "threads.none": "Tout l'historique (sans fil)",
  "threads.noneHint": "Les nouvelles questions ne sont rattachées à aucun fil.",
  "threads.untitled": "Fil sans titre",
  "threads.active": "Actif",
  "threads.activeBanner": "Les nouvelles questions sont rattachées à ce fil.",
  "threads.select": "Sélectionner le fil {title}",
  "threads.empty.title": "Pas encore de fil",
  "threads.empty.description":
    "Créez un fil pour regrouper des questions liées, ou continuez sans fil.",
  "threads.messages.title": "Messages du fil",
  "threads.messages.empty.title": "Pas encore de message dans ce fil",
  "threads.messages.empty.description":
    "Sélectionnez ce fil, puis posez une question dans l'onglet Demander pour le démarrer.",
  "threads.loadFailed": "Impossible de charger les fils.",
  "threads.messagesFailed": "Impossible de charger les messages du fil.",

  // Review panel (spaced repetition)
  "review.title": "Répétition espacée",
  "review.description":
    "Évaluez votre rappel de chaque notion. Votre note la replanifie au bon moment.",
  "review.refresh": "Actualiser",
  "review.dueTitle": "À réviser",
  "review.dueCount": "{count} à réviser",
  "review.add.title": "Ajouter une notion",
  "review.add.label": "Notion à réviser",
  "review.add.placeholder": "ex. transformée en ondelettes continue",
  "review.add.button": "Ajouter",
  "review.add.hint": "Ajoute la notion à votre file de révision, à réviser immédiatement.",
  "review.added": "« {notion} » ajoutée à votre file de révision.",
  "review.rateLabel": "À quel point vous en êtes-vous souvenu ?",
  "review.rate.again": "À revoir",
  "review.rate.hard": "Difficile",
  "review.rate.good": "Bien",
  "review.rate.easy": "Facile",
  "review.rate.againAria": "Noter « {notion} » comme oubliée",
  "review.rate.hardAria": "Noter « {notion} » comme difficile",
  "review.rate.goodAria": "Noter « {notion} » comme bien",
  "review.rate.easyAria": "Noter « {notion} » comme facile",
  "review.rescheduled": "« {notion} » — prochaine révision dans {days}.",
  "review.day": "1 jour",
  "review.days": "{days} jours",
  "review.empty.title": "Rien à réviser — bravo.",
  "review.empty.description":
    "Vous êtes à jour. Ajoutez une notion ci-dessus pour commencer à la suivre.",
  "review.helper":
    "La répétition espacée présente chaque notion juste avant que vous l'oubliiez. Notez votre mémorisation (À revoir, Difficile, Bien, Facile) et elle est replanifiée au moment optimal.",

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

  // Documents
  "doc.upload.title": "Ajouter du contenu de cours",
  "doc.upload.description":
    "Importez un PDF, du Markdown ou un fichier texte. Il est indexé et devient consultable dans le tuteur.",
  "doc.upload.file": "Fichier",
  "doc.upload.fileHint": "PDF, Markdown (.md) ou texte (.txt).",
  "doc.upload.course": "Cours",
  "doc.upload.coursePlaceholder": "ex. Transformée en ondelettes",
  "doc.upload.chapter": "Chapitre (optionnel)",
  "doc.upload.chapterHint": "Regroupe le contenu ; laissez vide si aucun.",
  "doc.upload.chapterPlaceholder": "ex. Chapitre 1",
  "doc.upload.button": "Importer et indexer",
  "doc.upload.success": "{pages} page(s) indexée(s) dans « {course} ».",
  "doc.library.title": "Contenu indexé",
  "doc.library.description": "Tout ce qui est consultable, par cours et chapitre.",
  "doc.refresh": "Actualiser",
  "doc.empty.title": "Rien d’indexé pour l’instant.",
  "doc.empty.description": "Importez un fichier ci-dessus pour le rendre consultable dans le tuteur.",
  "doc.pageCount": "{count} page(s)",
  "doc.uncategorized": "Sans catégorie",
  "doc.delete.course": "Supprimer le cours",
  "doc.delete.chapter": "Supprimer",
  "doc.delete.confirm": "Supprimer « {target} » de l’index ? Cette action est irréversible.",
  "doc.delete.success": "{count} élément(s) retiré(s) de « {target} ».",
  "doc.progress.starting": "Préparation…",
  "doc.progress.pages": "{done} / {total} pages",
  "doc.progress.elapsed": "Écoulé {time}",
  "doc.progress.eta": "~{time} restant",
  "doc.progress.skipped": "{count} déjà indexées",
  "doc.progress.done": "Terminé — {indexed} pages indexées.",
  "doc.progress.error": "Échec de l'import : {message}",
  "doc.upToDate": "À jour",
  "doc.viewFailed": "Impossible d'ouvrir le fichier.",
  "doc.delete.confirmShort": "Supprimer ?",
  "doc.delete.confirmYes": "Oui, supprimer",

  // Misc
  "common.loading": "Chargement",
};

/** Dutch dictionary. Same keys as `en`; values are translations. */
const nl: Record<TranslationKey, string> = {
  // Header / chrome
  "app.name": "Sourcio",
  "app.tagline": "Antwoorden alleen uit je cursus",
  "header.signIn": "Inloggen",

  // Language toggle
  "lang.label": "Taal",

  // Hero
  "hero.description":
    "Indexeer je slides en notities één keer en stel daarna je vragen in gewone taal. Elk antwoord is onderbouwd met een bronvermelding, of wordt eerlijk geweigerd als de cursus het niet behandelt.",
  "hero.cta": "Probeer het",
  "hero.ctaAria": "Scroll naar de tutor",
  "hero.principles": "Kernprincipes",
  "hero.headline.lead": "Een AI-tutor verankerd in je cursus —",
  "hero.headline.accent": "altijd geciteerd, nooit verzonnen.",
  "hero.badge.cited": "Altijd geciteerd",
  "hero.badge.refuses": "Nooit verzonnen",
  "hero.badge.fromCourse": "Uit je eigen cursussen",
  "hero.badge.verifiable": "100% verifieerbaar",
  "hero.preview.question": "Wat zegt de stelling van Pythagoras?",
  "hero.preview.answer":
    "In een rechthoekige driehoek is het kwadraat van de schuine zijde gelijk aan de som van de kwadraten van de twee andere zijden: a² + b² = c².",
  "hero.preview.citation": "(Wiskunde, H. 3, p.21)",
  "hero.preview.refusal": "Niet in het cursusmateriaal.",
  "hero.app.context": "Wiskunde · Hoofdstuk 3",
  "hero.app.tab.ask": "Vragen",
  "hero.app.tab.exercise": "Oefening",
  "hero.app.tab.grade": "Beoordelen",
  "hero.app.answered": "Beantwoord vanuit je materiaal",
  "hero.app.refusalQuestion": "Wat voor weer wordt het morgen?",

  // Stats band
  "stats.eyebrow": "Waarom studenten erop vertrouwen",
  "stats.title": "Gebouwd voor antwoorden waarop je kunt bouwen",
  "stats.subtitle":
    "Elk antwoord komt uit je eigen cursussen en toont waar het vandaan komt — zodat je kunt studeren zonder te twijfelen.",
  "stats.cited.value": "100%",
  "stats.cited.label": "Antwoorden geciteerd — nooit verzonnen",
  "stats.fromCourse.value": "82%",
  "stats.fromCourse.label": "Vragen rechtstreeks beantwoord vanuit je eigen cursussen",
  "stats.tools.value": "8",
  "stats.tools.label": "Manieren om te studeren: vragen, quiz, oefenen, beoordelen en meer",
  "stats.free.value": "0 €",
  "stats.free.label": "Om te beginnen — geen creditcard nodig",

  // How it works
  "how.eyebrow": "Hoe het werkt",
  "how.title": "Van je cursus naar een geciteerd antwoord",
  "how.subtitle":
    "Drie stappen van ruwe slides naar een betrouwbaar antwoord — voeg één keer toe, vraag alles, krijg de bron.",
  "how.step1.title": "Voeg je cursus toe",
  "how.step1.body":
    "Zet je slides, notities en oefeningen erin. Ze worden een privéruimte die alleen je tutor kan lezen.",
  "how.step2.title": "Stel je vragen",
  "how.step2.body":
    "Vraag zoals je het een tutor zou vragen. Het haalt de meest relevante passages rechtstreeks uit je eigen materiaal.",
  "how.step3.title": "Een geciteerd antwoord, of een weigering",
  "how.step3.body":
    "Elk antwoord toont zijn exacte bron. Als je cursus het niet behandelt, zegt de tutor dat in plaats van te gokken.",

  // Features
  "features.eyebrow": "Wat het anders maakt",
  "features.title": "Betrouwbare antwoorden, elke keer",
  "features.subtitle":
    "Elk antwoord komt uit je cursus en toont zijn bron — zodat je met een gerust hart kunt studeren.",
  "features.cited.title": "Elk antwoord vermeldt zijn bron",
  "features.cited.body":
    "Je ziet altijd waar een antwoord vandaan komt — de cursus, het hoofdstuk, de pagina. Nooit een antwoord uit het niets.",
  "features.refusal.title": "Het weigert liever dan te verzinnen",
  "features.refusal.body":
    "Als het antwoord niet in je cursus staat, zegt de tutor dat eerlijk in plaats van te gokken.",
  "features.retrieval.title": "Het vindt de juiste passage",
  "features.retrieval.body":
    "Vraag in gewone taal en de tutor haalt het exacte fragment uit je cursus dat je antwoord geeft.",
  "features.private.title": "Je cursussen blijven privé",
  "features.private.body":
    "Je materiaal blijft van jou — niets wordt gedeeld of elders hergebruikt.",
  "features.quiz.title": "Oefen en herhaal",
  "features.quiz.body":
    "Genereer oefeningen en quizzen uit je cursussen, en herhaal elk begrip op het juiste moment.",
  "features.bilingual.title": "Meertalig",
  "features.bilingual.body": "Werkt met je cursussen in het Frans, Engels en Nederlands.",
  "features.cited.demo.answer": "…dus a² + b² = c²",
  "features.cited.demo.chip": "(Wiskunde, H. 3, p.21)",

  // Landing CTA / footer
  "landing.cta.title": "Klaar om vanuit je eigen cursus te studeren?",
  "landing.cta.body":
    "Geen installatie om tot hier te lezen. Open de tutor hieronder, richt hem op je materiaal en stel je eerste vraag.",
  "landing.cta.button": "Begin nu",
  "landing.footer.tagline":
    "Een AI-tutor strikt verankerd in je cursus — geciteerd, of eerlijk over wat hij niet kan beantwoorden.",
  "footer.explore": "Ontdek",
  "footer.link.how": "Hoe het werkt",
  "footer.link.features": "Functies",
  "footer.link.tool": "Open de tutor",
  "footer.credit": "Sourcio — gemaakt door Mathis Delsart.",

  // Tabs
  "tabs.aria": "Tutor-secties",
  "tabs.ask": "Vragen",
  "tabs.reexplain": "Heruitleggen",
  "tabs.exercise": "Oefening",
  "tabs.grade": "Beoordelen",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Gesprekken",
  "tabs.history": "Geschiedenis",
  "tabs.review": "Herhaling",
  // Documents
  "tabs.documents": "Documenten",

  // Health badge
  "health.online": "Backend online",
  "health.offline": "Backend offline",
  "health.checking": "Controleren…",

  // Auth menu
  "auth.aria": "Account",
  "auth.signIn": "Inloggen",
  "auth.register": "Registreren",
  "auth.signOut": "Uitloggen",
  "auth.createAccount": "Account aanmaken",
  "auth.signedInAs": "Ingelogd als",
  "auth.email": "E-mail",
  "auth.password": "Wachtwoord",
  "auth.passwordHint": "Minstens 8 tekens.",
  "auth.accountCreated": "Account aangemaakt. Je wordt ingelogd…",
  "auth.signedInToast": "Ingelogd als {email}.",
  "auth.signedOutToast": "Uitgelogd.",
  "auth.failed": "Authenticatie mislukt.",

  // Settings panel
  "settings.title": "Instellingen",
  "settings.studentId": "Student-id",
  "settings.studentIdHint": "Identificeert je bij de tutor. Bewaard in deze browser.",
  "settings.baseUrl": "API-basis-URL",
  "settings.baseUrlHint": "Overschrijft NEXT_PUBLIC_API_BASE_URL. Laat leeg voor de standaardwaarde.",
  "settings.apiKey": "API-sleutel",
  "settings.apiKeyHint": "Optioneel — verzonden als de X-API-Key-header indien ingesteld.",
  "settings.apiKeyPlaceholder": "(geen)",
  "common.cancel": "Annuleren",
  "common.save": "Opslaan",

  // Shared
  "common.requestFailed": "Verzoek mislukt.",
  "common.submitHint": "Druk op ⌘/Ctrl + Enter om te verzenden.",
  "common.sources": "Bronnen",
  "common.noSources": "Geen bronnen geciteerd.",
  "refusal.title": "Geweigerd — niet behandeld in de cursus",

  // Source excerpt modal (opened from a citation chip)
  "source.view": "Bekijk de bron",
  "source.title": "Bronfragment",
  "source.close": "Sluiten",
  "source.failed": "Kon de bron niet laden.",

  // Level selector
  "level.aria": "Niveau van heruitleg",
  "level.beginner": "beginner",
  "level.intermediate": "gemiddeld",
  "level.advanced": "gevorderd",

  // Ask panel
  "ask.title": "Stel een vraag",
  "ask.description": "Antwoorden komen strikt uit je geïndexeerde cursusmateriaal.",
  "ask.example.question": "Wat zegt de stelling van Pythagoras?",
  "ask.example.course": "Wiskunde",
  "ask.example.chapter": "Hoofdstuk 3",
  "ask.questionLabel": "Vraag",
  "ask.questionPlaceholder": "bijv. Wat zegt de stelling van Pythagoras?",
  "ask.courseLabel": "Cursusfilter",
  "ask.courseHint": "Optioneel — beperk tot één cursus.",
  "ask.coursePlaceholder": "bijv. ELEC2885 Wavelet Transform",

  // Course picker
  "course.allCourses": "Alle cursussen",
  "course.loading": "Cursussen laden…",
  "course.fetchFailed": "Kon cursussen niet laden — voer een cursusnaam in.",
  "ask.chapterLabel": "Hoofdstukfilter",
  "ask.chapterHint": "Optioneel — beperk tot één hoofdstuk.",
  "ask.chapterPlaceholder": "bijv. Hoofdstuk 3",
  "ask.kLabel": "Op te halen bronnen:",
  "ask.submit": "Vragen",
  "ask.answerTitle": "Antwoord",
  "ask.empty.title": "Nog geen antwoord",
  "ask.empty.description": "Stel hierboven een vraag voor een onderbouwde, geciteerde uitleg.",
  "ask.reexplainPrompt": "Niet begrepen? Leg opnieuw uit op niveau:",
  "ask.reexplain": "Heruitleggen",

  // Answer feedback
  "feedback.prompt": "Was dit antwoord nuttig?",
  "feedback.up": "Nuttig",
  "feedback.upAria": "Markeer dit antwoord als nuttig",
  "feedback.down": "Niet nuttig",
  "feedback.downAria": "Markeer dit antwoord als niet nuttig",
  "feedback.notePlaceholder": "Optioneel: wat klopte er niet?",
  "feedback.send": "Feedback verzenden",
  "feedback.thanks": "Bedankt voor je feedback.",
  "feedback.failed": "Kon feedback niet verzenden.",

  // Re-explain panel
  "reexplain.title": "Leg het laatste antwoord opnieuw uit",
  "reexplain.description": "Hoor je meest recente antwoord opnieuw, afgestemd op een ander niveau.",
  "reexplain.lastAnswer": "Laatste antwoord",
  "reexplain.action": "Heruitleggen",
  "reexplain.resultTitle": "Heruitleg",
  "reexplain.empty.title": "Nog niets heruitgelegd",
  "reexplain.empty.description":
    "Kies een niveau en druk op Heruitleggen. Stel eerst een vraag als je dat nog niet hebt gedaan.",

  // Exercise panel
  "exercise.title": "Genereer een oefening",
  "exercise.description": "Een oefenprobleem verankerd in de cursus, met diens notatie.",
  "exercise.notionLabel": "Te oefenen begrip",
  "exercise.notionPlaceholder": "bijv. continue wavelettransformatie",
  "exercise.generate": "Genereren",
  "exercise.resultTitle": "Oefening",
  "exercise.empty.title": "Nog geen oefening",
  "exercise.empty.description":
    "Voer hierboven een begrip in om een op de cursus gebaseerd probleem te genereren.",
  "exercise.solveHint":
    "Los het op en beoordeel je antwoord hieronder — het is gekoppeld aan deze oefening.",

  // Grade panel
  "grade.title": "Verbeter je antwoord",
  "grade.description":
    "Krijg een gedetailleerde correctie: een score, wat goed is, wat te verbeteren, en een volledig modelantwoord.",
  "grade.against": "Beoordeling t.o.v. oefening #{id}",
  "grade.answerLabel": "Jouw antwoord",
  "grade.answerPlaceholder": "Schrijf hier je oplossing…",
  "grade.submit": "Beoordelen",
  "grade.verdictTitle": "Correctie",
  "grade.empty.title": "Nog niet beoordeeld",
  "grade.empty.description": "Dien hierboven een antwoord in voor een score en feedback.",
  "grade.score": "Score",

  // Quiz panel
  "quiz.title": "Genereer een quiz",
  "quiz.description": "Een reeks oefenvragen verankerd in de cursus, met diens notatie.",
  "quiz.notionLabel": "Begrip om over te quizzen",
  "quiz.notionPlaceholder": "bijv. continue wavelettransformatie",
  "quiz.questions": "Vragen",
  "quiz.generate": "Genereren",
  "quiz.resultTitle": "Quiz",
  "quiz.total": "Totaal {total}/100",
  "quiz.empty.title": "Nog geen quiz",
  "quiz.empty.description":
    "Voer hierboven een begrip in om een op de cursus gebaseerde quiz te genereren.",
  "quiz.refused": "Dit begrip wordt niet behandeld in het cursusmateriaal.",
  "quiz.answerLabel": "Jouw antwoord",
  "quiz.answerPlaceholder": "Schrijf hier je oplossing…",
  "quiz.gradeAnswer": "Antwoord beoordelen",
  "quiz.score": "Score",
  "quiz.gradeAll": "Alles beoordelen",
  "quiz.finalScore": "Eindscore",
  "quiz.recommendationTitle": "Aanbeveling",

  // History panel
  "history.title": "Gespreksgeschiedenis",
  "history.description": "Je beurten met de tutor, gegroepeerd per gesprek.",
  "history.refresh": "Vernieuwen",
  "history.empty.title": "Nog geen geschiedenis",
  "history.empty.description":
    "Stel een vraag of genereer een oefening — je beurten verschijnen hier.",
  "history.unthreaded": "Zonder gesprek",
  "history.unthreadedHint": "Beurten die aan geen enkel gesprek zijn gekoppeld.",
  "history.turnCount": "{count} berichten",

  // Threads (conversation sessions)
  "threads.title": "Gesprekken",
  "threads.description":
    "Groepeer je vragen in gesprekken. Het actieve gesprek wordt gekoppeld aan nieuwe vragen op het tabblad Vragen.",
  "threads.refresh": "Vernieuwen",
  "threads.list.title": "Gesprekken",
  "threads.new": "Nieuw gesprek",
  "threads.newTitleLabel": "Gesprekstitel",
  "threads.newTitlePlaceholder": "Optioneel — bijv. Wavelet-basis",
  "threads.create": "Aanmaken",
  "threads.created": "Gesprek aangemaakt.",
  "threads.createFailed": "Kon het gesprek niet aanmaken.",
  "threads.none": "Alle geschiedenis (zonder gesprek)",
  "threads.noneHint": "Nieuwe vragen worden aan geen enkel gesprek gekoppeld.",
  "threads.untitled": "Naamloos gesprek",
  "threads.active": "Actief",
  "threads.activeBanner": "Nieuwe vragen worden aan dit gesprek gekoppeld.",
  "threads.select": "Selecteer gesprek {title}",
  "threads.empty.title": "Nog geen gesprekken",
  "threads.empty.description":
    "Maak een gesprek om verwante vragen te groeperen, of blijf vragen zonder gesprek.",
  "threads.messages.title": "Gespreksberichten",
  "threads.messages.empty.title": "Nog geen berichten in dit gesprek",
  "threads.messages.empty.description":
    "Selecteer dit gesprek en stel een vraag op het tabblad Vragen om het te starten.",
  "threads.loadFailed": "Kon gesprekken niet laden.",
  "threads.messagesFailed": "Kon de berichten van het gesprek niet laden.",

  // Review panel (spaced repetition)
  "review.title": "Gespreide herhaling",
  "review.description":
    "Beoordeel hoe goed je elk begrip onthield. Je beoordeling plant het opnieuw op het juiste moment.",
  "review.refresh": "Vernieuwen",
  "review.dueTitle": "Nu te doen",
  "review.dueCount": "{count} te doen",
  "review.add.title": "Voeg een begrip toe",
  "review.add.label": "Te herhalen begrip",
  "review.add.placeholder": "bijv. continue wavelettransformatie",
  "review.add.button": "Toevoegen",
  "review.add.hint": "Voegt het begrip toe aan je herhalingswachtrij, direct te doen.",
  "review.added": "“{notion}” toegevoegd aan je herhalingswachtrij.",
  "review.rateLabel": "Hoe goed herinnerde je je dit?",
  "review.rate.again": "Opnieuw",
  "review.rate.hard": "Moeilijk",
  "review.rate.good": "Goed",
  "review.rate.easy": "Makkelijk",
  "review.rate.againAria": "Beoordeel “{notion}” als vergeten",
  "review.rate.hardAria": "Beoordeel “{notion}” als moeilijk",
  "review.rate.goodAria": "Beoordeel “{notion}” als goed",
  "review.rate.easyAria": "Beoordeel “{notion}” als makkelijk",
  "review.rescheduled": "“{notion}” — volgende herhaling over {days}.",
  "review.day": "1 dag",
  "review.days": "{days} dagen",
  "review.empty.title": "Niets te doen — goed gedaan.",
  "review.empty.description": "Je bent helemaal bij. Voeg hierboven een begrip toe om het te volgen.",
  "review.helper":
    "Gespreide herhaling toont elk begrip net voordat je het zou vergeten. Beoordeel je herinnering (Opnieuw, Moeilijk, Goed, Makkelijk) en het wordt op het optimale moment opnieuw ingepland.",

  // Export actions
  "export.copy": "Kopiëren als Markdown",
  "export.copyAria": "Kopieer antwoord en bronnen als Markdown",
  "export.download": ".md downloaden",
  "export.downloadAria": "Download antwoord en bronnen als Markdown-bestand",
  "export.copied": "Gekopieerd naar klembord.",
  "export.copyFailed": "Kon niet naar klembord kopiëren.",
  "export.downloadStarted": "Download gestart.",
  "export.downloadFailed": "Kon de download niet voorbereiden.",

  // Documents
  "doc.upload.title": "Cursusmateriaal toevoegen",
  "doc.upload.description":
    "Upload een PDF-, Markdown- of tekstbestand. Het wordt geïndexeerd en doorzoekbaar in de tutor.",
  "doc.upload.file": "Bestand",
  "doc.upload.fileHint": "PDF, Markdown (.md) of tekst (.txt).",
  "doc.upload.course": "Vak",
  "doc.upload.coursePlaceholder": "bijv. Wavelet-transformatie",
  "doc.upload.chapter": "Hoofdstuk (optioneel)",
  "doc.upload.chapterHint": "Groepeert het materiaal; laat leeg voor geen.",
  "doc.upload.chapterPlaceholder": "bijv. Hoofdstuk 1",
  "doc.upload.button": "Uploaden en indexeren",
  "doc.upload.success": "{pages} pagina('s) geïndexeerd in “{course}”.",
  "doc.library.title": "Geïndexeerd materiaal",
  "doc.library.description": "Alles wat nu doorzoekbaar is, per vak en hoofdstuk.",
  "doc.refresh": "Vernieuwen",
  "doc.empty.title": "Nog niets geïndexeerd.",
  "doc.empty.description": "Upload hierboven een bestand om het doorzoekbaar te maken in de tutor.",
  "doc.pageCount": "{count} pagina('s)",
  "doc.uncategorized": "Niet-gecategoriseerd",
  "doc.delete.course": "Vak verwijderen",
  "doc.delete.chapter": "Verwijderen",
  "doc.delete.confirm": "“{target}” uit de index verwijderen? Dit kan niet ongedaan worden gemaakt.",
  "doc.delete.success": "{count} item(s) verwijderd uit “{target}”.",
  "doc.progress.starting": "Voorbereiden…",
  "doc.progress.pages": "{done} / {total} pagina's",
  "doc.progress.elapsed": "Verstreken {time}",
  "doc.progress.eta": "~{time} resterend",
  "doc.progress.skipped": "{count} al geïndexeerd",
  "doc.progress.done": "Klaar — {indexed} pagina's geïndexeerd.",
  "doc.progress.error": "Import mislukt: {message}",
  "doc.upToDate": "Bijgewerkt",
  "doc.viewFailed": "Kon het bestand niet openen.",
  "doc.delete.confirmShort": "Verwijderen?",
  "doc.delete.confirmYes": "Ja, verwijderen",

  // Misc
  "common.loading": "Laden",
};

const DICTIONARIES: Record<Locale, Record<TranslationKey, string>> = { en, fr, nl };

/** Pick a sensible default locale from the browser language (fr/nl → match, else en). */
function detectLocale(): Locale {
  if (typeof navigator === "undefined") return "en";
  const lang = (navigator.language || "").toLowerCase();
  if (lang.startsWith("fr")) return "fr";
  if (lang.startsWith("nl")) return "nl";
  return "en";
}

/** Resolve the persisted locale, falling back to browser detection. */
function resolveLocale(): Locale {
  const stored = readLocal(KEYS.locale);
  if (stored === "en" || stored === "fr" || stored === "nl") return stored;
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
