# Technology decisions

One note per major dependency. Each answers the same four questions:

1. **What role does it play** in the system?
2. **Why it, and not the alternative** that was seriously considered?
3. **What does it cost** — every choice has a downside, and the downside is documented.
4. **What was measured**, where a claim can be measured rather than asserted.

These are decision records, not tutorials. They exist so that a future maintainer (or a
future me) can tell which choices were reasoned, which were defaults, and which are
already known to be wrong.

| Note | Subject |
| --- | --- |
| [rag.md](rag.md) | Retrieval-augmented generation: grounding, citation-by-construction, the refusal guards |
| [embeddings.md](embeddings.md) | `BAAI/bge-m3`, chunking strategy, why the similarity classes overlap |
| [qdrant.md](qdrant.md) | Vector store, payload filtering, HNSW, owner isolation |
| [evaluation.md](evaluation.md) | LLM-as-a-judge, faithfulness, threshold calibration |
| [fastapi.md](fastapi.md) | Async API, Pydantic validation, dependency injection, SSE streaming |
| [langchain.md](langchain.md) | Provider abstraction, the per-role model factory |
| [langgraph.md](langgraph.md) | The agent graph, and why it is not on the serving path |
| [langfuse.md](langfuse.md) | LLM observability, and why request logs are insufficient |
| [nextjs.md](nextjs.md) | Frontend, client/server boundary, consuming an SSE token stream |
| [database.md](database.md) | SQLAlchemy, Alembic, SQLite in dev and Postgres in production |
| [auth-security.md](auth-security.md) | JWT, bcrypt, multi-tenant isolation, residual risks |
| [deployment.md](deployment.md) | Docker image, hosting topology, CI gates |

## The central design argument

Retrieval is the easy half. The hard half is **making the model structurally unable to
misrepresent the source material**. Two mechanisms carry that weight, and most of the
decisions recorded here exist to serve them:

**Citations are produced by construction.** The model is shown numbered sources
`[1] [2] [3]` and never a page number. It cites indices; the code maps each index back to
the real chapter and page from the chunk's payload. The model cannot invent a page number
because it never handles one — this is a structural property, not a prompt instruction.

**Refusal is guarded three times**, and only one of the three is the model itself: a
similarity floor that runs before any LLM call, the grounded prompt, and a deterministic
check that drops any answer citing no source at all.

Measured on the live deployment: **100% citation rate**, **96% refusal accuracy** (22 of 23
out-of-scope requests). See [evaluation.md](evaluation.md) for the method.
