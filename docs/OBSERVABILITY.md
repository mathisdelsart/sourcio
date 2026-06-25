# Observability (LangFuse tracing)

Tracing is **fully opt-in** and **zero-cost when off**. With no LangFuse
credentials in the environment, every LLM call passes an empty callback list
(`[]`), which is a harmless no-op, so behavior and cost are unchanged.

## What is traced

When enabled, each LLM step in the pipeline becomes a LangFuse-traced
observation with its latency, token usage and estimated cost:

- **Router** — intent classification (`agent/graph.py`).
- **Explain** — the grounded answer, both the blocking and the streaming
  variant (`core/answer.py`); the agent `explain` node delegates here.
- **Generate** — exercise + reference solution (`agent/nodes/generate.py`).
- **Grade** — the product judge that marks the student's answer
  (`agent/nodes/grade.py`).
- **Reexplain** — the level-aware rephrasing (`agent/nodes/reexplain.py`).
- **Judge** — the offline faithfulness/relevance judge used by the evaluation
  harness (`eval/run_eval.py`).

Retrieval and per-stage latency are tracked separately by the in-process timer
in `core/obs.py` (see the metrics dashboard).

## How it works

`core/obs.get_callbacks()` returns a list with a LangFuse `CallbackHandler`
when credentials are present, or `[]` otherwise. Each call site passes that
list through the invocation config:

```python
get_llm("explain").invoke(messages, config={"callbacks": get_callbacks()})
```

The handler reads its credentials from the environment, so no keys are hard
coded anywhere.

## How to enable

1. Get LangFuse credentials, either way works:
   - **Cloud (free tier):** sign up at <https://cloud.langfuse.com> and create a
     project; copy its public and secret keys.
   - **Self-host:** run LangFuse locally (Docker) and create a project the same
     way; point `LANGFUSE_HOST` at your instance.
2. Install the optional extra:

   ```bash
   uv sync --extra obs
   ```

3. Set the three environment variables (e.g. in `.env`):

   ```bash
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
   ```

   Tracing activates only when **both** keys are set; `LANGFUSE_HOST` defaults to
   the cloud endpoint when omitted.

4. Run any query (an `/ask` call, an agent turn, or the eval harness). Open the
   LangFuse UI and the traces — retrieval → LLM → judge — appear with latency,
   tokens and cost.

To turn tracing off again, unset the keys: the pipeline returns to the
zero-overhead no-op path.
