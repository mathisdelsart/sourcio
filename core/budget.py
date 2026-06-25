"""Opt-in token budget guard for the LLM factory.

A lightweight LangChain callback accumulates the token usage reported by LLM
results and raises `BudgetExceeded` once a configured cap is reached. This is a
cost guard for development: it is off by default and only activates when a
positive cap is configured.

The guard reads token counts straight from `LLMResult`, so it never makes a
network call or imports a provider SDK.
"""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class BudgetExceeded(RuntimeError):
    """Raised when accumulated token usage exceeds the configured cap."""


def _extract_total_tokens(response: LLMResult) -> int:
    """Best-effort extraction of total tokens from an `LLMResult`.

    Token usage is reported differently across providers and LangChain versions.
    This reads the common `llm_output` usage block and falls back to per-message
    `usage_metadata` on the generations. Missing data counts as zero tokens.
    """
    total = 0

    # 1) Provider-level usage, e.g. {"token_usage": {"total_tokens": N}}.
    llm_output = response.llm_output or {}
    usage = llm_output.get("token_usage") or llm_output.get("usage") or {}
    total_tokens = usage.get("total_tokens")
    if isinstance(total_tokens, int):
        total += total_tokens
    else:
        prompt = usage.get("prompt_tokens") or 0
        completion = usage.get("completion_tokens") or 0
        total += int(prompt) + int(completion)

    # 2) Per-generation metadata, e.g. chat models exposing `usage_metadata`.
    if total == 0:
        for batch in response.generations:
            for generation in batch:
                message = getattr(generation, "message", None)
                meta = getattr(message, "usage_metadata", None)
                if isinstance(meta, dict):
                    total += int(meta.get("total_tokens") or 0)

    return total


class BudgetCallbackHandler(BaseCallbackHandler):
    """Accumulate token usage and stop once the cap is reached.

    A non-positive cap disables the guard entirely (it never raises).
    """

    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self.total_tokens = 0

    def on_llm_end(self, response: LLMResult, **kwargs: Any) -> None:
        self.total_tokens += _extract_total_tokens(response)
        if self.max_tokens > 0 and self.total_tokens > self.max_tokens:
            raise BudgetExceeded(
                f"Token budget exceeded: {self.total_tokens} tokens used, cap is {self.max_tokens}."
            )


# Process-wide cache of budget handlers, keyed by cap. The cost guard must be
# cumulative across every `get_llm` call in the process, so each distinct cap
# maps to a single shared handler whose `total_tokens` accumulates over time.
_HANDLERS: dict[int, BudgetCallbackHandler] = {}


def get_budget_handler(max_tokens: int) -> BudgetCallbackHandler:
    """Return the shared budget handler for `max_tokens`, creating it once.

    A single handler instance is reused for a given cap so token usage adds up
    across all LLM calls in the process, instead of resetting on every call.
    """
    handler = _HANDLERS.get(max_tokens)
    if handler is None:
        handler = BudgetCallbackHandler(max_tokens)
        _HANDLERS[max_tokens] = handler
    return handler


def get_budget_callbacks(max_tokens: int) -> list:
    """Return budget callbacks for the configured cap, or `[]` when disabled.

    A cap of zero (or negative) means no budget is enforced and an empty list is
    returned, so the factory attaches nothing. For a positive cap the same shared
    handler is returned every time, so usage accumulates process-wide and the cap
    actually trips on cumulative tokens.
    """
    if max_tokens and max_tokens > 0:
        return [get_budget_handler(max_tokens)]
    return []
