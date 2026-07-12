# agent/

The agentic orchestration layer: a LangGraph `StateGraph` that routes a student's message to the right
node. Nodes own no retrieval logic of their own — they delegate to `core/` so the grounding guarantees
live in one place. The deployed API calls these nodes directly through explicit endpoints; the graph
(`graph.py`) is kept as a tested reference of the routing/state design, not the request path (see
[../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)).

## Structure

| File | Responsibility |
| --- | --- |
| `graph.py` | Builds the graph and the router. `classify_intent` asks `get_llm("router")` for one intent label, with a deterministic keyword fallback so it never emits an invalid route. `langgraph` is imported lazily, so nodes stay unit-testable without the `agent` extra. |
| `state.py` | `TutorState`, the single TypedDict threaded through the graph. Keys are `total=False`, so each node writes only its own output key. |
| `persistence.py` | Best-effort, fully optional persistence of generated exercises and grades. A no-op without a `student_id` or a configured database; the session factory is injectable for tests. |
| `nodes/explain.py` | RAG explanation — delegates to `core.answer.answer` and appends the turn to history. |
| `nodes/generate.py` | Builds an exercise plus a reference solution strictly from retrieved chunks; refuses when nothing is retrieved. The solution is stored server-side, never returned. |
| `nodes/grade.py` | Judge #1 (product): marks the student's answer against the reference solution, returning a score and feedback. Distinct from the eval faithfulness judge. |
| `nodes/reexplain.py` | Rephrases the last answer at a chosen level (beginner / intermediate / advanced), reusing history instead of re-retrieving. |
| `nodes/quiz.py` | `generate_quiz` / `grade_quiz_answer` — a multi-question grounded quiz with server-side solutions, graded by the same product judge as `grade`. |

## How it fits

```
         +-- explain    RAG -> grounded, sourced explanation
router --+-- generate   exercise + reference solution (server-side)
         +-- grade      LLM-as-a-judge marks the student's answer
         +-- reexplain  level-aware rephrase, keeps memory
```

The API layer (`api/`) invokes these nodes directly (one explicit endpoint each); grounding and
citation come from `core/`. See [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Test it

```bash
uv run python -m pytest tests/test_agent.py tests/test_quiz.py -q
```
</content>
