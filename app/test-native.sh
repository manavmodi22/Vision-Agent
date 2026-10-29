#!/bin/sh
set -eu
APP_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
swift build --package-path "$APP_ROOT"
APP_BIN=$(swift build --package-path "$APP_ROOT" --show-bin-path)
"$APP_BIN/VisionApp" --self-test
