"""grade node: LLM-as-a-judge scoring the student's answer.

Scores the answer against the reference solution and returns score, feedback and criteria.
Distinct from the system-evaluation judge (faithfulness) under eval/.

This is judge #1 (the product feature). It marks the student's answer, ideally
against the reference solution of a previously generated exercise, and returns a
numeric score plus feedback.
"""

import json
import re

from agent.state import TutorState
from config import get_llm

_SYSTEM = (
    "You are a strict but fair grader for a course tutor.\n"
    "- Grade the student's answer against the reference, if one is provided.\n"
    "- Reward correct method and the course's notation; penalize errors.\n"
    'Reply with JSON only: {"score": <int 0-100>, "feedback": "<short feedback>"}'
)


def _parse(raw: str) -> dict:
    """Parse the judge's JSON verdict, tolerating extra surrounding text."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            return {
                "score": int(data.get("score", 0)),
                "feedback": str(data.get("feedback", "")).strip(),
            }
        except (ValueError, TypeError):
            pass
    # If the verdict is unparseable, surface it as feedback rather than guess.
    return {"score": 0, "feedback": raw.strip()}


def grade(state: TutorState) -> TutorState:
    """Grade ``state['message']`` (the student's answer) and return a verdict."""
    exercise = state.get("exercise") or {}
    reference = exercise.get("solution", "")

    human = f"Reference solution:\n{reference}\n\nStudent answer:\n{state['message']}"
    raw = get_llm("grade").invoke([("system", _SYSTEM), ("human", human)]).content.strip()

    verdict = _parse(raw)
    verdict["raw"] = raw
    return {"grade": verdict}
