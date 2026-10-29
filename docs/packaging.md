# Relocatable Mac package

Owner: application integration. The bundle must run after it is moved to a path
with spaces, with the checkout and development virtual environment absent from its
module search path. Python and production wheels ship inside the bundle; detector
weights and user data remain in Application Support.

## Interface and layout

`scripts/build_app.sh` builds a self-contained Apple silicon app using the locked
production and vision dependencies at `dist/VisionApp.app`. `--development`
builds a separate `dist/VisionApp-Development.app` checkout launcher for iteration.
The development bundle is assembled from an empty staging directory, contains
the native binary, Info.plist and checkout pointer, and uses the checkout’s
`.venv/bin/python`. It cannot inherit stale PythonRuntime contents from a portable
build and never modifies `dist/VisionApp.app`. Its display name and bundle identifier
are distinct so Launch Services can distinguish it from the portable app. Open the
exact development path when testing current backend changes. `scripts/package_runtime.py` owns staging, dependency
installation, dependency/license inventory, Mach-O signing and bundle assembly.

- `Contents/MacOS/VisionApp`: native UI and Apple Vision bridge.
- `Contents/Resources/PythonRuntime`: pinned CPython 3.12.14 from Astral's
  python-build-standalone, with locked production wheels and our installed wheel.
- `Contents/Resources/engine`: build manifest and dependency inventory; the
  supervised process uses this as its working directory.
- The supervisor chooses a bundled interpreter before looking for a development
  checkout. User-site packages, inherited Python search paths and bytecode writes
  are disabled for the supervised engine and MCP child.

Python standalone builds are the same distribution family used by uv; runtime
download/install goes through uv rather than copying a developer's interpreter.
See [Astral's distribution documentation](https://docs.astral.sh/python-build-standalone/)
and [uv's Python support](https://docs.astral.sh/uv/concepts/python-versions/).
No model weights, credentials, project data or local model-server configuration
are embedded. Model downloads remain a separate installation step.

## Failure and validation boundaries

Assembly happens in a new staging directory. Failed builds leave the existing
bundle intact. Every Mach-O is signed from the inside out; the bundle is verified
after assembly. A release identity can be supplied through `VISION_SIGN_IDENTITY`.
Without a Developer ID identity the result is explicitly a locally signed build,
not a hardened or notarized distribution. Ad-hoc signatures have no common Team ID
for Python extension library validation. The release identity path enables the
hardened runtime and uses the same identity for all nested code; no library
validation exception is added. Notarization requires Developer ID, hardened runtime
and Apple's service; see [Apple's distribution requirements](https://developer.apple.com/documentation/security/notarizing-macos-software-before-distribution).

Validation must launch the relocated interpreter with an unrelated working
directory and clean Python environment, import the actual engine/model adapters,
start its Unix-socket API, run a fixture pipeline and Apple Vision, and execute
real detector inference. Native self-tests and signature verification also run.
Successful packaging does not establish camera accuracy or model quality.
