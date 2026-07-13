import type { TranslationKey } from "./en";

/** Dutch dictionary. Same keys as `en`; values are translations. */
export const nl: Record<TranslationKey, string> = {
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
  "hero.app.answered": "Beantwoord vanuit je materiaal",
  "hero.app.refusalQuestion": "Wat voor weer wordt het morgen?",

  // Stats band
  "stats.eyebrow": "Waarom studenten erop vertrouwen",
  "stats.title": "Gebouwd voor antwoorden waarop je kunt bouwen",
  "stats.subtitle":
    "Elk antwoord komt uit je cursus en vermeldt de bron.",
  "stats.cited.value": "100%",
  "stats.cited.label": "Antwoorden met bron — nooit verzonnen",
  "stats.refuses.value": "0",
  "stats.refuses.label": "Verzonnen antwoorden — weigert bij twijfel",
  "stats.private.value": "100%",
  "stats.private.label": "Privé — alleen jij ziet je cursussen",
  "stats.indexOnce.value": "1×",
  "stats.indexOnce.label": "Eén keer indexeren, het hele jaar herhalen",

  // How it works
  "how.eyebrow": "Hoe het werkt",
  "how.title": "Van je cursus naar een geciteerd antwoord",
  "how.subtitle":
    "Van je slides naar een geciteerd antwoord, in drie stappen.",
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
    "Antwoorden uit je cursus — geciteerd, of een eerlijke weigering.",
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
    "Maak in twee klikken een account, voeg je cursus toe en stel je eerste vraag.",
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
  "tabs.exercise": "Oefening",
  "tabs.quiz": "Quiz",
  "tabs.threads": "Gesprekken",
  "tabs.history": "Geschiedenis",
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
  "auth.username": "Gebruikersnaam",
  "auth.usernamePlaceholder": "je_pseudo",
  "auth.password": "Wachtwoord",
  "auth.passwordHint": "Minstens 8 tekens.",
  "auth.accountCreated": "Account aangemaakt. Je wordt ingelogd…",
  "auth.signedInToast": "Ingelogd als {username}.",
  "auth.signedOutToast": "Uitgelogd.",
  "auth.failed": "Authenticatie mislukt.",
  "auth.incomplete": "Voer een gebruikersnaam en wachtwoord in.",
  "auth.cardSubtitle": "Stel vragen en krijg antwoorden op basis van je eigen cursussen.",
  "auth.close": "Sluiten",
  "auth.showPassword": "Wachtwoord tonen",
  "auth.hidePassword": "Wachtwoord verbergen",

  // Blocking sign-in gate (shown when the backend enforces authentication).

  // Locked tool area (landing stays public; the tool requires an account).
  "toolGate.title": "Log in om te starten",
  "toolGate.subtitle":
    "Maak een account om je eigen cursussen te indexeren — je documenten blijven privé.",
  "toolGate.button": "Inloggen of een account aanmaken",

  // Nog geen geïndexeerde cursus (de tools Vragen / Oefening / Quiz vereisen materiaal).
  "docsGate.title": "Nog geen cursusmateriaal",
  "docsGate.subtitle":
    "Sourcio antwoordt alleen op basis van je eigen geïndexeerde documenten. Importeer een cursus om te beginnen.",
  "docsGate.button": "Documenten importeren",

  // Settings panel
  "settings.title": "Instellingen",
  "settings.studentId": "Student-id",
  "settings.studentIdHint": "Identificeert je bij de tutor. Bewaard in deze browser.",
  "settings.baseUrl": "API-basis-URL",
  "settings.baseUrlHint": "Overschrijft NEXT_PUBLIC_API_BASE_URL. Laat leeg voor de standaardwaarde.",
  "settings.apiKey": "API-sleutel",
  "settings.apiKeyHint": "Optioneel — verzonden als de X-API-Key-header indien ingesteld.",
  "settings.apiKeyPlaceholder": "(geen)",
  "settings.sourcesMax": "Max. bronnen",
  "settings.sourcesMaxHint":
    "Maximaal aantal kandidaat-bronnen dat per vraag wordt opgehaald. Alleen de daadwerkelijk gebruikte bronnen worden getoond; een hogere waarde kan een lokaal model vertragen.",
  "common.cancel": "Annuleren",
  "common.save": "Opslaan",

  // Shared
  "common.requestFailed": "Verzoek mislukt.",
  "err.freeTierCapacity":
    "Dit verzoek is te groot voor het gratis model. Voeg je eigen OpenAI- of Anthropic-API-sleutel toe (accountmenu) — het draait dan op je eigen model, gefactureerd op je account.",
  "err.ownKeyCapacity":
    "Je API-sleutel heeft de snelheids- of groottelimiet van de provider voor dit verzoek bereikt. Wacht even en probeer opnieuw, of controleer de gebruikslimieten van je account.",
  "err.scannedNeedsKey":
    "Dit lijkt een gescande of op afbeeldingen gebaseerde PDF, die een vision-model nodig heeft. Voeg je OpenAI-API-sleutel toe om te importeren — tekst-PDF’s en .md/.txt-bestanden worden gratis geïmporteerd, zonder sleutel.",
  "err.keyRejected":
    "De API-sleutel is geweigerd. Controleer of hij geldig is — of hij tegoed en toegang tot een vision-model heeft, en dat je alleen de sleutel hebt geplakt (bijv. sk-…), niet een hele ‘OPENAI_API_KEY=…’-regel.",
  "err.unsupportedFile": "Niet-ondersteund bestandstype — upload een PDF, .md of .txt.",
  "common.upToDate": "Bijgewerkt",
  "answerProgress.search": "Zoeken in je cursussen",
  "answerProgress.read": "De bronnen lezen",
  "answerProgress.write": "Het antwoord schrijven",
  "answerProgress.sourcesFound": "{count} bronnen gevonden",
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
  "rigor.label": "Correctiestrengheid",
  "rigor.aria": "Correctiestrengheid",
  "rigor.lenient": "soepel",
  "rigor.standard": "standaard",
  "rigor.strict": "streng",

  // Ask panel
  "ask.title": "Stel een vraag",
  "ask.description": "Antwoorden komen strikt uit je geïndexeerde cursusmateriaal.",
  "ask.questionLabel": "Vraag",
  "ask.questionPlaceholder": "bijv. Wat zegt de stelling van Pythagoras?",
  "ask.courseLabel": "Cursusfilter",
  "ask.courseHint": "Optioneel — beperk tot één cursus.",
  "ask.coursePlaceholder": "bijv. Wiskunde",

  // Course picker
  "course.allCourses": "Alle cursussen",
  "course.loading": "Cursussen laden…",
  "course.fetchFailed": "Kon cursussen niet laden — voer een cursusnaam in.",
  "ask.chapterLabel": "Hoofdstukfilter",
  "ask.chapterHint": "Optioneel — beperk tot één hoofdstuk.",
  "chapter.all": "Alle hoofdstukken",
  "chapter.loading": "Hoofdstukken laden…",
  "chapter.selectCourseFirst": "Selecteer eerst een cursus.",
  "chapter.none": "Deze cursus heeft geen hoofdstukken.",
  "chapter.fetchFailed": "Kon hoofdstukken niet laden.",
  "ask.maxSources": "Max. bronnen",
  "ask.maxSourcesHint": "Hoeveel passages worden opgehaald.",
  "ask.submit": "Vragen",
  "ask.answerTitle": "Antwoord",
  "ask.empty.title": "Nog geen antwoord",
  "ask.empty.description": "Stel hierboven een vraag voor een onderbouwde, geciteerde uitleg.",
  "ask.reexplainPrompt": "Niet begrepen? Leg opnieuw uit op niveau:",
  "ask.reexplain": "Heruitleggen",
  "ask.rephrasing": "Opnieuw formuleren…",

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
  "reexplain.description": "Hoor je meest recente antwoord opnieuw, afgestemd op een ander niveau.",
  "reexplain.empty.description":
    "Kies een niveau en druk op Heruitleggen. Stel eerst een vraag als je dat nog niet hebt gedaan.",

  // Exercise panel
  "exercise.title": "Genereer een oefening",
  "exercise.description": "Een oefenprobleem verankerd in de cursus, met diens notatie.",
  "exercise.notionLabel": "Welke oefening wil je?",
  "exercise.notionPlaceholder":
    "bijv. een oefening waarin de stelling van Pythagoras wordt toegepast om de schuine zijde van een driehoek te vinden",
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
  "grade.answerLabel": "Jouw antwoord",
  "grade.answerPlaceholder": "Schrijf hier je oplossing…",
  "grade.submit": "Beoordelen",
  "grade.verdictTitle": "Correctie",
  "grade.score": "Score",

  // Quiz panel
  "quiz.title": "Genereer een quiz",
  "quiz.description": "Een reeks oefenvragen verankerd in de cursus, met diens notatie.",
  "quiz.notionLabel": "Waarover moet de quiz gaan?",
  "quiz.notionPlaceholder":
    "bijv. korte vragen over de stelling van Pythagoras, van de stelling tot een kleine berekening",
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
  "quiz.gradingAll": "Je {count} antwoorden worden beoordeeld…",
  "quiz.finalScore": "Eindscore",
  "quiz.recommendationTitle": "Aanbeveling",

  // History panel
  "history.title": "Gespreksgeschiedenis",
  "history.description": "Je beurten met de tutor voor het actieve gesprek.",
  "history.refresh": "Vernieuwen",
  "role.you": "Jij",
  "role.tutor": "Tutor",
  "history.kind.exercise": "Oefening",
  "history.kind.quiz": "Quiz",
  "history.empty.title": "Nog geen geschiedenis",
  "history.empty.description":
    "Stel een vraag of genereer een oefening — je beurten verschijnen hier.",
  "history.clear": "Geschiedenis wissen",
  "history.clear.yes": "Ja, wissen",
  "history.cleared": "Geschiedenis gewist.",
  "history.clearFailed": "Kon de geschiedenis niet wissen.",
  "history.review.show": "Details tonen",
  "history.review.hide": "Details verbergen",
  "history.review.problem": "Opgave",
  "history.review.question": "Vraag",
  "history.review.referenceSolution": "Referentieoplossing",
  "history.review.yourAnswer": "Jouw antwoord",
  "history.review.score": "Score",
  "history.review.feedback": "Feedback",
  "history.review.notAnswered": "Niet beantwoord.",
  "history.review.notGraded": "Nog niet beoordeeld.",
  "history.review.loadFailed": "Kon de details niet laden.",

  // Threads (conversation sessions)
  "threads.title": "Gesprekken",
  "threads.description.line1": "Groepeer je vragen in afzonderlijke gesprekken.",
  "threads.description.line2": "Het actieve gesprek krijgt de nieuwe vragen van het tabblad Vragen.",
  "threads.refresh": "Vernieuwen",
  "threads.list.title": "Gesprekken",
  "threads.newTitleLabel": "Gesprekstitel",
  "threads.newTitlePlaceholder": "Optioneel — bijv. De stelling van Pythagoras",
  "threads.create": "Aanmaken",
  "threads.created": "Gesprek aangemaakt.",
  "threads.createFailed": "Kon het gesprek niet aanmaken.",
  "threads.delete": "Verwijderen",
  "threads.delete.yes": "Ja, verwijderen",
  "threads.deleted": "Gesprek verwijderd, samen met de berichten.",
  "threads.deleteFailed": "Kon het gesprek niet verwijderen.",
  "threads.none": "Alle geschiedenis (zonder gesprek)",
  "threads.noneHint": "Nieuwe vragen worden aan geen enkel gesprek gekoppeld.",
  "threads.untitled": "Naamloos gesprek",
  "threads.active": "Actief",
  "threads.select": "Selecteer gesprek {title}",
  "threads.empty.title": "Nog geen gesprekken",
  "threads.empty.description":
    "Maak een gesprek om verwante vragen te groeperen, of blijf vragen zonder gesprek.",
  "threads.messages.empty.description":
    "Selecteer dit gesprek en stel een vraag op het tabblad Vragen om het te starten.",
  "threads.loadFailed": "Kon gesprekken niet laden.",

  // Thread selector
  "threadSelect.label": "Gesprek",
  "threadSelect.all": "Volledige geschiedenis (geen gesprek)",
  "threadSelect.new": "+ Nieuw gesprek",


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
  "doc.upload.dropzone": "Sleep een bestand hierheen, of klik om te kiezen",
  "doc.upload.dropzoneAria": "Sleepzone — druk op Enter om een bestand te kiezen",
  "doc.upload.selectedFile": "Geselecteerd: {name}",
  "doc.upload.selectedFiles": "{count} bestand(en) geselecteerd",
  "doc.upload.unsupported": "Niet-ondersteund bestandstype. Gebruik een PDF-, Markdown- (.md) of tekstbestand (.txt).",
  "doc.upload.batchFailed": "{count} bestand(en) konden niet worden gestart.",
  "doc.upload.course": "Vak",
  "doc.upload.coursePlaceholder": "bijv. Wiskunde",
  "doc.upload.courseRequired": "Voer een cursusnaam in om te importeren.",
  "doc.upload.chapter": "Hoofdstuk (optioneel)",
  "doc.upload.chapterHint": "Groepeert het materiaal; laat leeg voor geen.",
  "doc.upload.chapterPlaceholder": "bijv. De stelling van Pythagoras",
  "doc.upload.courseDefault": "Standaardcursus",
  "doc.upload.courseDefaultHint": "Gebruikt voor elk bestand hieronder waarvan de cursus leeg blijft.",
  "doc.upload.perFileHeading": "Cursus en hoofdstuk per bestand",
  "doc.upload.perFileHint":
    "Importeer meerdere cursussen en hoofdstukken tegelijk — stel die van elk bestand in. Een lege cursus valt terug op de standaardcursus hierboven.",
  "doc.upload.courseForFile": "Cursus voor {name}",
  "doc.upload.chapterForFile": "Hoofdstuk voor {name}",
  "doc.upload.courseRequiredEach": "Geef elk bestand een cursus (of een standaardcursus hierboven) om te importeren.",
  "doc.upload.openaiKey": "Uw OpenAI- of Anthropic-API-sleutel (optioneel)",
  "doc.upload.openaiKeyHint":
    "Dezelfde sleutel als in het accountmenu. Werkt met een OpenAI- of Anthropic-sleutel (automatisch gedetecteerd). Wanneer ingesteld, voedt hij elk antwoord met een premium-model ÉN leest hij gescande of op afbeeldingen gebaseerde PDF’s — hij vervangt het gratis model en gebruikt uw eigen OpenAI- of Anthropic-tegoed. Alleen opgeslagen in uw browser, nooit op onze server. Tekst-PDF’s en .md/.txt-bestanden worden gratis geïmporteerd, zonder sleutel.",
  "doc.upload.showKey": "Sleutel tonen",
  "doc.upload.hideKey": "Sleutel verbergen",
  "settings.openaiKey.label": "Uw OpenAI- of Anthropic-API-sleutel (optioneel)",
  "settings.openaiKey.note":
    "Gebruik uw eigen OpenAI- of Anthropic-sleutel (automatisch gedetecteerd) voor betere antwoorden overal — Vraag, Opnieuw uitleggen, Oefening, Quiz en beoordeling. Dit vervangt het gratis model en gebruikt uw eigen tegoed. Alleen opgeslagen in uw browser; alleen verzonden met uw verzoeken.",
  "settings.openaiKey.show": "Sleutel tonen",
  "settings.openaiKey.hide": "Sleutel verbergen",
  "settings.openaiKey.badge": "Premium-model",
  "settings.openaiKey.badgeTitle": "Uw OpenAI- of Anthropic-sleutel is actief — antwoorden gebruiken een premium-model in plaats van het gratis model.",
  "doc.upload.button": "Uploaden en indexeren",
  "doc.library.title": "Geïndexeerd materiaal",
  "doc.library.description": "Alles wat nu doorzoekbaar is, per vak en hoofdstuk.",
  "doc.refresh": "Vernieuwen",
  "doc.empty.title": "Nog niets geïndexeerd.",
  "doc.empty.description": "Upload hierboven een bestand om het doorzoekbaar te maken in de tutor.",
  "doc.pageCount": "{count} pagina('s)",
  "doc.uncategorized": "Niet-gecategoriseerd",
  "doc.delete.course": "Volledig vak verwijderen",
  "doc.delete.chapter": "Hoofdstuk verwijderen",
  "doc.delete.success": "{count} item(s) verwijderd uit “{target}”.",
  "doc.progress.starting": "Voorbereiden…",
  "doc.progress.pages": "{done} / {total} pagina's",
  "doc.progress.elapsed": "Verstreken {time}",
  "doc.progress.eta": "~{time} resterend",
  "doc.progress.skipped": "{count} al geïndexeerd",
  "doc.progress.done": "Klaar — {indexed} pagina's geïndexeerd.",
  "doc.progress.alreadyIndexed": "Al bijgewerkt — dit document was al geïndexeerd (0 nieuwe pagina's).",
  "doc.progress.empty":
    "Niets geïndexeerd — er kon geen tekst worden geëxtraheerd. Dit bestand lijkt alleen afbeeldingen te bevatten (gescande pagina's of afbeeldingen), die de huidige extractor niet kan lezen. Configureer een OpenAI-extractiemodel (stel LLM_EXTRACT in) om dit soort bestanden te indexeren.",
  "doc.progress.error": "Import mislukt: {message}",
  "doc.viewFailed": "Kon het bestand niet openen.",
  "doc.delete.confirmShort": "Verwijderen?",
  "doc.delete.confirmYes": "Ja, verwijderen",
  "doc.rename.course": "Vak hernoemen",
  "doc.rename.chapter": "Hoofdstuk hernoemen",
  "doc.rename.courseAria": "Vak “{name}” hernoemen",
  "doc.rename.chapterAria": "Hoofdstuk “{name}” hernoemen",
  "doc.rename.save": "Opslaan",
  "doc.rename.cancel": "Annuleren",
  "doc.rename.success": "Hernoemd naar “{name}”.",
  "doc.rename.failed": "Hernoemen mislukt. Probeer het opnieuw.",

  // Misc
  "common.loading": "Laden",

  // AI thinking indicator — staged messages cycled while the tutor works.
  "thinking.answer.1": "Je cursussen doorzoeken…",
  "thinking.answer.2": "De bronnen lezen…",
  "thinking.answer.3": "Het antwoord schrijven…",
  "thinking.exercise.1": "Relevant materiaal zoeken…",
  "thinking.exercise.2": "De oefening opbouwen…",
  "thinking.grade.1": "Je antwoord lezen…",
  "thinking.grade.2": "Vergelijken met de referentie…",
  "thinking.grade.3": "De correctie schrijven…",
  "thinking.quiz.1": "Relevant materiaal zoeken…",
  "thinking.quiz.2": "De vragen opbouwen…",
};
