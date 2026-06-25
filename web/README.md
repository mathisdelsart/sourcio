# Grounded Tutor — Web Frontend

A premium web UI for the grounded course tutor. It is a thin, typed client over
the existing FastAPI backend: ask grounded questions, re-explain answers at a
chosen level, generate exercises, grade your answers, and browse history — with
beautiful LaTeX rendering for math-heavy material.

Built with **Next.js (App Router) · TypeScript · Tailwind CSS**, with
KaTeX-rendered markdown via `react-markdown` + `remark-math` + `rehype-katex`.

## Quickstart

```bash
cd web
npm install

# Configure the backend (optional — sensible defaults apply).
cp .env.local.example .env.local

npm run dev   # http://localhost:3000
```

Make sure the FastAPI backend is running (default `http://localhost:8000`). The
health badge in the header polls `/health` and turns green when reachable.

## Environment variables

Set these in `web/.env.local` (see `.env.local.example`). Both are also
overridable at runtime from the in-app **Settings** panel.

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Backend base URL. Trailing slashes are trimmed. |
| `NEXT_PUBLIC_API_KEY` | _(empty)_ | Optional. When set, sent as the `X-API-Key` header on every request. |

A `student_id` identifies you to the tutor. One is generated per browser and
persisted in `localStorage` (`grounded-rag:student_id`); you can edit it in
Settings.

## Scripts

| Command | Description |
| --- | --- |
| `npm run dev` | Start the dev server. |
| `npm run build` | Production build (includes typecheck). |
| `npm run start` | Serve the production build. |
| `npm run lint` | Lint with `eslint-config-next`. |
| `npm run typecheck` | Type-check with `tsc --noEmit`. |

## Surface

| Tab | Maps to |
| --- | --- |
| **Ask** | `POST /ask` — question + course/chapter filter + `k`; renders the grounded answer, an explicit "refused — not covered" state, and source citation chips. Includes inline re-explain. |
| **Re-explain** | `POST /reexplain` — re-explain the last answer at `beginner` / `intermediate` / `advanced`. |
| **Exercise** | `POST /exercise` — generate a problem on a notion; the returned `id` is kept so Grade can link to it. |
| **Grade** | `POST /grade` — score + feedback for your answer, optionally tied to the last exercise. |
| **History** | `GET /history/{student_id}` — chronological turns. |

## Project layout

```
web/
├── app/
│   ├── globals.css       # Tailwind + KaTeX + markdown prose styles
│   ├── layout.tsx        # fonts (Inter), toast provider, metadata
│   └── page.tsx          # shell: header, tabs, shared cross-tab state
├── components/
│   ├── panels/           # AskPanel, ReexplainPanel, ExercisePanel, GradePanel, HistoryPanel
│   ├── Button, Card, TextField, Tabs, Toast, Spinner, States ...
│   ├── CitationChip, HealthBadge, LevelSelector, Markdown, SettingsPanel
└── lib/
    ├── api.ts            # typed client, one function per endpoint
    ├── storage.ts        # SSR-safe localStorage helpers + id generation
    ├── keys.ts           # Cmd/Ctrl+Enter submit helper
    └── cn.ts             # className join helper
```

## Design notes

Sober light theme: white/zinc surfaces, neutral gray text, a single restrained
indigo accent for primary actions and active states. Hairline borders, subtle
shadows, `rounded-xl` cards, accessible focus rings, loading skeletons, empty
states, and error toasts. Markdown is rendered without raw HTML for safety; math
uses KaTeX.
