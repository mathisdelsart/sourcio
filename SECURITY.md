# Security Policy

grounded-rag is a course tutor grounded in your own material: it answers only
from indexed course documents, always cites its sources, and refuses when a
question is not covered. This document describes how to report a vulnerability,
the threat model the project is built against, the controls in place, and how to
deploy it safely.

## Reporting a vulnerability

Please report security issues privately rather than opening a public issue.

- Use GitHub's **private vulnerability reporting** (the "Report a vulnerability"
  button under the repository's *Security* tab), or
- Contact the maintainer directly through the email on the GitHub profile.

Include a description, reproduction steps, affected version/commit, and impact.
Please allow a reasonable window for a fix before any public disclosure. There is
no bug-bounty program; this is a personal/portfolio project.

## Threat model

The project runs in two very different postures, and the security expectations
differ accordingly.

- **Local, single-user (default).** The API runs on `localhost`, authentication
  is optional (`REQUIRE_AUTH=false`), callers are keyed by a device-local
  `student_id`, and the data store is a local SQLite file plus a local Qdrant.
  The trust boundary is the machine itself; there is effectively one user. This
  is the out-of-the-box developer experience.
- **Shared / public deployment.** The API is exposed over the network and serves
  multiple accounts. Here the adversary is any remote client: an unauthenticated
  visitor, or a *logged-in but hostile* tenant trying to read or modify another
  tenant's data. This posture requires the full **Deployment checklist** below;
  the local defaults are not sufficient for it.

Out of scope: the security of the underlying LLM provider, denial-of-service via
paid-provider cost exhaustion beyond the provided rate limit and provider-side
caps, and physical/host compromise.

## Data-isolation model

Isolation is enforced in two layers that must agree.

- **Vector store (Qdrant), strict owner isolation.** Each indexed chunk carries
  an `owner` in its payload. Reads apply a strict *"owner == mine"* filter
  (`owner_scope_filter` in `core/retrieval.py`): a caller sees **only** chunks
  whose `owner` matches their own id — there is **no shared/legacy branch**, so
  owner-less chunks (e.g. ingested via the CLI before per-account scoping) are
  invisible to every account. This closes the cross-tenant leak where an
  owner-less chunk was visible to everyone. Chunk ids are deterministic
  (`ingestion/chunk.py`), so single-source lookups are scoped by the same rule:
  `GET /source/{chunk_id}` resolves the caller's effective owner and passes it to
  `get_source`, which returns a chunk only when its `owner` equals the caller's.
  A chunk owned by a *different* account — or an owner-less legacy chunk — is
  reported as **404**; its existence is never leaked, so a caller cannot read
  another account's material by guessing a chunk id. Deletes (`DELETE /documents`)
  use the same strict scope (`delete_documents` in `core/documents.py`): a caller
  can remove only their own uploads, never another account's material and never
  the owner-less corpus. **Fail-closed on missing identity.** Listing, retrieval,
  single-source and delete paths never run unscoped when an owner is expected: if
  the effective owner resolves to `None` (a request carrying no identity), the
  read returns *empty* and the delete removes *nothing*, rather than falling back
  to "everything". Uploads require a `student_id` so every indexed chunk is
  owner-stamped and never left globally invisible.
- **Relational store (SQLAlchemy), ownership-scoped.** Students, history,
  sessions, exercises, quizzes, feedback and reviews hang off `Student`, and
  `Student.user_id` links a student to a user account. Every write resolves the
  student through `_resolve_student` and every read through `_student_for_read` /
  `_scoped_read_owner`.

**403 on foreign ids.** Whenever a request carries a valid bearer token, touching
a `student_id` that belongs to a *different* account is rejected with **403**,
independent of `REQUIRE_AUTH`. Being authenticated always isolates you to your
own students; ownership never changes hands. Ownership is resolved *before* any
retrieval or LLM work runs, so a foreign id is rejected without wasting work.

With `REQUIRE_AUTH=true`, a valid bearer token is required on every data
endpoint (401 otherwise), giving true multi-tenant isolation on a shared
deployment.

## Authentication

- **Passwords** are hashed with **bcrypt** (per-password salt); plaintext is
  never stored or logged. Inputs longer than bcrypt's 72-byte limit are rejected
  explicitly rather than silently truncated.
- **Access tokens** are **JWTs signed with HS256** carrying a `sub` claim and an
  `exp` expiry (`JWT_EXPIRE_MINUTES`, default 60). Expired, malformed, or
  bad-signature tokens are rejected with 401.
