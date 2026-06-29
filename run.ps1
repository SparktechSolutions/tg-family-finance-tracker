# run.ps1 — Windows (PowerShell) companion to run.sh.
# Usage:  .\run.ps1 [setup|start|test|connector|import <file>|all]
# (macOS/Linux/WSL/Git Bash users: use ./run.sh instead.)

param([string]$Cmd = "all", [string]$Arg = "")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Venv = ".venv"
$Py = Join-Path $Root "$Venv\Scripts\python.exe"
$Port = if ($env:PORT) { $env:PORT } else { "8000" }

function Find-Python {
  foreach ($c in @("py -3.12","py -3.11","py -3.10","python","python3")) {
    try { & cmd /c "$c --version" *> $null; if ($LASTEXITCODE -eq 0) { return $c } } catch {}
  }
  throw "Python 3.10+ not found. Install from https://www.python.org/downloads/"
}

function Setup {
  $p = Find-Python
  if (-not (Test-Path $Venv)) { Write-Host "Creating virtualenv..."; & cmd /c "$p -m venv $Venv" }
  Write-Host "Installing dependencies..."
  & $Py -m pip install --quiet --upgrade pip
  & $Py -m pip install --quiet -r requirements.txt
  if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env (dry-run mode)" }
  Write-Host "Setup complete."
}
function Ensure { if (-not (Test-Path $Py)) { Setup } }
function Test  { Ensure; & $Py -m pip install --quiet pytest; & $Py -m pytest -q }
function Start { Ensure; Write-Host "http://localhost:$Port/ (Ctrl-C to stop)"; & $Py -m uvicorn app.main:app --host 0.0.0.0 --port $Port --reload }
function Connector {
  $p = Find-Python
  if (-not (Test-Path ".venv-connector")) { & cmd /c "$p -m venv .venv-connector" }
  & ".venv-connector\Scripts\python.exe" -m pip install --quiet --upgrade pip
  & ".venv-connector\Scripts\python.exe" -m pip install --quiet -r connector\requirements.txt
  Write-Host "Connector ready. See connector\README.md for the MCP config."
}

switch ($Cmd) {
  "all"       { Setup; Test; Start }
  "setup"     { Setup }
  "start"     { Start }
  "run"       { Start }
  "test"      { Test }
  "connector" { Connector }
  "import"    { Ensure; & $Py -m app.importer $Arg --group "cowork-household" }
  default     { Write-Host "Usage: .\run.ps1 [setup|start|test|connector|import <file>|all]" }
}
