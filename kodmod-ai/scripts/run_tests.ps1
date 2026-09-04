<#
.SYNOPSIS
    KODMOD AI  -  ordered test pipeline (Stage 0 -> 10), native PowerShell.

.DESCRIPTION
    Only the test INFRA runs in Docker (docker/docker-compose.test.yml: postgres,
    redis, llm-stub, [qdrant]). The `db-init` step and the `api` server run
    natively on the host - schema+seed via scripts/create_test_db +
    scripts/seed_curriculum, the API via scripts/serve_test_api - so a code
    change is picked up by a plain restart, no `docker build`. This SCRIPT runs
    natively too and never runs pytest inside a container.

    Runs each stage in order and STOPS at the first RED stage so bugs can be
    fixed iteratively. See docs/testplan/README.md section 3.

.PARAMETER From
    Resume from this stage number (default 0).

.PARAMETER Only
    Run only this single stage number.

.PARAMETER Gate
    Run only the Stage 10 readiness gate.

.PARAMETER NoCompose
    Assume containers are already up; skip all `docker compose` calls.

.PARAMETER Burndown
    Run only the known-bug burndown report (how many tracked bugs are still open).

.NOTES
    Each stage selects `-m "<marker> and not known_bug"` so the pipeline gates on
    REGRESSIONS. Tests tagged @pytest.mark.known_bug assert target behaviour of a
    tracked-but-unfixed bug: they FAIL until fixed, then pass. The burndown step
    (always run at the end, non-blocking) reports how many are still open.

.EXAMPLE
    pwsh scripts/run_tests.ps1
.EXAMPLE
    pwsh scripts/run_tests.ps1 -From 3
.EXAMPLE
    pwsh scripts/run_tests.ps1 -Only 4
.EXAMPLE
    pwsh scripts/run_tests.ps1 -Burndown
#>
[CmdletBinding()]
param(
    [int]$From = 0,
    [Nullable[int]]$Only = $null,
    [switch]$Gate,
    [switch]$NoCompose,
    [switch]$Burndown
)

$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$ComposeTest = "docker compose -p kodmod-test -f docker/docker-compose.test.yml"
$Reports = "reports"
New-Item -ItemType Directory -Force -Path $Reports | Out-Null

$script:ApiProc = $null

# Stages gate on regressions only; known-bug cases are reported separately.
$NotKnownBug = "and not known_bug"

function Write-Header([string]$Text) {
    Write-Host ""
    Write-Host "==== $Text ====" -ForegroundColor Cyan
}
function Write-Ok([string]$Text) { Write-Host $Text -ForegroundColor Green }
function Write-Bad([string]$Text) { Write-Host $Text -ForegroundColor Red }

function Invoke-Compose([string]$Args) {
    if ($NoCompose) { return }
    $cmd = "$ComposeTest $Args"
    Write-Host "  > $cmd"
    Invoke-Expression $cmd
    if ($LASTEXITCODE -ne 0) { throw "docker compose failed: $Args" }
}

function Wait-ApiHealthy {
    Write-Host "waiting for api on http://localhost:8000/live ..."
    for ($i = 0; $i -lt 30; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/live" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
        Start-Sleep -Seconds 2
    }
    Write-Bad "api did not become healthy  -  see: $Reports/api.log , $Reports/api.err.log"
    return $false
}

function Stop-TestApi {  # kill the host uvicorn started by Invoke-ComposeApi, if any
    $pidValue = $null
    if ($script:ApiProc -and -not $script:ApiProc.HasExited) { $pidValue = $script:ApiProc.Id }
    elseif (Test-Path "$Reports/.api.pid") {
        $pidValue = [int]((Get-Content "$Reports/.api.pid" -Raw).Trim())
    }
    if ($pidValue) {
        try { Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue } catch { }
    }
    $script:ApiProc = $null
    Remove-Item "$Reports/.api.pid" -ErrorAction SilentlyContinue
}

function Invoke-ComposeInfra {  # postgres + redis + llm-stub (Docker) + schema/seed (host) — Stage 3
    Invoke-Compose "up -d postgres redis llm-stub"
    python -m scripts.init_test_db
    if ($LASTEXITCODE -ne 0) { throw "scripts.init_test_db failed" }
}

