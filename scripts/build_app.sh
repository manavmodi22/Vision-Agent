#!/bin/bash
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
swift build --package-path app -c release
if [ "${1:-}" != "--development" ]; then
    exec "$REPO_ROOT/.venv/bin/python" scripts/package_runtime.py "$@"
fi

# Never overlay the portable app: its PythonRuntime takes precedence over a
# checkout pointer, so mixing the two layouts would silently run stale code.
APP_DIR="$REPO_ROOT/dist/VisionApp-Development.app"
mkdir -p "$REPO_ROOT/dist"
STAGING_DIR="$(mktemp -d "$REPO_ROOT/dist/.visionapp-development.XXXXXX")"
STAGED_APP="$STAGING_DIR/VisionApp-Development.app"
PREVIOUS_APP="$STAGING_DIR/previous-development.app"
trap 'rm -rf "$STAGING_DIR"' EXIT
mkdir -p "$STAGED_APP/Contents/MacOS" "$STAGED_APP/Contents/Resources"
cp app/.build/release/VisionApp "$STAGED_APP/Contents/MacOS/VisionApp"
cp app/Info.plist "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleIdentifier com.visionapp.local.development' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleName VisionApp Development' "$STAGED_APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Set :CFBundleDisplayName VisionApp Development' "$STAGED_APP/Contents/Info.plist"
printf '%s\n' "$REPO_ROOT" > "$STAGED_APP/Contents/Resources/repo-root.txt"
codesign --force --sign - "$STAGED_APP"
codesign --verify --deep --strict "$STAGED_APP"
if [ -e "$APP_DIR" ]; then
    mv "$APP_DIR" "$PREVIOUS_APP"
fi
if ! mv "$STAGED_APP" "$APP_DIR"; then
    if [ -e "$PREVIOUS_APP" ]; then
        mv "$PREVIOUS_APP" "$APP_DIR"
    fi
    exit 1
fi
codesign --verify --deep --strict "$APP_DIR"
printf 'Built local development app: %s\n' "$APP_DIR"
