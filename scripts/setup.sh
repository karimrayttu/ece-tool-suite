#!/usr/bin/env bash
# One-time developer setup on macOS/Linux: Python venv + backend install + JS dependencies.
#
#   ./scripts/setup.sh [--minimal]
#
# Instrument I/O on these platforms goes through pyvisa-py (LAN/LXI works; USBTMC needs
# libusb). The Windows-only tabs (LabVIEW, STM32CubeMX detection, one-click installers)
# report themselves unavailable rather than failing.

set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
venv="$repo/backend/.venv"
# Same list as setup.ps1. `labview` carries a sys_platform marker, so pip installs nothing for
# it here. `spice` pulls in spicelib (GPL-3.0); read THIRD-PARTY-NOTICES.md before you
# redistribute a build that includes it.
extras="hw,assistant,mcu,labview,power,spice,rtl,dev"

[[ "${1:-}" == "--minimal" ]] && extras="dev"

command -v python3 >/dev/null || { echo "python3 not found (need 3.12+)" >&2; exit 1; }
command -v node    >/dev/null || { echo "node not found (need 18+)" >&2; exit 1; }

pyver=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
if [[ $(printf '%s\n3.12\n' "$pyver" | sort -V | head -1) != "3.12" ]]; then
  echo "Python $pyver found, 3.12+ required." >&2
  exit 1
fi

[[ -d "$venv" ]] || { echo "Creating $venv (Python $pyver)"; python3 -m venv "$venv"; }

"$venv/bin/python" -m pip install --upgrade pip --quiet
echo "Installing backend with extras: $extras"
"$venv/bin/python" -m pip install -e "$repo/backend[$extras]"

echo "Installing JavaScript dependencies"
(cd "$repo" && npm install)

cat <<'EOF'

Done. Next:
  npm test          # backend test suite
  npm run dev       # backend + UI at http://localhost:5173
  npm run app       # native Electron window
EOF
