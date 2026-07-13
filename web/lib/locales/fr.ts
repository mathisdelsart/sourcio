import type { TranslationKey } from "./en";

/** French dictionary. Same keys as `en`; values are translations. */
export const fr: Record<TranslationKey, string> = {
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
  "hero.app.answered": "Répondu à partir de votre matériel",
  "hero.app.refusalQuestion": "Quel temps fera-t-il demain ?",

  // Stats band — chiffres orientés bénéfice, sans jargon interne.
  "stats.eyebrow": "Pourquoi lui faire confiance",
  "stats.title": "Conçu pour des réponses fiables",
  "stats.subtitle":
    "Chaque réponse vient de votre cours et cite sa source.",
  "stats.cited.value": "100 %",
  "stats.cited.label": "Réponses sourcées — jamais inventées",
  "stats.refuses.value": "0",
  "stats.refuses.label": "Réponse inventée — il refuse quand il ne sait pas",
  "stats.private.value": "100 %",
  "stats.private.label": "Privé — vos cours ne sont visibles que par vous",
  "stats.indexOnce.value": "1×",
  "stats.indexOnce.label": "Indexé une fois, révisé toute l'année",

  // How it works
  "how.eyebrow": "Comment ça marche",
  "how.title": "De votre cours à une réponse citée",
  "how.subtitle":
    "De vos slides à une réponse citée, en trois étapes.",
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
    "Des réponses citées de vos cours — ou un refus honnête.",
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
    "Créez un compte en deux clics, importez votre cours, et posez votre première question.",
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
  "tabs.exercise": "Exercice",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Fils",
  "tabs.history": "Historique",
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
  "auth.username": "Pseudo",
  "auth.usernamePlaceholder": "votre_pseudo",
  "auth.password": "Mot de passe",
  "auth.passwordHint": "Au moins 8 caractères.",
  "auth.accountCreated": "Compte créé. Connexion en cours…",
  "auth.signedInToast": "Connecté en tant que {username}.",
  "auth.signedOutToast": "Déconnecté.",
  "auth.failed": "Échec de l'authentification.",
  "auth.incomplete": "Entrez un pseudo et un mot de passe.",
  "auth.cardSubtitle":
    "Posez vos questions et obtenez des réponses ancrées dans vos propres cours.",
  "auth.close": "Fermer",
  "auth.showPassword": "Afficher le mot de passe",
  "auth.hidePassword": "Masquer le mot de passe",

  // Blocking sign-in gate (shown when the backend enforces authentication).

  // Locked tool area (landing stays public; the tool requires an account).
  "toolGate.title": "Connectez-vous pour commencer",
  "toolGate.subtitle":
    "Créez un compte pour indexer vos propres cours — vos documents restent privés.",
  "toolGate.button": "Se connecter ou créer un compte",

  // Aucun cours indexé (les outils Poser / Exercice / Quiz nécessitent des supports).
  "docsGate.title": "Aucun support de cours pour l'instant",
  "docsGate.subtitle":
    "Sourcio ne répond qu'à partir de vos propres documents indexés. Importez un cours pour commencer.",
  "docsGate.button": "Importer des documents",

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
  "settings.sourcesMax": "Sources max",
  "settings.sourcesMaxHint":
    "Nombre maximal de sources candidates à récupérer par question. Seules les sources réellement utilisées sont affichées ; une valeur élevée peut ralentir un modèle local.",
  "common.cancel": "Annuler",
  "common.save": "Enregistrer",

  // Shared
  "common.requestFailed": "La requête a échoué.",
  "err.freeTierCapacity":
    "Cette requête est trop volumineuse pour le modèle gratuit. Ajoutez votre propre clé API OpenAI ou Anthropic (menu du compte) — elle s’exécute alors sur votre modèle, facturé sur votre compte.",
  "err.ownKeyCapacity":
    "Votre clé API a atteint la limite de débit ou de taille de son fournisseur pour cette requête. Patientez un instant et réessayez, ou vérifiez les limites d’usage de votre compte.",
  "err.scannedNeedsKey":
    "Ceci ressemble à un PDF scanné ou basé sur des images, qui nécessite un modèle de vision. Ajoutez votre clé API OpenAI pour l’importer — les PDF texte et les fichiers .md/.txt s’importent gratuitement, sans clé.",
  "err.keyRejected":
    "La clé API a été rejetée. Vérifiez qu’elle est valide — qu’elle a du crédit et accès à un modèle de vision, et que vous avez collé uniquement la clé (ex. sk-…), pas toute une ligne « OPENAI_API_KEY=… ».",
  "err.unsupportedFile": "Type de fichier non pris en charge — importez un PDF, .md ou .txt.",
  "common.upToDate": "À jour",
  "answerProgress.search": "Recherche dans vos cours",
  "answerProgress.read": "Lecture des sources",
  "answerProgress.write": "Rédaction de la réponse",
  "answerProgress.sourcesFound": "{count} sources trouvées",
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
  "rigor.label": "Sévérité de la correction",
  "rigor.aria": "Sévérité de la correction",
  "rigor.lenient": "indulgente",
  "rigor.standard": "standard",
  "rigor.strict": "stricte",

  // Ask panel
  "ask.title": "Poser une question",
  "ask.description":
    "Les réponses proviennent strictement de votre matériel de cours indexé.",
  // Exemple pré-rempli (identique au hero) pour que l'outil soit clair d'emblée.
  "ask.questionLabel": "Question",
  "ask.questionPlaceholder": "ex. Que dit le théorème de Pythagore ?",
  "ask.courseLabel": "Filtre par cours",
  "ask.courseHint": "Optionnel — restreindre la récupération à un seul cours.",
  "ask.coursePlaceholder": "ex. Mathématiques",

  // Course picker
  "course.allCourses": "Tous les cours",
  "course.loading": "Chargement des cours…",
  "course.fetchFailed": "Impossible de charger les cours — saisissez un nom de cours.",
  "ask.chapterLabel": "Filtre par chapitre",
  "ask.chapterHint": "Optionnel — restreindre à un seul chapitre.",
  "chapter.all": "Tous les chapitres",
  "chapter.loading": "Chargement des chapitres…",
  "chapter.selectCourseFirst": "Sélectionnez d'abord un cours.",
  "chapter.none": "Ce cours n'a aucun chapitre.",
  "chapter.fetchFailed": "Impossible de charger les chapitres.",
  "ask.maxSources": "Sources max",
  "ask.maxSourcesHint": "Nombre de passages à récupérer.",
  "ask.submit": "Demander",
  "ask.answerTitle": "Réponse",
  "ask.empty.title": "Pas encore de réponse",
  "ask.empty.description":
    "Posez une question ci-dessus pour voir une explication ancrée et citée.",
  "ask.reexplainPrompt": "Pas compris ? Réexpliquer à un niveau :",
  "ask.reexplain": "Réexpliquer",
  "ask.rephrasing": "Reformulation…",

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
  "reexplain.description":
    "Réécoutez votre réponse la plus récente, adaptée à un autre niveau d'audience.",
  "reexplain.empty.description":
    "Choisissez un niveau et appuyez sur Réexpliquer. Posez d'abord une question si ce n'est pas déjà fait.",

  // Exercise panel
  "exercise.title": "Générer un exercice",
  "exercise.description":
    "Un problème d'entraînement ancré dans le cours, utilisant sa notation.",
  "exercise.notionLabel": "Quel exercice veux-tu ?",
  "exercise.notionPlaceholder":
    "ex. un problème appliquant le théorème de Pythagore pour trouver l'hypoténuse d'un triangle",
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
  "grade.answerLabel": "Votre réponse",
  "grade.answerPlaceholder": "Rédigez votre solution ici…",
  "grade.submit": "Corriger",
  "grade.verdictTitle": "Correction",
  "grade.score": "Note",

  // Quiz panel
  "quiz.title": "Générer un quiz",
  "quiz.description":
    "Un ensemble de questions d'entraînement ancrées dans le cours, utilisant sa notation.",
  "quiz.notionLabel": "Sur quoi doit porter le quiz ?",
  "quiz.notionPlaceholder":
    "ex. des questions courtes sur le théorème de Pythagore, de l'énoncé à un petit calcul",
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
  "quiz.gradingAll": "Correction de vos {count} réponses…",
  "quiz.finalScore": "Note finale",
  "quiz.recommendationTitle": "Recommandation",

  // History panel
  "history.title": "Historique de conversation",
  "history.description": "Vos échanges avec le tuteur pour le fil actif.",
  "history.refresh": "Actualiser",
  "role.you": "Vous",
  "role.tutor": "Tuteur",
  "history.kind.exercise": "Exercice",
  "history.kind.quiz": "Quiz",
  "history.empty.title": "Pas encore d'historique",
  "history.empty.description":
    "Posez une question ou générez un exercice — vos échanges apparaîtront ici.",
  "history.clear": "Effacer l'historique",
  "history.clear.yes": "Oui, effacer",
  "history.cleared": "Historique effacé.",
  "history.clearFailed": "Impossible d'effacer l'historique.",
  "history.review.show": "Afficher les détails",
  "history.review.hide": "Masquer les détails",
  "history.review.problem": "Énoncé",
  "history.review.question": "Question",
  "history.review.referenceSolution": "Solution de référence",
  "history.review.yourAnswer": "Votre réponse",
  "history.review.score": "Note",
  "history.review.feedback": "Retour",
  "history.review.notAnswered": "Pas de réponse.",
  "history.review.notGraded": "Pas encore corrigé.",
  "history.review.loadFailed": "Impossible de charger les détails.",

  // Threads (conversation sessions)
  "threads.title": "Fils de conversation",
  "threads.description.line1": "Regroupez vos questions dans des fils de conversation.",
  "threads.description.line2": "Le fil actif reçoit les nouvelles questions de l'onglet Demander.",
  "threads.refresh": "Actualiser",
  "threads.list.title": "Fils",
  "threads.newTitleLabel": "Titre du fil",
  "threads.newTitlePlaceholder": "Optionnel — ex. Le théorème de Pythagore",
  "threads.create": "Créer",
  "threads.created": "Fil créé.",
  "threads.createFailed": "Impossible de créer le fil.",
  "threads.delete": "Supprimer",
  "threads.delete.yes": "Oui, supprimer",
  "threads.deleted": "Fil supprimé, ainsi que ses messages.",
  "threads.deleteFailed": "Impossible de supprimer le fil.",
  "threads.none": "Tout l'historique (sans fil)",
  "threads.noneHint": "Les nouvelles questions ne sont rattachées à aucun fil.",
  "threads.untitled": "Fil sans titre",
  "threads.active": "Actif",
  "threads.select": "Sélectionner le fil {title}",
  "threads.empty.title": "Pas encore de fil",
  "threads.empty.description":
    "Créez un fil pour regrouper des questions liées, ou continuez sans fil.",
  "threads.messages.empty.description":
    "Sélectionnez ce fil, puis posez une question dans l'onglet Demander pour le démarrer.",
  "threads.loadFailed": "Impossible de charger les fils.",

  // Thread selector
  "threadSelect.label": "Fil",
  "threadSelect.all": "Tout l'historique (aucun fil)",
  "threadSelect.new": "+ Nouveau fil",


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
  "doc.upload.dropzone": "Glissez-déposez un fichier ici, ou cliquez pour choisir",
  "doc.upload.dropzoneAria": "Zone de dépôt — appuyez sur Entrée pour choisir un fichier",
  "doc.upload.selectedFile": "Sélectionné : {name}",
  "doc.upload.selectedFiles": "{count} fichier(s) sélectionné(s)",
  "doc.upload.unsupported": "Type de fichier non pris en charge. Utilisez un fichier PDF, Markdown (.md) ou texte (.txt).",
  "doc.upload.batchFailed": "{count} fichier(s) n'ont pas pu démarrer.",
  "doc.upload.course": "Cours",
  "doc.upload.coursePlaceholder": "ex. Mathématiques",
  "doc.upload.courseRequired": "Indiquez le nom du cours pour importer.",
  "doc.upload.chapter": "Chapitre (optionnel)",
  "doc.upload.chapterHint": "Regroupe le contenu ; laissez vide si aucun.",
  "doc.upload.chapterPlaceholder": "ex. Le théorème de Pythagore",
  "doc.upload.courseDefault": "Cours par défaut",
  "doc.upload.courseDefaultHint": "Utilisé pour tout fichier ci-dessous dont le cours est laissé vide.",
  "doc.upload.perFileHeading": "Cours et chapitre par fichier",
  "doc.upload.perFileHint":
    "Importez plusieurs cours et chapitres à la fois — indiquez ceux de chaque fichier. Un cours vide reprend le cours par défaut ci-dessus.",
  "doc.upload.courseForFile": "Cours pour {name}",
  "doc.upload.chapterForFile": "Chapitre pour {name}",
  "doc.upload.courseRequiredEach": "Donnez un cours à chaque fichier (ou un cours par défaut ci-dessus) pour importer.",
  "doc.upload.openaiKey": "Votre clé API OpenAI ou Anthropic (optionnel)",
  "doc.upload.openaiKeyHint":
    "La même clé que dans le menu du compte. Fonctionne avec une clé OpenAI ou Anthropic (détectée automatiquement). Lorsqu’elle est définie, elle alimente chaque réponse avec un modèle premium ET permet de lire les PDF scannés ou basés sur des images : elle remplace le modèle gratuit et utilise votre propre crédit OpenAI ou Anthropic. Conservée uniquement dans votre navigateur, jamais sur notre serveur. Les PDF texte et les fichiers .md/.txt s’importent gratuitement, sans clé.",
  "doc.upload.showKey": "Afficher la clé",
  "doc.upload.hideKey": "Masquer la clé",
  "settings.openaiKey.label": "Votre clé API OpenAI ou Anthropic (optionnel)",
  "settings.openaiKey.note":
    "Utilisez votre propre clé OpenAI ou Anthropic (détectée automatiquement) pour des réponses de meilleure qualité partout — Poser, Ré-expliquer, Exercice, Quiz et correction. Elle remplace le modèle gratuit et utilise votre propre crédit. Conservée uniquement dans votre navigateur ; envoyée seulement avec vos requêtes.",
  "settings.openaiKey.show": "Afficher la clé",
  "settings.openaiKey.hide": "Masquer la clé",
  "settings.openaiKey.badge": "Modèle premium",
  "settings.openaiKey.badgeTitle": "Votre clé OpenAI ou Anthropic est active — les réponses utilisent un modèle premium au lieu du modèle gratuit.",
  "doc.upload.button": "Importer et indexer",
  "doc.library.title": "Contenu indexé",
  "doc.library.description": "Tout ce qui est consultable, par cours et chapitre.",
  "doc.refresh": "Actualiser",
  "doc.empty.title": "Rien d’indexé pour l’instant.",
  "doc.empty.description": "Importez un fichier ci-dessus pour le rendre consultable dans le tuteur.",
  "doc.pageCount": "{count} page(s)",
  "doc.uncategorized": "Sans catégorie",
  "doc.delete.course": "Supprimer tout le cours",
  "doc.delete.chapter": "Supprimer le chapitre",
  "doc.delete.success": "{count} élément(s) retiré(s) de « {target} ».",
  "doc.progress.starting": "Préparation…",
  "doc.progress.pages": "{done} / {total} pages",
  "doc.progress.elapsed": "Écoulé {time}",
  "doc.progress.eta": "~{time} restant",
  "doc.progress.skipped": "{count} déjà indexées",
  "doc.progress.done": "Terminé — {indexed} pages indexées.",
  "doc.progress.alreadyIndexed": "Déjà à jour — ce document était déjà indexé (0 nouvelle page).",
  "doc.progress.empty":
    "Rien indexé — aucun texte n'a pu être extrait. Ce fichier semble ne contenir que des images (pages scannées ou images), que l'extracteur actuel ne peut pas lire. Configurez un modèle d'extraction OpenAI (définissez LLM_EXTRACT) pour indexer ce type de fichier.",
  "doc.progress.error": "Échec de l'import : {message}",
  "doc.viewFailed": "Impossible d'ouvrir le fichier.",
  "doc.delete.confirmShort": "Supprimer ?",
  "doc.delete.confirmYes": "Oui, supprimer",
  "doc.rename.course": "Renommer le cours",
  "doc.rename.chapter": "Renommer le chapitre",
  "doc.rename.courseAria": "Renommer le cours « {name} »",
  "doc.rename.chapterAria": "Renommer le chapitre « {name} »",
  "doc.rename.save": "Enregistrer",
  "doc.rename.cancel": "Annuler",
  "doc.rename.success": "Renommé en « {name} ».",
  "doc.rename.failed": "Impossible de renommer. Veuillez réessayer.",

  // Misc
  "common.loading": "Chargement",

  // AI thinking indicator — staged messages cycled while the tutor works.
  "thinking.answer.1": "Recherche dans vos cours…",
  "thinking.answer.2": "Lecture des sources…",
  "thinking.answer.3": "Rédaction de la réponse…",
  "thinking.exercise.1": "Recherche du contenu pertinent…",
  "thinking.exercise.2": "Construction de l'exercice…",
  "thinking.grade.1": "Lecture de votre réponse…",
  "thinking.grade.2": "Comparaison avec la référence…",
  "thinking.grade.3": "Rédaction de la correction…",
  "thinking.quiz.1": "Recherche du contenu pertinent…",
  "thinking.quiz.2": "Construction des questions…",
};
