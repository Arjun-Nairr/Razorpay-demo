# Launch the local Case 3 demo: FastAPI (uvicorn) + Streamlit UI, both on localhost.
#
#   Setup (once):
#     python -m venv .venv
#     .\.venv\Scripts\Activate.ps1
#     python -m pip install -e ".[api,db,gemini,ui,dev]"
#     # put GEMINI_API_KEY and DATABASE_URL in .\.env  (see .env.example)
#     python scripts\init_neon.py           # one-time, idempotent, non-destructive
#
#   Run:
#     .\scripts\run_demo.ps1 -Mode hermes    # actual isolated Nous Hermes + Gemini + Neon
#     .\scripts\run_demo.ps1 -Mode live      # direct Gemini + Neon
#     .\scripts\run_demo.ps1 -Mode offline   # no credentials; scripted proposals
#
#   Shutdown:
#     press Ctrl+C in this window (the script then stops the API job), or close
#     the window; if a stray job is left:  Get-Job | Stop-Job ; Get-Job | Remove-Job

param(
    [ValidateSet("live", "offline", "hermes")]
    [string]$Mode = "live",
    [int]$ApiPort = 8000,
    [int]$UiPort = 8501
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:HERMES_MODE = $Mode
$env:HERMES_API_BASE = "http://127.0.0.1:$ApiPort"

# --- use the PROJECT venv interpreter, not whatever `python` resolves to on PATH.
# (A bare `python` in a background job resolved to the system interpreter, which
# also had fastapi/uvicorn/psycopg installed, so the wrong Python ran the app.)
$py = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $py) {
    Write-Host "No project .venv and no `python` on PATH. Run: python -m venv .venv" -ForegroundColor Red
    exit 1
}
# With the venv interpreter the installed package is used; keep a src fallback
# only if it is somehow not installed there.
& $py -c "import hermes" 2>$null
if ($LASTEXITCODE -ne 0 -and -not $env:PYTHONPATH) { $env:PYTHONPATH = "$repo\src" }

# --- one consistent bounded startup budget -----------------------------------
# The app's DB phase (connect + advisory lock + first read) is bounded by
# HERMES_DB_CONNECT_TIMEOUT_S (default 30s in hermes/live modes). The launcher's
# health wait is ALWAYS that budget + a fixed margin for process spawn + uvicorn
# bind, so the launcher ceiling is never tighter than the DB ceiling. It still
# breaks immediately when the job dies (a sanitised SystemExit).
$dbBudget = if ($env:HERMES_DB_CONNECT_TIMEOUT_S) { [int]$env:HERMES_DB_CONNECT_TIMEOUT_S } else { 30 }
if ($Mode -eq "offline") { $maxWaitSec = 20 } else { $maxWaitSec = $dbBudget + 30 }

Write-Host "Interpreter: $py" -ForegroundColor DarkGray
Write-Host ("Starting FastAPI (uvicorn) on 127.0.0.1:{0}  [mode={1}]  (startup budget {2}s, health wait {3}s)" -f `
    $ApiPort, $Mode, $dbBudget, $maxWaitSec) -ForegroundColor Cyan
$api = Start-Job -Name hermes-api -ScriptBlock {
    param($repo, $port, $mode, $py, $pp, $dbb)
    Set-Location $repo
    $env:HERMES_MODE = $mode
    if ($pp) { $env:PYTHONPATH = $pp }
    if ($dbb) { $env:HERMES_DB_CONNECT_TIMEOUT_S = $dbb }
    & $py -m uvicorn hermes.asgi:app --host 127.0.0.1 --port $port
} -ArgumentList $repo, $ApiPort, $Mode, $py, $env:PYTHONPATH, $env:HERMES_DB_CONNECT_TIMEOUT_S
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$healthy = $false
$r = $null
while ($sw.Elapsed.TotalSeconds -lt $maxWaitSec) {
    if ($api.State -eq "Failed" -or $api.State -eq "Completed") { break }
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/health" -TimeoutSec 3
        if ($r.status -eq "ok") { $healthy = $true; break }
    } catch { }
    Start-Sleep -Seconds 1
}
$sw.Stop()

if (-not $healthy) {
    Write-Host ("API did not become healthy after {0:n0}s. Job state: {1}. Startup output:" -f `
        $sw.Elapsed.TotalSeconds, $api.State) -ForegroundColor Red
    Receive-Job -Job $api
    Stop-Job -Job $api -ErrorAction SilentlyContinue
    Remove-Job -Job $api -ErrorAction SilentlyContinue
    exit 1
}
Write-Host ("API healthy in {0:n0}s (mode reported by /health): {1})" -f `
    $sw.Elapsed.TotalSeconds, $r.mode) -ForegroundColor Green

Write-Host "Starting Streamlit UI on 127.0.0.1:$UiPort" -ForegroundColor Cyan
try {
    & $py -m streamlit run scripts\demo_ui.py `
        --server.address 127.0.0.1 --server.port $UiPort --server.headless true
}
finally {
    Write-Host "Stopping background API job..." -ForegroundColor Yellow
    Stop-Job -Job $api -ErrorAction SilentlyContinue
    Remove-Job -Job $api -ErrorAction SilentlyContinue
}
