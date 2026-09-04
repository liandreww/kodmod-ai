#!/usr/bin/env bash
# =============================================================================
# KODMOD AI — ordered test pipeline (Stage 0 -> 10).
#
# Only the test INFRA runs in Docker (docker/docker-compose.test.yml: postgres,
# redis, llm-stub, [qdrant]). The `db-init` step and the `api` server run
# natively on the host — schema+seed via scripts/create_test_db +
# scripts/seed_curriculum, the API via scripts/serve_test_api — so a code
# change is picked up by a plain restart, no `docker build`. This SCRIPT runs
# natively too and never runs pytest inside a container. On Windows, prefer
# scripts/run_tests.ps1 in PowerShell.
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
PYBIN=${PYBIN:-python}
REPORTS=reports
mkdir -p "$REPORTS"
API_PID=""

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

stop_host_api() {  # kill the host uvicorn started by compose_up_api, if any
  local pid="$API_PID"
  [ -z "$pid" ] && [ -f "$REPORTS/.api.pid" ] && pid=$(cat "$REPORTS/.api.pid" 2>/dev/null)
  [ -n "$pid" ] && kill "$pid" 2>/dev/null || true
  API_PID=""
  rm -f "$REPORTS/.api.pid"
}
trap stop_host_api EXIT

compose_up_infra() {  # postgres + redis + llm-stub (Docker) + schema/seed (host) — Stage 3
  if [ "$USE_COMPOSE" -eq 1 ]; then
    $COMPOSE_TEST up -d postgres redis llm-stub
  fi
  $PYBIN -m scripts.init_test_db
}

compose_up_api() {  # + the backend, run natively on the host (Stage 4+)
  # $1 (optional) = KODMOD_CHECKPOINTER for the server ("memory" for Stage 8,
  # where the Postgres saver's global lock would serialise every graph turn).
  # When set we always start a fresh server; otherwise we reuse a healthy one.
  compose_up_infra || return 1
  local want_cp="${1:-}"
  if [ -z "$want_cp" ] && curl -fsS http://localhost:8000/live >/dev/null 2>&1; then
    return 0  # reuse a healthy server (e.g. --no-compose, or a dev-run server)
  fi
  stop_host_api
  # Never inherit reload for perf/e2e — watchfiles churn thrashes concurrency.
  unset SERVE_TEST_API_RELOAD
  KODMOD_CHECKPOINTER="${want_cp:-postgres}" \
    $PYBIN -m scripts.serve_test_api >"$REPORTS/api.log" 2>&1 &
  API_PID=$!
  echo "$API_PID" > "$REPORTS/.api.pid"
  echo "waiting for api on http://localhost:8000/live ..."
  for _ in $(seq 1 30); do
    curl -fsS http://localhost:8000/live >/dev/null 2>&1 && return 0
    kill -0 "$API_PID" 2>/dev/null || { c_red "serve_test_api exited early — see $REPORTS/api.log"; return 1; }
    sleep 2
  done
  c_red "api did not become healthy — see $REPORTS/api.log"
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
  compose_up_api memory || return 0
  [ "$USE_COMPOSE" -eq 1 ] && $COMPOSE_TEST --profile load up -d locust
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
  # Repo-inspection meta-checks (traceability, docs, migration policy, marker
  # hygiene) — no service needed. Non-blocking here; the gate script folds the
  # result in via reports/junit-readiness.xml.
  $PYTEST -q -m "readiness $NOT_KNOWN_BUG" --junitxml="$REPORTS/junit-readiness.xml" || \
    c_red "Stage 10 readiness meta-checks had failures — see reports/junit-readiness.xml"
  python scripts/readiness_gate.py || return 1
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

if [ "$GATE_ONLY" -eq 1 ]; then
  gate || exit 1
elif [ -z "$ONLY" ] && [ "$FROM" -le 9 ]; then
  gate || true   # full-pipeline run: report the gate, don't mask an earlier green
fi

# Always show what's left on the bug backlog (never fails the pipeline).
[ -z "$ONLY" ] && burndown

c_grn "pipeline complete"
