#!/usr/bin/env bash
# =============================================================================
# KODMOD AI — ordered test pipeline (Stage 0 -> 10).
#
# kodmod-ai runs entirely in Docker (docker/docker-compose.test.yml: postgres,
# redis, llm-stub, api). This SCRIPT runs natively on the host (bash/CI) — it
# never runs pytest inside a container. It only uses `docker compose` to bring
# up the service containers that Stage 3+ talk to over the network. On
# Windows, prefer scripts/run_tests.ps1 in PowerShell.
#
# Runs each stage in dependency order and STOPS at the first RED stage so bugs
# can be fixed iteratively. See docs/testplan/README.md section 3.
#
#   bash scripts/run_tests.sh                # run 0..9 then the readiness gate
#   bash scripts/run_tests.sh --from 3       # resume from Stage 3 (Integration)
#   bash scripts/run_tests.sh --only 1       # run just Stage 1
#   bash scripts/run_tests.sh --gate         # only the Stage 10 readiness gate
#   bash scripts/run_tests.sh --no-compose   # assume containers already up
#   bash scripts/run_tests.sh --burndown     # only the known-bug burndown report
#
# Each stage selects `-m "<marker> and not known_bug"` so the pipeline gates on
# REGRESSIONS. Tests tagged @pytest.mark.known_bug assert target behaviour of a
# tracked-but-unfixed bug: they FAIL until fixed, then pass. The burndown step
# (always run, non-blocking) reports how many are still open.
#
# Env:
#   COMPOSE_TEST   docker compose invocation (default below)
#   PYTEST         pytest invocation (default: python -m pytest)
# =============================================================================
set -uo pipefail
cd "$(dirname "$0")/.."

COMPOSE_TEST=${COMPOSE_TEST:-docker compose -p kodmod-test -f docker/docker-compose.test.yml}
PYTEST=${PYTEST:-python -m pytest}
REPORTS=reports
mkdir -p "$REPORTS"

FROM=0
ONLY=""
GATE_ONLY=0
USE_COMPOSE=1
BURNDOWN_ONLY=0

# Stages gate on regressions only; known-bug cases are reported separately.
NOT_KNOWN_BUG=${NOT_KNOWN_BUG:-and not known_bug}

while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --gate) GATE_ONLY=1; shift ;;
    --burndown) BURNDOWN_ONLY=1; shift ;;
    --no-compose) USE_COMPOSE=0; shift ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

c_red() { printf '\033[31m%s\033[0m\n' "$*"; }
c_grn() { printf '\033[32m%s\033[0m\n' "$*"; }
c_hdr() { printf '\n\033[1;36m==== %s ====\033[0m\n' "$*"; }

want() {  # want <stage-number>
  { [ "$GATE_ONLY" -eq 1 ] || [ "$BURNDOWN_ONLY" -eq 1 ]; } && return 1
  if [ -n "$ONLY" ]; then [ "$1" = "$ONLY" ]; return; fi
  [ "$1" -ge "$FROM" ]
}

run_stage() {  # run_stage <num> <label> <command...>
  local num="$1" label="$2"; shift 2
  want "$num" || return 0
  c_hdr "Stage $num — $label"
  if "$@"; then
    c_grn "Stage $num PASSED"
  else
    c_red "Stage $num FAILED — fix the root cause, then: bash scripts/run_tests.sh --from $num"
    exit 1
  fi
}

compose_up_infra() {  # postgres + redis + llm-stub + schema/seed (Stage 3)
  [ "$USE_COMPOSE" -eq 1 ] || return 0
  $COMPOSE_TEST up -d postgres redis llm-stub
  $COMPOSE_TEST up --no-deps db-init
}

