# db/

The relational store: SQLAlchemy 2.0 declarative models and the engine/session layer. Holds accounts,
students, exercises with their reference solutions, grades, quizzes, conversation history, threads,
and feedback. Vectors live in Qdrant, not here.

## Files

| File | Responsibility |
| --- | --- |
| `models.py` | Declarative models: `User`, `Student`, `Exercise`, `Grade`, `Quiz`, `QuizQuestion`, `Session`, `Message`, `Feedback`, `Review`. Only portable column types, so the same schema runs on SQLite and PostgreSQL. |
| `session.py` | Engine and session helpers driven by `Settings.database_url`. The engine is created lazily (no connection at import), so swapping SQLite for PostgreSQL is a URL change. |

Migrations are managed by Alembic in [`../alembic/`](../alembic/), which resolves the same
`DATABASE_URL` at runtime and diffs against the declarative `Base`.

## How it fits

`agent/persistence.py` and the API layer write through these models; ownership links (`Student.user_id`)
enforce per-account data isolation. Model relationships and the account/ownership design are documented
in [../docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md).

## Run it

```bash
# Default is SQLite (sqlite:///./app.db); nothing to install.
uv run --extra migrations alembic upgrade head     # apply migrations
make reset-db                                        # wipe the local dev DB after a schema change
uv run python -m pytest tests/test_db.py tests/test_migrations.py -q
```

Switching to PostgreSQL: [../docs/OPERATIONS.md](../docs/OPERATIONS.md).
</content>
