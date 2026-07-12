"""Tests for core.errors: translating opaque provider capacity errors."""

import pytest
from fastapi import HTTPException

from core.errors import (
    FREE_TIER_CAPACITY_MESSAGE,
    GENERIC_ERROR_MESSAGE,
    OWN_KEY_CAPACITY_MESSAGE,
    describe_capacity_error,
    friendly_llm_error_message,
    raise_friendly_llm_error,
)


class _StatusError(Exception):
    """Stand-in for the openai/groq/anthropic ``APIStatusError`` family."""

    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.parametrize("status_code", [413, 429])
def test_describe_capacity_error_free_tier(status_code):
    message = describe_capacity_error(_StatusError(status_code), used_own_key=False)
    assert message == FREE_TIER_CAPACITY_MESSAGE


@pytest.mark.parametrize("status_code", [413, 429])
def test_describe_capacity_error_own_key(status_code):
    message = describe_capacity_error(_StatusError(status_code), used_own_key=True)
    assert message == OWN_KEY_CAPACITY_MESSAGE


def test_describe_capacity_error_ignores_unrelated_status():
    assert describe_capacity_error(_StatusError(500), used_own_key=False) is None


def test_describe_capacity_error_ignores_plain_exception():
    assert describe_capacity_error(ValueError("nope"), used_own_key=False) is None


def test_raise_friendly_llm_error_raises_http_413_for_capacity_error():
    with pytest.raises(HTTPException) as exc_info:
        raise_friendly_llm_error(_StatusError(413), used_own_key=False)
    assert exc_info.value.status_code == 413
    assert exc_info.value.detail == FREE_TIER_CAPACITY_MESSAGE


def test_raise_friendly_llm_error_is_a_noop_for_unrelated_errors():
    raise_friendly_llm_error(ValueError("nope"), used_own_key=False)  # does not raise


def test_friendly_llm_error_message_returns_capacity_message():
    assert (
        friendly_llm_error_message(_StatusError(429), used_own_key=True) == OWN_KEY_CAPACITY_MESSAGE
    )


def test_friendly_llm_error_message_never_leaks_raw_exception():
    # A non-capacity error must fall back to the generic message and never carry
    # the raw exception text into a streamed error event.
    message = friendly_llm_error_message(ValueError("secret /etc/passwd trace"), used_own_key=False)
    assert message == GENERIC_ERROR_MESSAGE
    assert "secret" not in message
