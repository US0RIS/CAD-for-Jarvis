$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Engine = Join-Path $Root 'services\forge-engine'
$Venv = Join-Path $Engine '.venv'
$Python = Join-Path $Venv 'Scripts\python.exe'

Write-Host 'ForgeCAD v2 — Windows bootstrap' -ForegroundColor Green
if (-not (Test-Path $Python)) {
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { & py -3.12 -m venv $Venv }
  else {
    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCmd) { throw 'Python 3.12 is required. Install 64-bit Python 3.12, then rerun this script.' }
    & python -m venv $Venv
  }
}
& $Python -m pip install --upgrade pip
& $Python -m pip install -e $Engine

if (-not (Get-Command corepack -ErrorAction SilentlyContinue)) { throw 'Node.js 22+ with corepack is required.' }
Push-Location $Root
try {
  corepack enable
  pnpm install
} finally { Pop-Location }

Write-Host ''
Write-Host 'Windows runtime ready.' -ForegroundColor Green
Write-Host 'Run:  pnpm dev' -ForegroundColor Cyan
Write-Host 'Windows default Ollama model: qwen3.8:27b (override with FORGECAD_OLLAMA_MODEL).'