- **Generic login errors.** `/auth/login` returns the same 401 message for an
  unknown email and a wrong password, so it does not reveal which accounts exist.
- **`JWT_SECRET` must be overridden.** The shipped default
  (`dev-insecure-change-me`) is a placeholder for local development only. Anyone
  who knows it can forge valid tokens. To prevent a public deploy from silently
  running with a forgeable secret, **the application refuses to start when
  `REQUIRE_AUTH=true` and `JWT_SECRET` is the default or shorter than 16
  characters** — it fails fast with a clear error telling the operator to set a
  strong, random secret. With `REQUIRE_AUTH=false` (local dev) the placeholder is
  left alone so single-user runs are unaffected.
- **Token storage note.** The web client stores the bearer token in the
  browser's `localStorage`. This keeps the token readable by JavaScript on the
  origin, so it is exposed to any cross-site scripting on the frontend; it is a
  deliberate simplicity trade-off. Serve the app over TLS from a trusted origin,
  keep token lifetimes short, and treat frontend XSS as a token-compromise risk.

## Transport, CORS, rate limiting, and API key

- **Security headers** are always sent: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- **HSTS** (`Strict-Transport-Security`) is added only when `ENABLE_HSTS=true`,
  so enable it once the deployment is served over HTTPS.
- **CORS** is configurable via `CORS_ORIGINS` (comma-separated allow-list;
  default is the local frontend only). Set it to the exact deployed frontend
  origin(s) in production — do not use a wildcard, since credentialed requests
  are allowed.
- **Rate limiting** is applied per client when `RATE_LIMIT_PER_MINUTE` is
  positive; it is a no-op (unthrottled) by default for local dev.
- **Optional API key.** When `API_KEY` is set, data endpoints additionally
  require a matching `X-API-Key` header (401 otherwise). This guard is
  independent of user auth; the two coexist.
- **Structured logging** carries a request id per request and never logs
  passwords or tokens; a catch-all handler returns a generic 500 without leaking
  internals.

## Secrets handling

- Provider keys (`OPENAI_API_KEY`), `JWT_SECRET`, `QDRANT_API_KEY`, and `API_KEY`
  are read from the environment or a local `.env` file and are never committed.
- Course PDFs and personal data are never committed.
- Configuration is centralized in `core/config.py` (pydantic settings); override
  via environment variables in production. Do not bake secrets into images or
  compose files.

## Deployment checklist (safe public deploy)

Before exposing the API to the network, set **all** of the following:

- [ ] `REQUIRE_AUTH=true` — every data endpoint requires a valid bearer token.
- [ ] `JWT_SECRET` = a strong, random value (≥ 16 chars; use many more). The app
      will refuse to boot under `REQUIRE_AUTH` if this is still the default or too
      short.
- [ ] `CORS_ORIGINS` = the exact deployed frontend origin(s), no wildcard.
- [ ] Serve over **TLS** and set `ENABLE_HSTS=true`.
- [ ] `RATE_LIMIT_PER_MINUTE` set to a sane positive value.
- [ ] Provider key (`OPENAI_API_KEY`) is **capped/budgeted** on the provider side
      (or the deployment is gated by `API_KEY`) to bound cost exposure.
- [ ] `QDRANT_API_KEY` set when using a hosted/Qdrant Cloud instance.
- [ ] Secrets injected from the environment / secret manager, never committed.

## Residual risks / known limitations

- **Token in `localStorage`.** As noted above, the web client stores the JWT in
  `localStorage`, so frontend XSS can exfiltrate a token until it expires. There
  is no server-side token revocation list; shortening `JWT_EXPIRE_MINUTES` limits
  the exposure window.
- **Owner-less corpus is invisible, not shared.** Under strict isolation, chunks
  with no `owner` (ingested via the CLI or before per-account scoping) match no
  account's reads and are therefore invisible in the UI (not listed, not
  retrievable, not deletable). They are not a cross-tenant risk; ingest material
  through the API (which owner-stamps it) so it is visible to its account.
- **No account lifecycle.** There is no email verification, password reset, or
  account lockout/throttling on repeated login attempts beyond the global rate
  limit. Add these before treating the service as production-grade multi-tenant.
- **Cost-based denial of service.** A determined authenticated caller can still
  drive LLM/provider cost within the configured rate limit; rely on provider-side
  caps and the rate limiter to bound it.
- **LLM output.** Answers are grounded and citation-checked, but the faithfulness
  guard is a mitigation, not a guarantee; treat generated content accordingly.
