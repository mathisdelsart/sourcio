# Next.js — frontend

## Role in the system

The user interface. It is a client of the FastAPI backend and shares no code with it; the two
deploy independently (Vercel and a Docker container respectively).

## Why Next.js

A plain React SPA (Vite) would have worked. Next.js was chosen for:

- **file-based routing** — conventions rather than a route configuration to maintain;
- **a solved production build** — bundling, code-splitting, asset handling;
- **first-class deployment** on Vercel, which matters for a project that must be publicly
  reachable.

**Server rendering is largely irrelevant here**, and this should be stated plainly rather than
implied otherwise. The application is authenticated and highly interactive: nearly every page
is a client component talking to a separate API, so there is little for server components to
do. Next.js was chosen for routing conventions and deployment, not for SSR. Vite would have
produced a comparable application.

## The client/server boundary

- **Server Components** (the default) render on the server, ship no JavaScript to the browser,
  and cannot use `useState`, `useEffect` or event handlers.
- **Client Components** (`"use client"`) are conventional React and can be interactive.

The rule is to push `"use client"` as far down the tree as possible, since everything below a
client boundary is also client. In this application the interactive surface is large — the ask
box, the streaming answer, the panels — so the boundary sits high. That is an accurate
reflection of the product, not an oversight.

## Consuming the SSE token stream

The backend streams answers as Server-Sent Events. Three constraints shape the client:

**`EventSource` cannot be used.** It is GET-only and cannot set an `Authorization` header. The
request carries a JWT and is a POST, so the response body stream is read manually:

```ts
const res = await fetch(`${base}/ask/stream`, { method: "POST", body, headers });
const reader = res.body!.getReader();
```

**Events must be buffered across network chunks.** A chunk boundary can split an SSE event in
half. Parsing must occur only on a complete `\n\n` delimiter, or tokens are silently dropped.

**State updates must be batched.** Setting React state per token is one re-render per token.
Tokens accumulate in a buffer and are flushed per frame.

## `NEXT_PUBLIC_` variables

Inlined into the client bundle **at build time**. Two consequences that govern their use:

- they are **permanently public** to anyone who opens developer tools;
- changing one requires a **rebuild**, not a restart.

The API base URL and an optional demo key are appropriate. A provider key never is.

## localStorage and the rename

Client state — the auth token, the student id, the selected course, theme and locale — is kept
in `localStorage` under a namespaced prefix.

When the project was renamed from `grounded-rag` to `sourcio`, renaming the keys directly would
have **signed out every existing user** and discarded their preferences on the next deployment.

`web/lib/storage.ts` therefore performs a **one-time migration**: on load, each legacy value is
copied to the new key when the new key is absent, and the legacy key is removed. It is
idempotent and becomes a no-op once every browser has been through it.

A rename should not be a logout.

## Known trade-off

The JWT is stored in `localStorage` and attached as `Authorization: Bearer`. This is readable
by JavaScript on the origin, so frontend XSS implies token compromise. The alternative — an
`HttpOnly` cookie — is more resistant but requires CSRF protection and a same-site strategy
against a cross-origin API. See [auth-security.md](auth-security.md).

## Hydration

Hydration mismatches in this application originate from reading `localStorage` during render,
which does not exist on the server. The storage helpers are SSR-safe
(`typeof window === "undefined"` returns the fallback), which is the reason they exist rather
than calling `localStorage` directly.
