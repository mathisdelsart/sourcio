#!/usr/bin/env bash
#
# smoke.sh — end-to-end smoke test for the Sourcio API.
#
# Drives the critical user flows against a running API (local or deployed) and
# asserts each one responds correctly. It is self-contained: it registers a
# throwaway account, ingests a tiny built-in course (a free .md, no LLM needed),
# then exercises grounded answer, honest refusal, exercise and grade. When a
# premium key is supplied it also checks the bring-your-own-key path and that the
# key never leaks back in a response.
#
# It is a smoke test, not a unit test: it does not assert on exact wording, only
# that each flow is fundamentally working. Run it after every deploy to confirm
# nothing is on fire, in ~30s, without clicking through the web UI.
#
# Usage:
#   BASE_URL=http://localhost:8000                  scripts/smoke.sh
#   BASE_URL=https://mathis003-sourcio-api.hf.space scripts/smoke.sh
#   PREMIUM_KEY=sk-...           BASE_URL=... scripts/smoke.sh   # also test premium
#   API_KEY=<x-api-key>          BASE_URL=... scripts/smoke.sh   # if password-gated
#
# Env:
#   BASE_URL     API base URL (default http://localhost:8000)
#   PREMIUM_KEY  optional premium API key to exercise the bring-your-own-key path
#   API_KEY      optional value sent as X-API-Key when the deployment is gated
#   SMOKE_USER / SMOKE_PASS   override the throwaway credentials
#
# Requires: curl, python3. Exits non-zero on the first failed assertion.

set -uo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
BASE_URL="${BASE_URL%/}"
PREMIUM_KEY="${PREMIUM_KEY:-}"
API_KEY="${API_KEY:-}"
USERNAME="${SMOKE_USER:-smoketest_$$}"
PASSWORD="${SMOKE_PASS:-smoke-pass-123}"
COURSE="Smoke Test Course"

PASS=0
FAIL=0
GREEN=$'\033[32m'; RED=$'\033[31m'; DIM=$'\033[2m'; RST=$'\033[0m'

ok()   { PASS=$((PASS+1)); printf "  ${GREEN}PASS${RST} %s\n" "$1"; }
bad()  { FAIL=$((FAIL+1)); printf "  ${RED}FAIL${RST} %s\n" "$1"; [ -n "${2:-}" ] && printf "       ${DIM}%s${RST}\n" "$2"; }
skip() { printf "  ${DIM}SKIP %s${RST}\n" "$1"; }
step() { printf "\n${DIM}%s${RST}\n" "$1"; }

# jval <json> <python-expression-on-`d`>  -> prints the extracted value ("" on error)
jval() {
  python3 -c 'import sys,json
try:
    d=json.load(sys.stdin)
    print(eval(sys.argv[1]))
except Exception:
    print("")' "$2" <<<"$1" 2>/dev/null
}

# Common headers as an array (auth + optional gate). TOKEN is filled in after login.
TOKEN=""
auth_headers() {
  HDR=(-H "Content-Type: application/json")
  [ -n "$TOKEN" ]   && HDR+=(-H "Authorization: Bearer $TOKEN")
  [ -n "$API_KEY" ] && HDR+=(-H "X-API-Key: $API_KEY")
}

# post_json <path> <json-body> [extra curl args...] -> sets $BODY and $CODE
post_json() {
  local path="$1" body="$2"; shift 2
  auth_headers
  local out
  out=$(curl -sS -m 90 -w $'\n%{http_code}' -X POST "$BASE_URL$path" "${HDR[@]}" "$@" -d "$body" 2>/dev/null)
  CODE="${out##*$'\n'}"; BODY="${out%$'\n'*}"
}

# get_json <path> -> sets $BODY and $CODE
get_json() {
  local path="$1"; shift
  auth_headers
  local out
  out=$(curl -sS -m 30 -w $'\n%{http_code}' "$BASE_URL$path" "${HDR[@]}" "$@" 2>/dev/null)
  CODE="${out##*$'\n'}"; BODY="${out%$'\n'*}"
}

printf "Smoke test against %s\n" "$BASE_URL"

# ---------------------------------------------------------------------------
step "0. Liveness"
get_json /health
[ "$CODE" = "200" ] && ok "/health -> 200" || bad "/health ($CODE)" "$BODY"
get_json /ready
[ "$CODE" = "200" ] && ok "/ready -> 200" || bad "/ready ($CODE)" "$BODY"
get_json /config
REQ_AUTH=$(jval "$BODY" 'd.get("require_auth")')
ok "/config require_auth=$REQ_AUTH"

# ---------------------------------------------------------------------------
step "1. Auth (register + login)"
post_json /auth/register "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}"
if [ "$CODE" = "201" ]; then ok "register -> 201 ($USERNAME)"
elif [ "$CODE" = "409" ]; then ok "register -> 409 (already exists, reusing)"
else bad "register ($CODE)" "$BODY"; fi

post_json /auth/login "{\"username\":\"$USERNAME\",\"password\":\"$PASSWORD\"}"
TOKEN=$(jval "$BODY" 'd["access_token"]')
[ -n "$TOKEN" ] && ok "login -> token" || { bad "login ($CODE)" "$BODY"; echo; echo "Cannot continue without a token."; exit 1; }

get_json /auth/me
ACCT_ID=$(jval "$BODY" 'd["id"]')   # not UID: that name is a readonly shell var
STUDENT="u${ACCT_ID}"
[ -n "$ACCT_ID" ] && ok "me -> id=$ACCT_ID (student_id=$STUDENT)" || bad "me ($CODE)" "$BODY"

