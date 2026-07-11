"""API-driven benchmark runner for Sourcio, with an independent LLM reviewer.

Replaces slow, one-at-a-time manual UI testing with a single command that drives
the real backend (local or deployed) the same way the web app does — hitting
``/ask``, ``/exercise`` and ``/quiz`` with the same parameters (course filter,
chapter filter, max sources, prompt) — over a predefined list of cases
(``eval/benchmark_cases.json``), and writes every result to a timestamped file.

An optional second, *external* model acts as an automated first-pass QA reviewer:
it reads Sourcio's actual output (answer + cited sources, or the generated
exercise/quiz, plus any grading) and flags likely issues — unsupported claims,
citation mismatches, chapter-scope violations, self-contradictory feedback,
missing scores. It never replaces Sourcio's own generation; it only reviews it.

This is a personal debugging tool: it authenticates as *your* account (so it sees
your indexed courses) and calls the reviewer with *your* key. Nothing is exposed
publicly and no credential is written to the output.

Usage
-----
    # Credentials + target (env)
    export SOURCIO_BASE_URL=https://mathis003-sourcio-api.hf.space   # or http://localhost:8000
    export SOURCIO_USER=...            # account that owns the Finance / Relativity uploads
    export SOURCIO_PASSWORD=...
    export SOURCIO_API_KEY=...         # optional: X-API-Key gate, if the deployment is gated
    export SOURCIO_JUDGE_KEY=sk-...    # optional: OpenAI key for the independent reviewer

    # Run everything, review each result, write eval/benchmark/run-<UTC>/{results.json,report.md}
    uv run python -m eval.bench_runner

    # A subset (id / mode / course substring), no reviewer, more quiz questions
    uv run python -m eval.bench_runner --filter Relativity
    uv run python -m eval.bench_runner --mode exercise --no-judge
    uv run python -m eval.bench_runner --filter R-all --judge-model gpt-4o

    # Steady the reviewer: run it 3x per case and take the majority verdict
    uv run python -m eval.bench_runner --judge-votes 3

    # Just list the cases (no calls)
    uv run python -m eval.bench_runner --list

Run it again after each deployed fix and diff two run folders to confirm a case
flipped. It complements — does not replace — the occasional manual UI spot-check
(the UI is itself under test; an API-only run won't catch rendering bugs).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
CASES_PATH = Path(__file__).with_name("benchmark_cases.json")
OUT_ROOT = Path(__file__).with_name("benchmark")
# Default external reviewer. OpenAI so it is independent of whatever model Sourcio
# runs internally; override with --judge-model.
DEFAULT_JUDGE_MODEL = "gpt-4o"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# The exact refusal sentence the product emits, so the runner can recognise a
# refusal without depending on the reviewer.
REFUSAL_MARKERS = ("not covered by the course", "not covered in the course")


@dataclass
class Case:
    """One benchmark case, mirroring what the UI would send for a single action."""

    id: str
    mode: str  # ask | exercise | quiz
    prompt: str
    course: str | None = None
    chapter: str | None = None
    k: int = 5
    n: int = 3
    expect: str = "behavior"  # answer | refuse | generate | behavior
    note: str = ""
    student_answer: str | None = None  # exercise only: submit to /grade if present


@dataclass
class Result:
    """A case's full outcome: what was sent, what came back, and the review."""

    case: Case
    ok_call: bool
    http_status: int | None
    output: dict[str, Any] = field(default_factory=dict)
    review: dict[str, Any] = field(default_factory=dict)
    error: str = ""