function Invoke-ComposeApi {  # + the backend, run natively on the host (Stage 4+)
    # -Checkpointer "memory" (Stage 8) forces a fresh server with the lock-free
    # in-memory saver — the Postgres saver serialises every graph turn on one
    # asyncio.Lock. Otherwise reuse a healthy server.
    param([string]$Checkpointer = "")
    Invoke-ComposeInfra
    if (-not $Checkpointer) {
        try {
            $r = Invoke-WebRequest -Uri "http://localhost:8000/live" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { return $true }
        } catch { }
    }
    Stop-TestApi
    # Never inherit reload for perf/e2e — watchfiles churn thrashes concurrency.
    $env:SERVE_TEST_API_RELOAD = $null
    $env:KODMOD_CHECKPOINTER = if ($Checkpointer) { $Checkpointer } else { "postgres" }
    $script:ApiProc = Start-Process -FilePath "python" -ArgumentList "-m", "scripts.serve_test_api" `
        -NoNewWindow -PassThru -RedirectStandardOutput "$Reports/api.log" -RedirectStandardError "$Reports/api.err.log"
    $script:ApiProc.Id | Out-File -FilePath "$Reports/.api.pid" -Encoding ascii
    if (-not (Wait-ApiHealthy)) { return $false }
    return $true
}

function Test-Want([int]$Num) {
    if ($Gate -or $Burndown) { return $false }
    if ($null -ne $Only) { return $Num -eq $Only }
    return $Num -ge $From
}

function Invoke-Stage([int]$Num, [string]$Label, [scriptblock]$Body) {
    if (-not (Test-Want $Num)) { return }
    Write-Header "Stage $Num  -  $Label"
    $ok = & $Body
    if ($ok -eq $false) {
        Write-Bad "Stage $Num FAILED  -  fix the root cause, then: pwsh scripts/run_tests.ps1 -From $Num"
        throw "STAGE_FAILED:$Num"
    }
    Write-Ok "Stage $Num PASSED"
}

# ------------------------------------------------------------------ stages ----

function Stage0 {
    # Stage 0 is a single pytest run of `-m static` (tests/static/, spec:
    # docs/testplan/00-static.md). Those cases shell out to ruff / mypy /
    # bandit / pip-audit / detect-secrets / docker compose and skip cleanly
    # when a tool is absent. Image-build cases (`static and slow`) run in CI's
    # full `-m static`.
    $select = if ($env:STATIC_SELECT) { $env:STATIC_SELECT } else { "static and not slow" }
    python -m pytest -q -m "$select $NotKnownBug" --junitxml="$Reports/junit-static.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage1 {
    python -m pytest -q -m "unit $NotKnownBug" --junitxml="$Reports/junit-unit.xml" `
        --cov --cov-report="xml:$Reports/coverage-unit.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage2 {
    python -m pytest -q -m "contract $NotKnownBug" --junitxml="$Reports/junit-contract.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage3 {
    Invoke-ComposeInfra
    python -m pytest -q -m "integration $NotKnownBug" --junitxml="$Reports/junit-integration.xml" `
        --cov --cov-report="xml:$Reports/coverage-integration.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage4 {
    if (-not (Invoke-ComposeApi)) { return $false }
    python -m pytest -q -m "api $NotKnownBug" --junitxml="$Reports/junit-api.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage5 {
    if (-not (Invoke-ComposeApi)) { return $false }
    python -m pytest -q -m "ws $NotKnownBug" --junitxml="$Reports/junit-ws.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage6 {
    if (-not (Invoke-ComposeApi)) { return $false }
    python -m pytest -q -m "e2e $NotKnownBug" --junitxml="$Reports/junit-e2e.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage7 {
    if (-not (Invoke-ComposeApi)) { return $false }
    python -m pytest -q -m "system $NotKnownBug" --junitxml="$Reports/junit-system.xml"
    return ($LASTEXITCODE -eq 0)
}

function Stage8 {  # non-blocking: record baselines, never fail the pipeline
    if (-not (Invoke-ComposeApi -Checkpointer "memory")) { return $true }
    Invoke-Compose "--profile load up -d locust"
    python -m pytest -q -m "perf $NotKnownBug" --junitxml="$Reports/junit-perf.xml" `
        --benchmark-json="docs/testplan/baselines/bench.json"
    if ($LASTEXITCODE -ne 0) { Write-Bad "Stage 8 had failures (non-blocking)  -  see reports/junit-perf.xml" }
    return $true
}

function Stage9 {
    if (-not (Invoke-ComposeApi)) { return $false }
    python -m pytest -q -m "security $NotKnownBug" --junitxml="$Reports/junit-security.xml"
    return ($LASTEXITCODE -eq 0)
}

function Invoke-Burndown {  # non-blocking: how many tracked bugs are still open (RED)
    Write-Header "Known-bug burndown"
    python -m pytest -q -m known_bug --no-header -rN --junitxml="$Reports/junit-known-bug.xml"
    Write-Host "(failures above = bugs still open; passes = fixed  -  remove the known_bug marker)"
}

function Invoke-Gate {
    Write-Header "Stage 10  -  Release Readiness Gate"
    # Repo-inspection meta-checks (traceability, docs, migration policy, marker
    # hygiene) - no service needed. Non-blocking; readiness_gate.py folds the
    # result in via reports/junit-readiness.xml.
    python -m pytest -q -m "readiness $NotKnownBug" --junitxml="$Reports/junit-readiness.xml"
    if ($LASTEXITCODE -ne 0) {
        Write-Bad "Stage 10 readiness meta-checks had failures  -  see reports/junit-readiness.xml"
    }
    python scripts/readiness_gate.py
    return ($LASTEXITCODE -eq 0)
}

# ------------------------------------------------------------------- main -----

if ($Burndown) {
    Invoke-Burndown
    exit 0
}

$exitCode = 0
try {
    Invoke-Stage 0 "Static & Build"        { Stage0 }
    Invoke-Stage 1 "Unit"                  { Stage1 }
    Invoke-Stage 2 "Contract / Schema"     { Stage2 }
    Invoke-Stage 3 "Integration"           { Stage3 }
    Invoke-Stage 4 "API / Endpoint"        { Stage4 }
    Invoke-Stage 5 "WebSocket / Realtime"  { Stage5 }
    Invoke-Stage 6 "E2E user journey"      { Stage6 }
    Invoke-Stage 7 "System (black-box)"    { Stage7 }
    Invoke-Stage 8 "Performance / Load"    { Stage8 }
    Invoke-Stage 9 "Security (dynamic)"    { Stage9 }

    if ($Gate) {
        if ((Invoke-Gate) -eq $false) { throw "STAGE_FAILED:10" }
    } elseif ($null -eq $Only -and $From -le 9) {
        Invoke-Gate | Out-Null   # full-pipeline run: report the gate, non-blocking
    }

    # Always show what's left on the bug backlog (never fails the pipeline).
    if ($null -eq $Only) { Invoke-Burndown }

    Write-Ok "pipeline complete"
} catch {
    if ("$_" -notmatch '^STAGE_FAILED:') { Write-Bad "$_" }
    $exitCode = 1
} finally {
    Stop-TestApi
}
exit $exitCode
