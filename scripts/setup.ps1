# One-time developer setup: Python venv + backend install + JS dependencies.
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#
# Pass -Minimal to skip the optional extras (USB/serial discovery, the Claude assistant,
# MCU flashing, the power-design engine). The app runs without them; the matching tabs
# report what is missing instead of failing.
#
# The full set includes `spice`, which pulls in spicelib (GPL-3.0). That is fine for local
# development. If you are building something you intend to redistribute, leave it out and
# read THIRD-PARTY-NOTICES.md first.

[CmdletBinding()]
param(
    [switch]$Minimal,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $repo "backend\.venv"

function Require-Command($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "$name is not on PATH. $hint"
    }
}

# A failing .exe does not raise in PowerShell no matter what ErrorActionPreference says, so
# every external call has to be checked by hand or the script cheerfully reports success.
function Assert-LastExit($what) {
    if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" }
}

Require-Command $Python "Install CPython 3.12 or newer from python.org."
Require-Command "node" "Install Node.js 18 or newer from nodejs.org."

$pyVersion = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$pyVersion -lt [version]"3.12") {
    throw "Python $pyVersion found, 3.12+ required. Pass -Python <path-to-3.12> if you have both."
}

if (-not (Test-Path $venv)) {
    Write-Host "Creating $venv (Python $pyVersion)"
    & $Python -m venv $venv
    Assert-LastExit "python -m venv"
}

$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --upgrade pip --quiet
Assert-LastExit "pip upgrade"

$extras = if ($Minimal) { "dev" } else { "hw,assistant,mcu,labview,power,spice,rtl,dev" }
Write-Host "Installing backend with extras: $extras"
& $vpy -m pip install -e "$repo\backend[$extras]"
Assert-LastExit "pip install backend"

Write-Host "Installing JavaScript dependencies"
Push-Location $repo
try { npm install; Assert-LastExit "npm install" } finally { Pop-Location }

Write-Host ""
Write-Host "Done. Next:"
Write-Host "  npm test          # backend test suite"
Write-Host "  npm run dev       # backend + UI at http://localhost:5173"
Write-Host "  npm run app       # native Electron window"
