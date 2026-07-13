# FastAPI

## Role in the system

The HTTP layer: request validation, authentication, dependency wiring, streaming, and the
error contract. It is a JSON API only — the frontend is a separate Next.js application, and
nothing is server-rendered here.

## Why FastAPI

| | Assessment |
| --- | --- |
| **Django** | Batteries included — ORM, admin, templates, auth. Almost none of it is wanted: there is no server rendering, and the ORM would be the only component used. Disproportionate for a JSON API. |
| **Flask** | Synchronous by default, and provides nothing for validation or API documentation. Request models, error shapes and OpenAPI would all be hand-rolled. |
| **Starlette** | FastAPI is Starlette plus Pydantic and dependency injection. Using it directly means reimplementing both. |
| **FastAPI** (chosen) | Async-first, validation and OpenAPI derived from type hints, first-class dependency injection. |

The decisive property is **async**. A request in this system spends nearly all of its life
waiting — on Qdrant, on an LLM provider, on the database. Under a synchronous framework each
waiting request occupies a worker thread. Under async the event loop suspends it and serves
another. Concurrency here is bounded by I/O, which is the case async exists for.

## Validation as type declaration

```python
class AskRequest(BaseModel):
    student_id: str
    question: str
    k: int = 5
    course: str | None = None
```

Declaring the model enforces it: a malformed payload is rejected with a **422** and a precise
error before any application code runs. The same model generates the OpenAPI schema, so
`/docs` cannot drift from the implementation — it is not maintained, it is derived.

## Dependency injection

```python
def ask(request: AskRequest, user: UserOut | None = DataUser, key: str | None = OpenAIKey):
```

`DataUser` resolves the JWT and the caller's identity; `OpenAIKey` extracts the visitor's
optional per-request provider key from a header. Declared once, reused across routers.

The property that matters most is that dependencies are **overridable in tests**. This is
why the entire suite — 853 tests — runs with an in-memory database, monkeypatched nodes, no
network and no model load. A test suite requiring an API key is a test suite that does not
get run.

## Streaming (Server-Sent Events)

Answers stream token by token. This is not cosmetic: a grounded answer takes several
seconds, and silence for that long reads as a failure.

**SSE rather than WebSockets**, because the data flows in one direction only:

| | SSE | WebSocket |
| --- | --- | --- |
| Direction | Server → client | Bidirectional |
| Protocol | Plain HTTP | Upgrade handshake |
| Reconnection | Built in | Application's responsibility |
| Fit | A token feed | Chat rooms, collaborative editing |

SSE is the smaller mechanism that fits the requirement, and it traverses proxies that
mishandle WebSocket upgrades.

### The constraint SSE imposes on error handling

**Once the response body has begun, an `HTTPException` cannot be raised** — the status line
is already on the wire. If the LLM fails mid-stream there is no 500 available.

Streaming endpoints therefore emit the error **in band**:

```
data: {"type": "error", "message": "..."}
```

The message is a client-safe one, never `str(exc)`, which would leak internal detail to the
browser. Tests assert precisely this: the raw exception text must not appear in the response
body.

## Error contract

- **Explicit `HTTPException`** for anything the client can act on. Provider capacity errors
  (413/429) are translated into a **413** carrying an actionable message — telling the caller
  to supply their own API key — rather than surfacing an opaque provider error.
- **Everything unexpected** falls through to a global handler returning a **generic 500**.
  The raw exception never reaches the client.
- **`X-Request-ID`** on every request, so a user-reported error maps to the server log that
  explains it.

## Testing note

`TestClient` **re-raises server exceptions by default**, which means a test of the global 500
handler never actually exercises the handler. `TestClient(app, raise_server_exceptions=False)`
is required. This project had that gap: the handler appeared covered and was not.

## Async discipline

`async def` for I/O. Plain `def` for CPU-bound or blocking libraries — FastAPI runs those in
a threadpool, so they do not stall the loop. The failure mode to avoid is a **blocking call
inside `async def`**, which freezes the event loop for every concurrent user, not only the
caller.
