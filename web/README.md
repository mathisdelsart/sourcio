# web/

The primary UI: a premium Next.js web app over the FastAPI backend. Ask grounded questions, upload and
manage course documents, generate and grade exercises and quizzes, browse threads and history — with
KaTeX rendering for math-heavy material.

Built with **Next.js (App Router) · TypeScript · Tailwind CSS**, math via `react-markdown` +
`remark-math` + `rehype-katex`. Dark mode and an English / French / Dutch UI toggle are built in.

## Quickstart

```bash
cd web
npm install

# Configure the backend (optional — sensible defaults apply).
cp .env.local.example .env.local

npm run dev   # http://localhost:3000
```

Make sure the FastAPI backend is running (default `http://localhost:8000`). The health badge in the
header polls `/health` and turns green when reachable. Full local stack: [../docs/RUN-LOCAL.md](../docs/RUN-LOCAL.md).

## Environment variables

Set these in `web/.env.local` (see `.env.local.example`); both are also overridable at runtime from the
in-app **Settings** panel.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend base URL. Trailing slashes are trimmed. |
| `NEXT_PUBLIC_API_KEY` | _(empty)_ | Optional. When set, sent as the `X-API-Key` header on every request. |

A `student_id` identifies you to the tutor; one is generated per browser and persisted in
`localStorage`. Registering an account links it to a JWT so history and documents follow the login.

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start the dev server. |
| `npm run build` | Production build (includes typecheck). |
| `npm run start` | Serve the production build. |
| `npm run lint` | Lint with `eslint-config-next`. |
| `npm run typecheck` | Type-check with `tsc --noEmit`. |

## Tabs

| Tab | Backs onto |
| --- | --- |
| **Ask** | `/ask` (+ streaming) — grounded answer, an explicit "refused — not covered" state, source citation chips, and inline re-explain at a chosen level. |
| **Exercise** | `/exercise` then `/grade` — generate a problem on a notion, then score your answer with feedback (the reference solution stays server-side). |
| **Quiz** | `/quiz` (+ `/quiz/{id}/grade`) — a grounded multi-question quiz with automatic grading. |
| **Threads** | `/sessions` — named conversation threads and their messages. |
| **History** | `/history` — chronological turns. |
| **Documents** | upload course files, follow background ingestion jobs, and list / rename / delete / re-open indexed material. |

## Project layout

```
web/
├── app/
│   ├── globals.css       # Tailwind + KaTeX + markdown prose styles
│   ├── layout.tsx        # fonts, toast provider, metadata
│   └── page.tsx          # shell: header, tabs, shared cross-tab state, landing page
├── components/
│   ├── panels/           # AskPanel, ExercisePanel, QuizPanel, ThreadsPanel, HistoryPanel, DocumentsPanel
│   ├── Button, Card, TextField, Tabs, Toast, Spinner, States ...
│   ├── CitationChip, HealthBadge, LevelSelector, Markdown, SettingsPanel, AuthMenu ...
│   └── Hero, Features, HowItWorks, StatsBand ...   # landing-page sections
└── lib/
    ├── api/              # the typed client, split by concern
    │   ├── client.ts     #   transport: base URL, headers, error mapping
    │   ├── types.ts      #   request/response types
    │   └── endpoints.ts  #   one function per endpoint
    ├── i18n.tsx          # locale context and the toggle
    ├── locales/          # en.ts / fr.ts / nl.ts — the strings themselves
    ├── storage.ts        # SSR-safe localStorage helpers + id generation
    ├── exportAnswer.ts   # export a grounded answer as clean Markdown
    ├── highlight.ts      # highlight the source excerpt an answer relied on
    └── useCourses.ts, keys.ts, scroll.ts, cn.ts
```

## Design notes

Charcoal surfaces with a restrained periwinkle accent, hairline borders, `rounded-xl` cards, accessible
focus rings, loading skeletons, empty states, and error toasts. Markdown is rendered without raw HTML
for safety; math uses KaTeX. Deploying on Vercel: [../docs/DEPLOY.md](../docs/DEPLOY.md).
</content>
