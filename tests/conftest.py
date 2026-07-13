"""Shared test fixtures.

The suite is hermetic in CI, where no `.env` exists. On a developer machine the
project's `.env` is loaded by pydantic-settings, so anything configured there
(LangFuse keys, a token budget) silently leaks into the tests and changes what
the code under test does -- `core.llm.get_llm`, for instance, only wraps the
model in `.with_config(...)` when callbacks are enabled. Neutralize that env up
front so a local run matches CI. Tests that want a feature on still set the vars
themselves; this fixture runs first, so their `setenv` calls win.
"""

import pytest

from core.config import get_settings

_AMBIENT_ENV = (
    "LANGFUSE_PUBLIC_KEY",
    "LANGFUSE_SECRET_KEY",
    "LANGFUSE_HOST",
    "LLM_BUDGET_TOKENS",
)


@pytest.fixture(autouse=True)
def _isolate_ambient_env(monkeypatch):
    for var in _AMBIENT_ENV:
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
