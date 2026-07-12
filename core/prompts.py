"""Shared prompt fragments for the grounded answer, exercise and quiz surfaces.

The refusal sentence and the output-language directive are used by ``core.answer``
and the ``generate``/``quiz`` agent nodes alike. Keeping them here lets those
modules share one definition instead of reaching into a private helper of
``core.answer``.
"""

# The exact sentence emitted when nothing in the course covers a request. It is
# compared verbatim to detect a refusal, so every surface must use this constant.
REFUSAL = "This is not covered in the course material."

# Locale codes the UI sends, mapped to the language name used in the prompt.
_LANGUAGE_NAMES = {"en": "English", "fr": "French", "nl": "Dutch"}


def language_instruction(language: str | None, *, subject: str = "the answer") -> str:
    """Build the output-language directive for a grounding system prompt.

    ``subject`` names what must be written ("the answer", "the exercise", "the
    quiz"), so the same directive is reusable across the answer, exercise and
    quiz prompts. With no explicit ``language`` we keep the original behavior:
    write in the request's own language. With a locale code ('en'/'fr'/'nl') we
    make that language the strong default that overrides the sources' language,
    while still deferring to an explicit request for another language. The
    wording is deliberately forceful so a weak local model does not default to
    the (usually English) source language.
    """
    if language is None:
        return (
            f"- Write {subject} in the same language as the request, unless it "
            "explicitly asks for another language.\n"
        )
    name = _LANGUAGE_NAMES.get(language, "English")
    return (
        f"- Write {subject} in {name}, even if the sources are written in another "
        "language, unless the request explicitly asks for another language. Only "
        "the prose is translated: keep all mathematics, notation and symbols "
        "exactly as they appear in the sources.\n"
    )