# ---------------------------------------------------------------------------
step "2. Ingest a tiny course (free .md path)"
TMPMD="$(mktemp -t smoke_course_XXXX).md"
cat >"$TMPMD" <<'MD'
# Cellular Respiration — Study Notes

## Overview
Cellular respiration is the process by which cells convert glucose and oxygen
into energy stored as ATP, releasing carbon dioxide and water as by-products.

## The three stages
1. Glycolysis splits glucose into two pyruvate molecules in the cytoplasm.
2. The Krebs cycle oxidises pyruvate in the mitochondria, releasing carbon dioxide.
3. The electron transport chain produces most of the ATP, with oxygen as the
   final electron acceptor.

## Key figure
Aerobic respiration yields about 30 to 32 ATP molecules per glucose molecule.
MD

UP=()
[ -n "$TOKEN" ]   && UP+=(-H "Authorization: Bearer $TOKEN")
[ -n "$API_KEY" ] && UP+=(-H "X-API-Key: $API_KEY")
out=$(curl -sS -m 120 -w $'\n%{http_code}' -X POST "$BASE_URL/documents/upload" "${UP[@]}" \
  -F "file=@$TMPMD;type=text/markdown" \
  -F "course=$COURSE" \
  -F "student_id=$STUDENT" 2>/dev/null)
CODE="${out##*$'\n'}"; BODY="${out%$'\n'*}"
JOB=$(jval "$BODY" 'd["job_id"]')
rm -f "$TMPMD"
[ -n "$JOB" ] && ok "upload -> job $JOB (HTTP $CODE)" || bad "upload ($CODE)" "$BODY"

if [ -n "$JOB" ]; then
  status=""; for i in $(seq 1 40); do
    get_json "/documents/jobs/$JOB"
    status=$(jval "$BODY" 'd.get("status","")')
    [ "$status" = "done" ] || [ "$status" = "error" ] && break
    sleep 2
  done
  [ "$status" = "done" ] && ok "ingestion done" || bad "ingestion status=$status" "$BODY"
fi

# ---------------------------------------------------------------------------
step "3. Discovery"
get_json "/courses?student_id=$STUDENT"
echo "$BODY" | grep -q "Smoke Test Course" && ok "/courses lists the course" || bad "/courses missing the course" "$BODY"

# ---------------------------------------------------------------------------
step "4. Grounded answer (in-course)"
post_json /ask "{\"student_id\":\"$STUDENT\",\"question\":\"What are the three stages of cellular respiration?\",\"course\":\"$COURSE\"}"
REFUSED=$(jval "$BODY" 'd.get("refused")')
NCITE=$(jval "$BODY" 'len(d.get("citations",[]))')
if [ "$REFUSED" = "False" ] && [ "${NCITE:-0}" -gt 0 ] 2>/dev/null; then
  ok "grounded answer with $NCITE citation(s)"
else
  bad "expected grounded+cited (refused=$REFUSED, citations=$NCITE)" "$BODY"
fi

# ---------------------------------------------------------------------------
step "5. Honest refusal (out-of-course)"
post_json /ask "{\"student_id\":\"$STUDENT\",\"question\":\"What is the capital of Australia?\",\"course\":\"$COURSE\"}"
REFUSED=$(jval "$BODY" 'd.get("refused")')
[ "$REFUSED" = "True" ] && ok "out-of-course refused" || bad "expected refusal (refused=$REFUSED)" "$BODY"

# ---------------------------------------------------------------------------
step "6. Premium bring-your-own-key"
if [ -z "$PREMIUM_KEY" ]; then
  skip "no PREMIUM_KEY set (export PREMIUM_KEY=sk-... to test the premium path)"
else
  auth_headers; HDR+=(-H "X-OpenAI-Key: $PREMIUM_KEY")
  out=$(curl -sS -m 90 -w $'\n%{http_code}' -X POST "$BASE_URL/ask" "${HDR[@]}" \
    -d "{\"student_id\":\"$STUDENT\",\"question\":\"What are the three stages of cellular respiration?\",\"course\":\"$COURSE\"}" 2>/dev/null)
  CODE="${out##*$'\n'}"; BODY="${out%$'\n'*}"
  [ "$CODE" -lt 500 ] 2>/dev/null && ok "premium /ask -> HTTP $CODE (server handled the key)" || bad "premium /ask ($CODE)" "$BODY"
  echo "$BODY" | grep -qF "$PREMIUM_KEY" && bad "the premium key LEAKED into the response body" || ok "premium key not leaked in the response"
fi

# ---------------------------------------------------------------------------
step "7. Exercise + grade"
post_json /exercise "{\"student_id\":\"$STUDENT\",\"notion\":\"a short question on the stages of cellular respiration\",\"course\":\"$COURSE\"}"
PROBLEM=$(jval "$BODY" 'd.get("problem","")')
[ -n "$PROBLEM" ] && ok "exercise generated" || bad "exercise empty" "$BODY"

post_json /grade "{\"student_id\":\"$STUDENT\",\"message\":\"Glycolysis, the Krebs cycle and the electron transport chain.\"}"
SCORE=$(jval "$BODY" 'd.get("score")')
[ -n "$SCORE" ] && ok "grade -> score=$SCORE" || bad "grade returned no score" "$BODY"

# ---------------------------------------------------------------------------
printf "\n${DIM}----------------------------------------${RST}\n"
printf "Result: ${GREEN}%d passed${RST}, ${RED}%d failed${RST}\n" "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] && printf "${GREEN}SMOKE OK${RST}\n" || printf "${RED}SMOKE FAILED${RST}\n"
exit "$([ "$FAIL" -eq 0 ] && echo 0 || echo 1)"
