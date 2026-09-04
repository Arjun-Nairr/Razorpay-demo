# Launch the local Case 3 demo: FastAPI (uvicorn) + Streamlit UI, both on localhost.
#
#   Setup (once):
#     python -m venv .venv
#     .\.venv\Scripts\Activate.ps1
#     python -m pip install -e ".[api,db,gemini,ui]"
#     # put GEMINI_API_KEY and DATABASE_URL in .\.env  (see .env.example)
#     python scripts\init_neon.py           # one-time, idempotent, non-destructive
#
#   Run:
#     .\scripts\run_demo.ps1                # live mode (real Gemini + Neon)
#     .\scripts\run_demo.ps1 -Mode offline  # no credentials; scripted proposals
#
#   Shutdown:
#     press Ctrl+C in this window, then:
#     Get-Job | Stop-Job ; Get-Job | Remove-Job
#     (or just close the window; the child jobs are stopped on exit)

param(
    [ValidateSet("live", "offline")]
    [string]$Mode = "live",
    [int]$ApiPort = 8000,
    [int]$UiPort = 8501
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$env:HERMES_MODE = $Mode
$env:HERMES_API_BASE = "http://127.0.0.1:$ApiPort"

Write-Host "Starting FastAPI (uvicorn) on 127.0.0.1:$ApiPort  [mode=$Mode]" -ForegroundColor Cyan
$api = Start-Job -Name hermes-api -ScriptBlock {
    param($repo, $port, $mode)
    Set-Location $repo
    $env:HERMES_MODE = $mode
    python -m uvicorn hermes.asgi:app --host 127.0.0.1 --port $port
} -ArgumentList $repo, $ApiPort, $Mode

Start-Sleep -Seconds 3
Write-Host "Starting Streamlit UI on 127.0.0.1:$UiPort" -ForegroundColor Cyan
try {
    python -m streamlit run scripts\demo_ui.py `
        --server.address 127.0.0.1 --server.port $UiPort --server.headless true
}
finally {
    Write-Host "Stopping background API job..." -ForegroundColor Yellow
    Stop-Job -Job $api -ErrorAction SilentlyContinue
    Remove-Job -Job $api -ErrorAction SilentlyContinue
}