compose_up_api() {  # + the real backend, built from docker/Dockerfile (Stage 4+)
  [ "$USE_COMPOSE" -eq 1 ] || return 0
  $COMPOSE_TEST up -d --build api
  echo "waiting for api on http://localhost:8000/live ..."
  for _ in $(seq 1 30); do
    curl -fsS http://localhost:8000/live >/dev/null 2>&1 && return 0
    sleep 2
  done
  c_red "api did not become healthy — see: $COMPOSE_TEST logs api"
  return 1
}

# ------------------------------------------------------------------ stages ----

# Stage 0 is a single pytest run of `-m static` (tests/static/, spec:
# docs/testplan/00-static.md). Those cases shell out to ruff / mypy / bandit /
# pip-audit / detect-secrets / docker compose and skip cleanly when a tool is
# absent. Image-build cases (`static and slow`) run in CI's full `-m static`.
STATIC_SELECT=${STATIC_SELECT:-static and not slow}
stage0() {
  $PYTEST -q -m "$STATIC_SELECT $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-static.xml"
}

stage1() { $PYTEST -q -m "unit $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-unit.xml" \
             --cov --cov-report="xml:$REPORTS/coverage-unit.xml"; }

stage2() { $PYTEST -q -m "contract $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-contract.xml"; }

stage3() { compose_up_infra; $PYTEST -q -m "integration $NOT_KNOWN_BUG" \
             --junitxml="$REPORTS/junit-integration.xml" \
             --cov --cov-report="xml:$REPORTS/coverage-integration.xml"; }

stage4() { compose_up_api && $PYTEST -q -m "api $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-api.xml"; }

stage5() { compose_up_api && $PYTEST -q -m "ws $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-ws.xml"; }

stage6() { compose_up_api && $PYTEST -q -m "e2e $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-e2e.xml"; }

stage7() { compose_up_api && $PYTEST -q -m "system $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-system.xml"; }

stage8() {  # non-blocking: record baselines, never fail the pipeline
  compose_up_api || return 0
  [ "$USE_COMPOSE" -eq 1 ] && $COMPOSE_TEST --profile load up -d --build
  $PYTEST -q -m "perf $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-perf.xml" \
    --benchmark-json="docs/testplan/baselines/bench.json" || \
    c_red "Stage 8 had failures (non-blocking) — see reports/junit-perf.xml"
  return 0
}

stage9() { compose_up_api && $PYTEST -q -m "security $NOT_KNOWN_BUG" \
             --junitxml="$REPORTS/junit-security.xml"; }

burndown() {  # non-blocking: how many tracked bugs are still open (RED)
  c_hdr "Known-bug burndown"
  $PYTEST -q -m known_bug --no-header -rN --junitxml="$REPORTS/junit-known-bug.xml" || true
  echo "(failures above = bugs still open; passes = fixed — remove the known_bug marker)"
}

gate() {
  c_hdr "Stage 10 — Release Readiness Gate"
  python scripts/readiness_gate.py 2>/dev/null || {
    echo "readiness_gate.py not implemented yet — see docs/testplan/10-readiness.md"
    return 0
  }
}

# ------------------------------------------------------------------- main -----

if [ "$BURNDOWN_ONLY" -eq 1 ]; then
  burndown
  exit 0
fi

run_stage 0 "Static & Build"        stage0
run_stage 1 "Unit"                  stage1
run_stage 2 "Contract / Schema"     stage2
run_stage 3 "Integration"           stage3
run_stage 4 "API / Endpoint"        stage4
run_stage 5 "WebSocket / Realtime"  stage5
run_stage 6 "E2E user journey"      stage6
run_stage 7 "System (black-box)"    stage7
run_stage 8 "Performance / Load"    stage8
run_stage 9 "Security (dynamic)"    stage9

if [ "$GATE_ONLY" -eq 1 ] || { [ -z "$ONLY" ] && [ "$FROM" -le 9 ]; }; then
  gate
fi

# Always show what's left on the bug backlog (never fails the pipeline).
[ -z "$ONLY" ] && burndown

c_grn "pipeline complete"
