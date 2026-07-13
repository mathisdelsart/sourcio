/** Stable, English dictionary. Keys are stable ids; English doubles as fallback. */
export const en = {
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
  "hero.app.answered": "Answered from your material",
  "hero.app.refusalQuestion": "What's the weather tomorrow?",

  // Stats band — benefit-first figures, no internal jargon.
  "stats.eyebrow": "Why students trust it",
  "stats.title": "Built for answers you can rely on",
  "stats.subtitle":
    "Every answer comes from your own course and cites its source.",
  "stats.cited.value": "100%",
  "stats.cited.label": "Answers cited — never invented",
  "stats.refuses.value": "0",
  "stats.refuses.label": "Made-up answers — it refuses when unsure",
  "stats.private.value": "100%",
  "stats.private.label": "Private — only you can see your courses",
  "stats.indexOnce.value": "1×",
  "stats.indexOnce.label": "Index once, revise all year",

  // How it works
  "how.eyebrow": "How it works",
  "how.title": "From your course to a cited answer",
  "how.subtitle":
    "From your slides to a cited answer, in three steps.",
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
    "Answers from your course — cited, or an honest refusal.",
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
    "Create an account in two clicks, add your course, and ask your first question.",
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
  "tabs.exercise": "Exercise",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Threads",
  "tabs.history": "History",
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
  "auth.username": "Username",
  "auth.usernamePlaceholder": "your_pseudo",
  "auth.password": "Password",
  "auth.passwordHint": "At least 8 characters.",
  "auth.accountCreated": "Account created. Signing you in…",
  "auth.signedInToast": "Signed in as {username}.",
  "auth.signedOutToast": "Signed out.",
  "auth.failed": "Authentication failed.",
  "auth.incomplete": "Enter a username and password.",
  "auth.cardSubtitle": "Ask questions and get answers grounded in your own courses.",
  "auth.close": "Close",
  "auth.showPassword": "Show password",
  "auth.hidePassword": "Hide password",

  // Blocking sign-in gate (shown when the backend enforces authentication).

  // Locked tool area (landing stays public; the tool requires an account).
  "toolGate.title": "Sign in to start",
  "toolGate.subtitle":
    "Create an account to index your own courses — your documents stay private to you.",
  "toolGate.button": "Sign in or create an account",

  // No indexed courses yet (Ask / Exercise / Quiz tools require course material).
  "docsGate.title": "No course material yet",
  "docsGate.subtitle":
    "Sourcio only answers from your own indexed documents. Import a course to get started.",
  "docsGate.button": "Import documents",

  // Settings panel
  "settings.title": "Settings",
  "settings.studentId": "Student id",
  "settings.studentIdHint": "Identifies you to the tutor. Persisted in this browser.",
  "settings.baseUrl": "API base URL",
  "settings.baseUrlHint": "Overrides NEXT_PUBLIC_API_BASE_URL. Leave empty to use the default.",
  "settings.apiKey": "API key",
  "settings.apiKeyHint": "Optional — sent as the X-API-Key header when set.",
  "settings.apiKeyPlaceholder": "(none)",
  "settings.sourcesMax": "Max sources",
  "settings.sourcesMaxHint":
    "Maximum candidate sources to retrieve per question. Only the sources actually used are shown; a higher value can slow a local model.",
  "common.cancel": "Cancel",
  "common.save": "Save",

  // Shared
  "common.requestFailed": "Request failed.",
  "err.freeTierCapacity":
    "This request is too large for the free model. Add your own OpenAI or Anthropic API key (account menu) — it then runs on your own model, billed to your account.",
  "err.ownKeyCapacity":
    "Your API key hit its provider's rate or size limit for this request. Wait a moment and try again, or check your account's usage limits.",
  "err.scannedNeedsKey":
    "This looks like a scanned or image-based PDF, which needs a vision model to read. Add your OpenAI API key to import it — text PDFs and .md/.txt files import for free without a key.",
  "err.keyRejected":
    "The API key was rejected. Check that it is valid — that it has credit and access to a vision model, and that you pasted only the key itself (e.g. sk-…), not a whole “OPENAI_API_KEY=…” line.",
  "err.unsupportedFile": "Unsupported file type — upload a PDF, .md or .txt.",
  "common.upToDate": "Up to date",
  "answerProgress.search": "Searching your courses",
  "answerProgress.read": "Reading the sources",
  "answerProgress.write": "Writing the answer",
  "answerProgress.sourcesFound": "{count} sources found",
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
  "rigor.label": "Marking strictness",
  "rigor.aria": "Marking strictness",
  "rigor.lenient": "lenient",
  "rigor.standard": "standard",
  "rigor.strict": "strict",

  // Ask panel
  "ask.title": "Ask a question",
  "ask.description": "Answers come strictly from your indexed course material.",
  // Pre-filled example (mirrors the hero) so the tool is instantly clear.
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder": "e.g. What does the Pythagorean theorem state?",
  "ask.courseLabel": "Course filter",
  "ask.courseHint": "Optional — restrict retrieval to one course.",
  "ask.coursePlaceholder": "e.g. Mathematics",

  // Course picker
  "course.allCourses": "All courses",
  "course.loading": "Loading courses…",
  "course.fetchFailed": "Could not load courses — enter a course name.",
  "ask.chapterLabel": "Chapter filter",
  "ask.chapterHint": "Optional — restrict to a single chapter.",
  "chapter.all": "All chapters",
  "chapter.loading": "Loading chapters…",
  "chapter.selectCourseFirst": "Select a course first.",
  "chapter.none": "This course has no chapters.",
  "chapter.fetchFailed": "Could not load chapters.",
  "ask.maxSources": "Max sources",
  "ask.maxSourcesHint": "How many passages to retrieve.",
  "ask.submit": "Ask",
  "ask.answerTitle": "Answer",
  "ask.empty.title": "No answer yet",
  "ask.empty.description": "Ask a question above to see a grounded, cited explanation.",
  "ask.reexplainPrompt": "Didn't get it? Re-explain at a level:",
  "ask.reexplain": "Re-explain",
  "ask.rephrasing": "Rephrasing…",

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
  "reexplain.description":
    "Hear your most recent answer again, tuned to a different audience level.",
  "reexplain.empty.description":
    "Pick a level and press Re-explain. Ask a question first if you have not yet.",

  // Exercise panel
  "exercise.title": "Generate an exercise",
  "exercise.description": "A practice problem grounded in the course, using its notation.",
  "exercise.notionLabel": "What exercise do you want?",
  "exercise.notionPlaceholder":
    "e.g. a problem applying the Pythagorean theorem to find a triangle's hypotenuse",
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
  "grade.answerLabel": "Your answer",
  "grade.answerPlaceholder": "Write your solution here…",
  "grade.submit": "Grade",
  "grade.verdictTitle": "Correction",
  "grade.score": "Score",

  // Quiz panel
  "quiz.title": "Generate a quiz",
  "quiz.description":
    "A set of practice questions grounded in the course, using its notation.",
  "quiz.notionLabel": "What should the quiz cover?",
  "quiz.notionPlaceholder":
    "e.g. short questions on the Pythagorean theorem, from statement to a small calculation",
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
  "quiz.gradingAll": "Grading your {count} answers…",
  "quiz.finalScore": "Final score",
  "quiz.recommendationTitle": "Recommendation",

  // History panel
  "history.title": "Conversation history",
  "history.description": "Your turns with the tutor for the active thread.",
  "history.refresh": "Refresh",
  "role.you": "You",
  "role.tutor": "Tutor",
  "history.kind.exercise": "Exercise",
  "history.kind.quiz": "Quiz",
  "history.empty.title": "No history yet",
  "history.empty.description":
    "Ask a question or generate an exercise — your turns will appear here.",
  "history.clear": "Clear history",
  "history.clear.yes": "Yes, clear",
  "history.cleared": "History cleared.",
  "history.clearFailed": "Could not clear the history.",
  "history.review.show": "Show details",
  "history.review.hide": "Hide details",
  "history.review.problem": "Problem",
  "history.review.question": "Question",
  "history.review.referenceSolution": "Reference solution",
  "history.review.yourAnswer": "Your answer",
  "history.review.score": "Score",
  "history.review.feedback": "Feedback",
  "history.review.notAnswered": "Not answered.",
  "history.review.notGraded": "Not graded yet.",
  "history.review.loadFailed": "Could not load the details.",

  // Threads (conversation sessions)
  "threads.title": "Conversation threads",
  // Split into two balanced lines, rendered on separate lines in the card header.
  "threads.description.line1": "Group your questions into conversation threads.",
  "threads.description.line2": "New questions in the Ask tab join the active thread.",
  "threads.refresh": "Refresh",
  "threads.list.title": "Threads",
  "threads.newTitleLabel": "Thread title",
  "threads.newTitlePlaceholder": "Optional — e.g. The Pythagorean theorem",
  "threads.create": "Create",
  "threads.created": "Thread created.",
  "threads.createFailed": "Could not create the thread.",
  "threads.delete": "Delete",
  "threads.delete.yes": "Yes, delete",
  "threads.deleted": "Thread deleted, along with its messages.",
  "threads.deleteFailed": "Could not delete the thread.",
  "threads.none": "All history (unthreaded)",
  "threads.noneHint": "New questions are not attached to any thread.",
  "threads.untitled": "Untitled thread",
  "threads.active": "Active",
  "threads.select": "Select thread {title}",
  "threads.empty.title": "No threads yet",
  "threads.empty.description":
    "Create a thread to group related questions, or keep asking without one.",
  "threads.messages.empty.description":
    "Select this thread, then ask a question in the Ask tab to start it.",
  "threads.loadFailed": "Could not load threads.",

  // Thread selector
  "threadSelect.label": "Thread",
  "threadSelect.all": "All history (no thread)",
  "threadSelect.new": "+ New thread",


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
  "doc.upload.dropzone": "Drag & drop a file here, or click to choose",
  "doc.upload.dropzoneAria": "Drop zone — press Enter to choose a file",
  "doc.upload.selectedFile": "Selected: {name}",
  "doc.upload.selectedFiles": "{count} file(s) selected",
  "doc.upload.unsupported": "Unsupported file type. Use a PDF, Markdown (.md) or text (.txt) file.",
  "doc.upload.batchFailed": "{count} file(s) failed to start.",
  "doc.upload.course": "Course",
  "doc.upload.coursePlaceholder": "e.g. Mathematics",
  "doc.upload.courseRequired": "Enter a course name to import.",
  "doc.upload.chapter": "Chapter (optional)",
  "doc.upload.chapterHint": "Groups the material; leave empty for none.",
  "doc.upload.chapterPlaceholder": "e.g. The Pythagorean theorem",
  "doc.upload.courseDefault": "Default course",
  "doc.upload.courseDefaultHint": "Used for any file below that leaves its course blank.",
  "doc.upload.perFileHeading": "Course & chapter per file",
  "doc.upload.perFileHint":
    "Import several courses and chapters at once — set each file’s own. A blank course falls back to the default above.",
  "doc.upload.courseForFile": "Course for {name}",
  "doc.upload.chapterForFile": "Chapter for {name}",
  "doc.upload.courseRequiredEach": "Give every file a course (or a default above) to import.",
  "doc.upload.openaiKey": "Your OpenAI or Anthropic API key (optional)",
  "doc.upload.openaiKeyHint":
    "The same key as in the account menu. Works with an OpenAI or an Anthropic key (auto-detected). When set it powers every answer with a premium model AND reads scanned/image PDFs — it replaces the free model and runs on your own OpenAI or Anthropic credit. Stored in your browser only; never on our server. Text PDFs and .md/.txt files import for free without a key.",
  "doc.upload.showKey": "Show key",
  "doc.upload.hideKey": "Hide key",
  "settings.openaiKey.label": "Your OpenAI or Anthropic API key (optional)",
  "settings.openaiKey.note":
    "Use your own OpenAI or Anthropic key (auto-detected) for higher-quality answers everywhere — Ask, Re-explain, Exercise, Quiz and grading. This replaces the free model and runs on your own credit. Stored only in your browser; sent only with your requests.",
  "settings.openaiKey.show": "Show key",
  "settings.openaiKey.hide": "Hide key",
  "settings.openaiKey.badge": "Premium model",
  "settings.openaiKey.badgeTitle": "Your OpenAI or Anthropic key is active — answers use a premium model instead of the free one.",
  "doc.upload.button": "Upload & index",
  "doc.library.title": "Indexed material",
  "doc.library.description": "Everything currently searchable, by course and chapter.",
  "doc.refresh": "Refresh",
  "doc.empty.title": "Nothing indexed yet.",
  "doc.empty.description": "Upload a file above to make it searchable in the tutor.",
  "doc.pageCount": "{count} page(s)",
  "doc.uncategorized": "Uncategorized",
  "doc.delete.course": "Delete entire course",
  "doc.delete.chapter": "Delete chapter",
  "doc.delete.success": "Removed {count} item(s) from “{target}”.",
  "doc.progress.starting": "Preparing…",
  "doc.progress.pages": "{done} / {total} pages",
  "doc.progress.elapsed": "Elapsed {time}",
  "doc.progress.eta": "~{time} left",
  "doc.progress.skipped": "{count} already indexed",
  "doc.progress.done": "Done — {indexed} pages indexed.",
  "doc.progress.alreadyIndexed": "Already up to date — this document was already indexed (0 new pages).",
  "doc.progress.empty":
    "Nothing indexed — no text could be extracted. This file looks image-only (scanned pages or images), which the current extractor cannot read. Configure an OpenAI extract model (set LLM_EXTRACT) to index files like this.",
  "doc.progress.error": "Import failed: {message}",
  "doc.viewFailed": "Could not open the file.",
  "doc.delete.confirmShort": "Delete?",
  "doc.delete.confirmYes": "Yes, delete",
  "doc.rename.course": "Rename course",
  "doc.rename.chapter": "Rename chapter",
  "doc.rename.courseAria": "Rename course “{name}”",
  "doc.rename.chapterAria": "Rename chapter “{name}”",
  "doc.rename.save": "Save",
  "doc.rename.cancel": "Cancel",
  "doc.rename.success": "Renamed to “{name}”.",
  "doc.rename.failed": "Could not rename. Please try again.",

  // Misc
  "common.loading": "Loading",

  // AI thinking indicator — staged messages cycled while the tutor works.
  "thinking.answer.1": "Searching your courses…",
  "thinking.answer.2": "Reading the sources…",
  "thinking.answer.3": "Writing the answer…",
  "thinking.exercise.1": "Finding the relevant material…",
  "thinking.exercise.2": "Building the exercise…",
  "thinking.grade.1": "Reading your answer…",
  "thinking.grade.2": "Comparing with the reference…",
  "thinking.grade.3": "Writing the correction…",
  "thinking.quiz.1": "Finding the relevant material…",
  "thinking.quiz.2": "Building the questions…",
} as const;

/** Translation key set, derived from the English dictionary. */
export type TranslationKey = keyof typeof en;
