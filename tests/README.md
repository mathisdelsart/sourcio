# tests/

The pytest suite: 841 tests, green in CI behind a coverage gate (>=84%). Tests run with **no paid API
calls** — every LLM, judge, retriever, sleep, and database session is injectable, so the suite stubs
them and exercises real code paths deterministically.

## Layout

Tests mirror the packages they cover, one file per area:

- **Ingestion** — `test_extract.py`, `test_ingest_text.py`
- **Retrieval and grounding** — `test_retrieval.py`, `test_grounding.py`, `test_hybrid.py`, `test_hyde.py`, `test_neighbors.py`, `test_query.py`, `test_source.py`, `test_courses.py`, `test_documents.py`
- **Agent** — `test_agent.py`, `test_quiz.py`, `test_spaced_repetition.py`
- **API** — `test_api.py`, `test_auth.py`, `test_ownership.py`, `test_multiuser.py`, `test_sessions.py`, `test_feedback.py`, `test_cors.py`, `test_middleware.py`, `test_errors.py`
- **Storage** — `test_db.py`, `test_migrations.py`, `test_storage.py`, `test_postgres_backend.py`
- **Config and observability** — `test_config.py`, `test_budget.py`, `test_obs.py`, `test_observability.py`, `test_latency.py`
- **Eval** — `test_eval.py`, `test_eval_report.py`, `test_benchmark.py`, `test_calibrate.py`, `test_ab_retrieval.py`

## Run it

```bash
uv run python -m pytest -q                    # or: make test
uv run python -m pytest tests/test_api.py -q  # one area
make check                                     # lint + format check + tests (mirrors CI)
```
</content>
