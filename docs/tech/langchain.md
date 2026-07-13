# LangChain

## Role in the system

One job, done at one call site: **provider abstraction**.

```python
# core/llm.py
llm = init_chat_model(model, temperature=0, api_key=key)
```

`get_llm(role)` returns a chat model for OpenAI, Anthropic, Groq or Ollama, selected by
environment variable. Everything downstream — answering, grading, quiz generation, vision
extraction, the offline judge — talks to that single interface.

The value is concrete: **the provider is a configuration change, not a code change.** The
system runs entirely on a free Groq tier, entirely locally on Ollama, or on OpenAI, without
touching application code. Reimplementing that across four SDKs, each with its own
authentication scheme and response shape, would be significant work for no differentiating
benefit.

## The per-role factory

There is not one model. There is one model **per role**:

```
LLM_EXTRACT   -> vision; transcribes scanned and math-heavy PDF pages
LLM_GENERATE  -> writes exercises
LLM_GRADE     -> grades the student's answer
LLM_JUDGE     -> offline faithfulness judge
LLM_ROUTER    -> intent routing (reference graph only)
```

The roles have genuinely different requirements. Extraction **requires** vision, so it always
resolves to OpenAI — neither Groq nor Ollama offers a comparable vision model. Grading wants
a strong reasoner. Routing is a cheap classification. One control per role allows spend to be
directed where it changes the output.

**Per-request keys.** A visitor may supply their own provider key on a header. `get_llm`
detects the provider from the key prefix (`sk-ant-` → Anthropic, otherwise OpenAI) and
switches *that call* to their model, billed to them. The key lives on the returned instance
for the duration of one call: never cached, never logged, never persisted. The response cache
keys on prompt and model and **deliberately never on the key**, so one caller's key cannot be
persisted into a cache another caller could hit.

## What the abstraction costs

- **API churn.** LangChain moves quickly and breaks across minor versions; `langchain-core`
  is pinned for that reason.
- **It hides the prompt.** A helper that "just works" is a helper that cannot be debugged
  when the model misbehaves. Prompts here are therefore kept as **explicit strings** in
  `agent/nodes/*` rather than as LangChain prompt templates — when the benchmark surfaced a
  quiz question offering two equivalent correct options, the fix required reading the exact
  words the model was given.
- **It invites over-adoption.** Chains, agents, memory and retrievers are all available and
  none of them are used. Retrieval is written directly against the Qdrant client, because
  retrieval *is* the product and abstracting it would mean not owning it.

The scope of adoption is: the model factory, and the callback hook. Nothing else.

## Callbacks

The extension point through which observability and cost control attach, without any call
site being aware of them:

```python
callbacks = get_callbacks() + get_budget_callbacks(get_settings().llm_budget_tokens)
if callbacks:
    llm = llm.with_config(callbacks=callbacks)
```

`get_callbacks()` returns `[]` unless LangFuse is configured; `get_budget_callbacks()`
returns `[]` unless a token budget is set. When both are off, the model instance is returned
unchanged and the default path is byte-identical.

This conditional creates a **second code path that only exists when a feature is enabled** —
which produced a real test-isolation defect. See [langfuse.md](langfuse.md).

## Configuration notes

**`temperature=0` everywhere.** Not because it is strictly deterministic, but because a tutor
citing sources should not be creative: any variation in output is variation that cannot be
explained.

**LCEL** (`prompt | model | parser`) composes runnables into a DAG and provides streaming and
batching for free. It is barely used here: the pipeline is three explicit steps, and a pipe
would obscure them rather than simplify them.
