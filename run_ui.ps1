# Launch the RepoMedic AI UI on http://localhost:8501 (localhost only) and open it in your browser.
#   .\run_ui.ps1                 start and open the browser
#   .\run_ui.ps1 -NoBrowser      start without opening a browser
#   .\run_ui.ps1 -Port 8600      use another port
param(
    [int]$Port = 8501,
    [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

python -c "import streamlit" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Error "Streamlit is not installed. Run:  python -m pip install -r requirements.txt"
    exit 1
}

$url = "http://localhost:$Port"
try {
    $null = Invoke-RestMethod "http://127.0.0.1:11434/api/tags" -TimeoutSec 3
    Write-Host "Ollama: reachable"
} catch {
    Write-Warning "Ollama is not reachable at 127.0.0.1:11434; start it with 'ollama serve' before diagnosing."
}
if (-not (Test-Path ".venv-graphify\Scripts\graphify.exe") -and -not (Get-Command graphify -ErrorAction SilentlyContinue)) {
    Write-Warning "Graphify CLI not found; see README 'Quick start' step 1. The UI will explain this too."
}

if (-not $NoBrowser) {
    # Open the browser once the server reports healthy (a cold first start can take over a minute).
    Start-Job -ArgumentList $url -ScriptBlock {
        param($u)
        for ($i = 0; $i -lt 180; $i++) {
            try {
                if ((Invoke-WebRequest "$u/_stcore/health" -UseBasicParsing -TimeoutSec 2).Content -eq 'ok') {
                    Start-Process $u
                    break
                }
            } catch { }
            Start-Sleep -Seconds 1
        }
    } | Out-Null
}

Write-Host "RepoMedic AI -> $url   (Ctrl+C to stop)"
python -m streamlit run app.py --server.port $Port --server.address localhost
