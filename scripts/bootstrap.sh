#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
PYTHON_BIN="${VISION_PYTHON:-python3.12}"
if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
fi
.venv/bin/python -m pip install -e '.[dev,vision]'
printf '\nNext: scripts/build_app.sh, then open dist/VisionApp.app\n'