# --------------------------------------------------------------------------- #
# Sourcio API client
# --------------------------------------------------------------------------- #
class SourcioClient:
    """Thin client over the Sourcio API, authenticating like the web app."""

    def __init__(self, base_url: str, api_key: str | None, openai_key: str | None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.openai_key = openai_key
        self.token: str | None = None
        self.student_id: str | None = None
        self._client = httpx.Client(timeout=120.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        if self.openai_key:
            headers["X-OpenAI-Key"] = self.openai_key
        return headers

    def login_or_register(self, username: str, password: str) -> None:
        """Register the account if new, then log in and resolve the student id."""
        body = {"username": username, "password": password}
        # Register is idempotent for our purposes: 409 just means it already exists.
        self._client.post(f"{self.base_url}/auth/register", json=body, headers=self._headers())
        resp = self._client.post(f"{self.base_url}/auth/login", json=body, headers=self._headers())
        resp.raise_for_status()
        self.token = resp.json()["access_token"]
        me = self._client.get(f"{self.base_url}/auth/me", headers=self._headers())
        me.raise_for_status()
        self.student_id = f"u{me.json()['id']}"

    def _post(self, path: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        resp = self._client.post(f"{self.base_url}{path}", json=payload, headers=self._headers())
        try:
            data = resp.json()
        except ValueError:
            data = {"raw": resp.text}
        return resp.status_code, data

    def ask(self, case: Case) -> tuple[int, dict[str, Any]]:
        payload = {
            "student_id": self.student_id,
            "question": case.prompt,
            "k": case.k,
            "course": case.course,
            "chapter": case.chapter,
        }
        return self._post("/ask", payload)

    def exercise(self, case: Case) -> tuple[int, dict[str, Any]]:
        payload = {
            "student_id": self.student_id,
            "notion": case.prompt,
            "course": case.course,
            "chapter": case.chapter,
        }
        return self._post("/exercise", payload)

    def quiz(self, case: Case) -> tuple[int, dict[str, Any]]:
        payload = {
            "student_id": self.student_id,
            "notion": case.prompt,
            "n": case.n,
            "course": case.course,
            "chapter": case.chapter,
        }
        return self._post("/quiz", payload)

    def grade(
        self, message: str, exercise: dict[str, Any] | None = None
    ) -> tuple[int, dict[str, Any]]:
        payload: dict[str, Any] = {"student_id": self.student_id, "message": message}
        if exercise is not None:
            payload["exercise"] = exercise
        return self._post("/grade", payload)

    def close(self) -> None:
        self._client.close()


def looks_refused(output: dict[str, Any]) -> bool:
    """Best-effort refusal detection across the Ask/Exercise/Quiz shapes."""
    if output.get("refused") is True:
        return True
    text = " ".join(str(output.get(k, "")) for k in ("answer", "problem")).lower()
    if any(m in text for m in REFUSAL_MARKERS):
        return True
    # Quiz: a refusal returns no questions.
    if "questions" in output and not output.get("questions") and output.get("refused"):
        return True
    return False


def run_case(client: SourcioClient, case: Case) -> Result:
    """Call the right endpoint for the case and capture the full response."""
    try:
        if case.mode == "ask":
            status, output = client.ask(case)
        elif case.mode == "exercise":
            status, output = client.exercise(case)
            # Optionally exercise the grading path with a supplied student answer,
            # so grading defects (missing score, contradictory feedback) surface.
            if case.student_answer and not looks_refused(output):
                g_status, grade = client.grade(
                    case.student_answer, exercise={"solution": output.get("solution", "")}
                )
                output["grade"] = {"http_status": g_status, **grade}
        elif case.mode == "quiz":
            status, output = client.quiz(case)
        else:
            return Result(case, False, None, error=f"unknown mode {case.mode!r}")
        return Result(case, 200 <= status < 300, status, output=output)
    except httpx.HTTPError as exc:
        return Result(case, False, None, error=f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------- #
# Independent reviewer (external model)
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = (
    "You are an automated QA reviewer for a course-grounded tutoring system. The "
    "system must answer ONLY from the user's indexed course material, always cite "
    "its sources, respect the selected course/chapter filter, and refuse honestly "
    "when the material does not cover the request.\n"
    "You are given: the test's intent, the exact filters used, the expected "
    "behaviour, and the system's ACTUAL output. Judge whether the output matches "
    "the expectation and flag concrete problems: unsupported claims not backed by "
    "the cited sources, citation/scope mismatches, self-contradictory or circular "
    "grading feedback, a missing score, or a refusal where content was expected "
    "(and vice versa).\n"
    "SCOPE RULE — read the filters before judging a scope mismatch. A scope "
    "mismatch exists ONLY when a SPECIFIC chapter/course was selected but the "
    "answer draws on content outside it. When the chapter filter is null ('All "
    "chapters') or the course filter is null ('All courses'), citing MULTIPLE "
    "chapters or courses is EXPECTED and CORRECT — never flag that as a mismatch.\n"
    "CITATION RULE — an inline marker like [1] is a SOURCE INDEX, not a page "
    "number. The page/chapter shown in the source label the system attaches is "
    "accurate by construction (the model never types page numbers). Do NOT flag a "
    "page as invented from a [n] marker; only flag a page the answer's PROSE states "
    "that plainly contradicts its cited source label.\n"
    "EVIDENCE RULE — reason ONLY about content that literally appears in the given "
    "system_output. Never invent, assume, or hallucinate question numbers, symbols, "
    "formulas, page labels, or wording that is not actually present in "
    "system_output. Every detail your reason mentions must be copyable verbatim from "
    "system_output; if you cannot find it there, do not mention it. When you are "
    "uncertain whether something is a real defect — the output is ambiguous, or you "
    "cannot verify a claim against the material, or the detail you would cite is not "
    'clearly in the output — default to "pass" (or at most "suspicious"). Never '
    'issue a "fail" that rests on a detail you are not certain is actually in '
    "system_output.\n"
    'Reply with a JSON object ONLY: {"verdict": "pass"|"suspicious"|"fail", '
    '"reason": "<one or two sentences>"}. Use "pass" when the output meets the '
    'expectation, "fail" only for a clear violation you can point to verbatim in '
    'system_output, "suspicious" when something looks off but is not conclusive. '
    'For a discovery case (expected behaviour "behavior") always use "pass" and '
    "describe what the system actually did."
)


# Severity order for the self-consistency tie-break: less severe wins a tie so an
# uncertain reviewer never manufactures a "fail" by a bare plurality.
VERDICT_SEVERITY = {"pass": 0, "suspicious": 1, "fail": 2, "error": 3}


def _majority_verdict(votes: list[dict[str, Any]]) -> dict[str, Any]:
    """Combine N single reviews into one, preferring the least-severe on a tie.

    Takes the majority verdict; ties are broken toward the least severe
    (pass > suspicious > fail). The returned dict keeps the standard
    {verdict, reason} contract and adds the individual votes for the report.
    """
    verdicts = [v.get("verdict", "suspicious") for v in votes]
    counts = {v: verdicts.count(v) for v in set(verdicts)}
    top = max(counts.values())
    winners = [v for v, n in counts.items() if n == top]
    winner = min(winners, key=lambda v: VERDICT_SEVERITY.get(v, 1))
    reason = next((v.get("reason", "") for v in votes if v.get("verdict") == winner), "")
    return {"verdict": winner, "reason": reason, "votes": verdicts}


def review(
    case: Case, output: dict[str, Any], judge_key: str, model: str, votes: int = 1
) -> dict[str, Any]:
    """Review the case, optionally taking the majority over ``votes`` reviews.

    With ``votes == 1`` this is a single reviewer call (unchanged behaviour).
    With ``votes > 1`` the reviewer runs that many times and the majority verdict
    is returned (ties broken toward the least-severe verdict), with the individual
    votes recorded under ``votes``.
    """
    if votes <= 1:
        return _review_once(case, output, judge_key, model)
    ballots = [_review_once(case, output, judge_key, model) for _ in range(votes)]
    return _majority_verdict(ballots)


def _review_once(case: Case, output: dict[str, Any], judge_key: str, model: str) -> dict[str, Any]:
    """Ask the external reviewer to flag the case once, returning {verdict, reason}."""
    expectation = {
        "answer": "A grounded, correctly cited, in-scope answer (not a refusal).",
        "refuse": "An honest refusal — the material does not cover this request.",
        "generate": "A generated exercise/quiz (not a refusal), grounded and in scope.",
        "behavior": "Discovery only — no pass/fail; describe what happened.",
    }.get(case.expect, case.expect)

    human = json.dumps(
        {
            "test_id": case.id,
            "mode": case.mode,
            "filters": {"course": case.course, "chapter": case.chapter, "max_sources": case.k},
            "prompt": case.prompt,
            "intent_note": case.note,
            "expected": expectation,
            "system_output": output,
        },
        ensure_ascii=False,
        indent=2,
    )
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": human},
        ],
    }
    try:
        resp = httpx.post(
            OPENAI_CHAT_URL,
            headers={"Authorization": f"Bearer {judge_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=90.0,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        verdict = json.loads(content)
        return {
            "verdict": verdict.get("verdict", "suspicious"),
            "reason": verdict.get("reason", ""),
        }
    except Exception as exc:  # noqa: BLE001 — the reviewer is best-effort
        return {"verdict": "error", "reason": f"reviewer failed: {type(exc).__name__}: {exc}"}


# --------------------------------------------------------------------------- #
# Loading / filtering / reporting
# --------------------------------------------------------------------------- #
def load_cases(path: Path) -> list[Case]:
    data = json.loads(path.read_text())
    return [Case(**{k: v for k, v in c.items()}) for c in data["cases"]]


def select(cases: list[Case], text: str | None, mode: str | None) -> list[Case]:
    out = cases
    if mode:
        out = [c for c in out if c.mode == mode]
    if text:
        needle = text.lower()
        out = [
            c
            for c in out
            if needle in c.id.lower()
            or needle in c.mode.lower()
            or needle in (c.course or "").lower()
            or needle in (c.chapter or "").lower()
        ]
    return out


def git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def scope_label(case: Case) -> str:
    course = case.course or "All courses"
    chapter = case.chapter or "All chapters"
    return f"{course} / {chapter}"


def write_reports(results: list[Result], out_dir: Path, meta: dict[str, Any]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    # Machine-readable.
    payload = {
        "meta": meta,
        "results": [
            {
                "id": r.case.id,
                "mode": r.case.mode,
                "course": r.case.course,
                "chapter": r.case.chapter,
                "max_sources": r.case.k,
                "prompt": r.case.prompt,
                "expected": r.case.expect,
                "note": r.case.note,
                "http_status": r.http_status,
                "call_ok": r.ok_call,
                "refused": looks_refused(r.output),
                "output": r.output,
                "review": r.review,
                "error": r.error,
            }
            for r in results
        ],
    }
    (out_dir / "results.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # Human-readable.
    lines: list[str] = []
    lines.append(f"# Sourcio benchmark — {meta['timestamp']}")
    lines.append("")
    lines.append(f"- Base URL: `{meta['base_url']}`")
    lines.append(f"- Commit: `{meta['commit']}`")
    lines.append(f"- Reviewer: {meta['judge']}")
    lines.append(f"- Cases: {len(results)}")
    lines.append("")

    verdicts = [r.review.get("verdict", "-") for r in results]
    tally = {v: verdicts.count(v) for v in sorted(set(verdicts))}
    lines.append("| verdict | count |")
    lines.append("|---|---|")
    for v, n in tally.items():
        lines.append(f"| {v} | {n} |")
    lines.append("")

    lines.append("| id | mode | scope | expected | refused | verdict | reason |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in results:
        refused = "yes" if looks_refused(r.output) else "no"
        verdict = r.review.get("verdict", "-")
        reason = (r.review.get("reason", "") or r.error).replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {r.case.id} | {r.case.mode} | {scope_label(r.case)} | "
            f"{r.case.expect} | {refused} | {verdict} | {reason} |"
        )
    lines.append("")

    # Per-case detail, so the raw output is reviewable without opening the JSON.
    lines.append("## Detail")
    for r in results:
        lines.append("")
        lines.append(f"### {r.case.id} — {r.case.mode} — {scope_label(r.case)}")
        lines.append(f"- Prompt: {r.case.prompt}")
        lines.append(f"- Expected: {r.case.expect} — {r.case.note}")
        lines.append(f"- HTTP: {r.http_status} (call_ok={r.ok_call})")
        if r.error:
            lines.append(f"- Error: {r.error}")
        verdict = r.review.get("verdict", "-")
        lines.append(f"- Review: **{verdict}** — {r.review.get('reason', '')}")
        votes = r.review.get("votes")
        if votes:
            lines.append(f"- Votes: {', '.join(votes)}")
        answer = r.output.get("answer") or r.output.get("problem")
        if answer:
            snippet = answer if len(answer) < 1200 else answer[:1200] + " …"
            lines.append("")
            lines.append("```")
            lines.append(snippet)
            lines.append("```")
        cites = r.output.get("citations") or r.output.get("sources")
        if cites:
            lines.append(f"- Sources: {json.dumps(cites, ensure_ascii=False)}")
        if "questions" in r.output:
            for q in r.output.get("questions", []):
                lines.append(f"  - Q: {q.get('problem', '')}")
        if "grade" in r.output:
            g = r.output["grade"]
            lines.append(f"- Grade: score={g.get('score')} — {g.get('feedback', '')}")

    (out_dir / "report.md").write_text("\n".join(lines))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="API-driven Sourcio benchmark runner.")
    parser.add_argument("--base-url", default=os.getenv("SOURCIO_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--filter", dest="text", help="substring on id / mode / course / chapter")
    parser.add_argument("--mode", choices=["ask", "exercise", "quiz"], help="only this mode")
    parser.add_argument("--cases", type=Path, default=CASES_PATH)
    parser.add_argument("--out-dir", type=Path, default=None, help="override the run output dir")
    parser.add_argument(
        "--judge-model", default=os.getenv("SOURCIO_JUDGE_MODEL", DEFAULT_JUDGE_MODEL)
    )
    parser.add_argument(
        "--judge-votes",
        type=int,
        default=1,
        metavar="N",
        help="run the reviewer N times per case and take the majority verdict (default 1)",
    )
    parser.add_argument("--no-judge", action="store_true", help="skip the external reviewer")
    parser.add_argument("--list", action="store_true", help="list selected cases and exit")
    args = parser.parse_args(argv)

    if args.judge_votes < 1:
        print("--judge-votes must be >= 1.", file=sys.stderr)
        return 2

    all_cases = load_cases(args.cases)
    cases = select(all_cases, args.text, args.mode)
    if not cases:
        print("No cases match the filter.", file=sys.stderr)
        return 2

    if args.list:
        for c in cases:
            print(f"{c.id:14} {c.mode:9} {scope_label(c):32} expect={c.expect}")
        return 0

    username = os.getenv("SOURCIO_USER")
    password = os.getenv("SOURCIO_PASSWORD")
    if not username or not password:
        print(
            "Set SOURCIO_USER and SOURCIO_PASSWORD (the account owning the courses).",
            file=sys.stderr,
        )
        return 2

    judge_key = None if args.no_judge else os.getenv("SOURCIO_JUDGE_KEY")
    if not args.no_judge and not judge_key:
        print("No SOURCIO_JUDGE_KEY set — running without the external reviewer.", file=sys.stderr)

    client = SourcioClient(
        args.base_url,
        api_key=os.getenv("SOURCIO_API_KEY"),
        openai_key=os.getenv("SOURCIO_OPENAI_KEY"),  # optional premium key for generation
    )
    client.login_or_register(username, password)
    print(f"Authenticated as {username} (student_id={client.student_id}) against {args.base_url}")

    results: list[Result] = []
    for i, case in enumerate(cases, 1):
        print(f"[{i}/{len(cases)}] {case.id} ({case.mode}, {scope_label(case)}) …", flush=True)
        result = run_case(client, case)
        if judge_key and result.ok_call:
            result.review = review(
                case, result.output, judge_key, args.judge_model, votes=args.judge_votes
            )
        elif not result.ok_call:
            result.review = {"verdict": "error", "reason": result.error or "call failed"}
        verdict = result.review.get("verdict", "-")
        print(
            f"      -> HTTP {result.http_status}, "
            f"refused={looks_refused(result.output)}, review={verdict}"
        )
        results.append(result)
    client.close()

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = args.out_dir or (OUT_ROOT / f"run-{stamp}")
    meta = {
        "timestamp": stamp,
        "base_url": args.base_url,
        "commit": git_commit(),
        "judge": ("disabled" if not judge_key else args.judge_model),
        "judge_votes": args.judge_votes,
        "case_count": len(results),
    }
    write_reports(results, out_dir, meta)
    print(f"\nWrote {out_dir}/results.json and report.md")

    fails = sum(1 for r in results if r.review.get("verdict") == "fail")
    print(f"Reviewer flagged {fails} fail(s).")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
