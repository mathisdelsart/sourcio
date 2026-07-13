# Authentication and isolation

Companion to [SECURITY.md](../../SECURITY.md), which holds the threat model, the deployment
checklist and the reporting policy. This note records the *decisions* behind the controls.

## Two postures

The security requirements differ fundamentally between the two ways this system runs, and the
defaults are set for the first:

- **Local, single user.** API on localhost, one person, a SQLite file. The trust boundary is
  the machine. Authentication is optional (`REQUIRE_AUTH=false`).
- **Shared or public.** The adversary is any remote client — including an authenticated but
  hostile tenant attempting to read another tenant's documents. This posture requires the full
  deployment checklist, and the local defaults are insufficient for it.

## Passwords — bcrypt

A hash is stored, never the password. Bcrypt provides a per-password **salt** (so identical
passwords produce different hashes, defeating precomputed tables) and a tunable **work factor**
that makes verification deliberately slow — negligible for a login, prohibitive for a brute
force.

**Bcrypt truncates at 72 bytes, silently.** A longer passphrase is only as strong as its first
72 characters, and two distinct long passwords can collide. Inputs exceeding the limit are
therefore **rejected explicitly** rather than silently truncated.

Argon2 is the stronger modern recommendation (memory-hard, which reduces the attacker's GPU
advantage). Bcrypt remains appropriate here. Fast hashes — MD5, bare SHA-256 — are unsuitable
by construction: speed is the attacker's asset.

## JWT

A signed token carrying `sub` (the user id) and `exp` (expiry).

**Signed, not encrypted.** Anyone holding the token can read its payload. Signing establishes
that it has not been tampered with; it does not make it confidential. Nothing sensitive is
placed in it.

**Stateless by design**: the server verifies the signature and trusts the claims, with no
session store to consult and nothing to share across replicas.

**The cost of statelessness is revocation.** A stolen token remains valid until it expires.
This is mitigated by a short lifetime (60 minutes by default) and accepted as a trade-off; a
denylist would reintroduce exactly the state the design avoids.

**`JWT_SECRET` must be strong.** Anyone who knows it can forge a token for any user. The
shipped default is an obvious development placeholder, and the application **refuses to start**
when `REQUIRE_AUTH=true` and the secret is still the default or shorter than 16 characters. It
fails closed rather than quietly serving a forgeable secret.

## Multi-tenant isolation

Authentication establishes *who*. Isolation establishes *what may be seen*, and it is where
leaks occur. It is enforced in two layers that must agree.

**Vector store.** Every chunk carries an `owner` in its payload, and every read applies a
strict filter at the database, not in application code:

```python
Filter(must=[FieldCondition(key="owner", match=MatchValue(value=owner))])
```

- **No shared branch.** A chunk with no owner matches **nobody**, not everybody — closing the
  common leak in which material ingested before per-account scoping remains visible to all.
- **Fail closed.** If the effective owner resolves to `None`, reads return empty and deletes
  remove nothing.
- **Existence is not disclosed.** `GET /source/{chunk_id}` returns **404** for a chunk owned by
  another account — not 403 — so ids cannot be probed to discover another account's material.

**Relational store.** All records hang off `Student`, and `Student.user_id` binds a student to
an account. Touching a `student_id` belonging to another account returns **403**, resolved
**before** any retrieval or LLM work runs, so a hostile identifier is rejected without incurring
cost.

**This is verified, not assumed.** The endpoint benchmark includes a question whose subject is
covered only by *another account's* indexed corpus; the benchmark account is correctly refused.
An answer there would be a cross-tenant breach rather than a quality regression.

## Transport, CORS, rate limiting

- Security headers are always sent: `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`.
- **HSTS** is opt-in, because it is meaningless without TLS.
- **CORS** is an explicit allow-list of origins. A wildcard is never used, as credentialed
  cross-origin requests are permitted.
- **Rate limiting**: `RATE_LIMIT_PER_MINUTE=0` means *auto*, not *off* — unthrottled locally,
  but **60 requests/minute as soon as `REQUIRE_AUTH=true`**, so a public deployment is never
  accidentally unlimited. A safe default is preferred to a documented one.
- **Login errors are generic.** The same 401 is returned for an unknown username and for a
  wrong password, so the endpoint is not an account-existence oracle.

## Residual risks

Documented rather than claimed to be absent:

- **Token in `localStorage`.** Readable by JavaScript on the origin, so any frontend XSS is a
  token compromise. A deliberate simplicity trade-off; the alternative — an `HttpOnly` cookie —
  requires CSRF protection and a same-site story against a cross-origin API. Short expiry bounds
  the exposure window.
- **No revocation list.** As above.
- **Cost-based denial of service.** An authenticated caller can consume provider budget within
  the rate limit; this is bounded by provider-side caps, not by the application.
- **No account lifecycle.** No email verification, password reset, or lockout on repeated login
  attempts beyond the global rate limit.

## Deployment note

A connection string is a credential. `DATABASE_URL` belongs in the platform's **secret** store,
not among its public variables — the distinction is not cosmetic, and platforms that offer both
expect it to be observed.
