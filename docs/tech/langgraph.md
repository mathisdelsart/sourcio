# LangGraph

## Status in this system

`agent/graph.py` implements the tutor's routing as a LangGraph router and state graph. It is
tested and maintained as a **reference implementation of the agentic design**.

**It is not on the serving path.** No API module imports it. Every endpoint (`/ask`,
`/exercise`, `/grade`, `/quiz`) dispatches directly to its node in `agent/nodes/`.

This is deliberate, and the rationale is recorded below rather than left to be inferred.

## Why the serving path is not agentic

The product exposes **explicit endpoints**. The client already knows whether it wants an
answer, an exercise or a quiz — that information is in the request. Routing it through an
LLM router would spend a model call to recover an intent that was never lost, and would add
a failure mode (a misrouted request) that cannot otherwise occur.

An agent framework earns its place when the next step **depends on the model's output**. Here
it does not.

| Warrants a graph | Does not |
| --- | --- |
| The next step depends on what the model produced | The step is known from the request (this system) |
| Loops: generate → critique → regenerate | A straight-line pipeline |
| Multi-agent hand-off | One call, one answer |
| Durable state, human-in-the-loop pauses | Stateless request/response |

The graph is retained because the agentic formulation is what would be needed the moment the
intent becomes genuinely ambiguous or a flow becomes multi-step, and keeping it tested means
that transition is a routing change rather than a rewrite.

## What LangGraph provides

A library for **stateful, cyclic** LLM workflows expressed as a graph.

- **State** — a typed dict threaded through the graph. Here `TutorState`: the message, the
  student id, course and chapter filters, the retrieved chunks, the answer. Each node receives
  it and returns a partial update, which is merged.
- **Nodes** — plain functions, `state -> partial state`. There is nothing framework-specific
  about them, which is exactly why they can be (and are) called directly in production.
- **Edges** — fixed (`A → B`) or **conditional** (`A → f(state) → B | C`).
- **Cycles** — the substantive difference from a chain. A chain is a DAG; a graph can loop.

## LangGraph and LangChain

Complementary, not competing:

- **LangChain** — components (models, prompts, retrievers) and a DAG to compose them (LCEL).
  Directed, **acyclic**.
- **LangGraph** — a state machine that can branch and loop, from the same authors, for the
  cases the DAG cannot express.

This project uses LangChain for the model factory ([langchain.md](langchain.md)) and
LangGraph only in the reference graph.

## Concepts referenced in the codebase

- **ReAct** — *reason + act*: the model alternates reasoning and tool calls until it can
  answer. The canonical agent loop.
- **Tool calling** — the model emits a structured `{name, args}` request rather than prose;
  the application executes it and returns the result.
- **Checkpointing** — persisting graph state so a run can be suspended and resumed. Supported
  by LangGraph; not required here.
