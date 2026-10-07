# One command for everyone: set the data up (first time only, about 3 minutes), clear any stale stub override, and start the interface with every module real.
#   .\run_demo.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Remove-Item Env:LEXSHIFT_STUBS -ErrorAction SilentlyContinue   # a leftover override from an earlier session is what turns stub mode on
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Creating the virtual environment (once)..."
    python -m venv .venv
    & $py -m pip install -r requirements.txt
    & $py -m nltk.downloader stopwords
}
$env:PYTHONIOENCODING = "utf-8"
& $py -m app.setup
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Get-NetTCPConnection -LocalPort 8765 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }   # an old server on the same port would keep answering
& $py -m app.server --real --open
