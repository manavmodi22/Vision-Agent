#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
if [ -x "$REPO_ROOT/dist/VisionApp.app/Contents/MacOS/VisionApp" ]; then
  export VISION_APP_BINARY="$REPO_ROOT/dist/VisionApp.app/Contents/MacOS/VisionApp"
fi
exec .venv/bin/python -m engine.api "$@"
