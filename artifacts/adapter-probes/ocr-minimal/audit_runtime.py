"""Record installed metadata, wheel hashes, notices and actual native linkage."""

import hashlib
import importlib.metadata
import json
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE.parents[2] / ".visionapp/adapter-probes/ocr-minimal/venv"
SITE = ENV / "lib/python3.12/site-packages"
rows = []
if (HERE / "notices").exists():
    shutil.rmtree(HERE / "notices")
for dist in sorted(importlib.metadata.distributions(), key=lambda d: d.metadata["Name"].lower()):
    notices = []
    for relative in dist.files or []:
        if not any(
            part in relative.name.lower() for part in ("license", "copying", "notice", "copyright")
        ):
            continue
        source = dist.locate_file(relative)
        if not source.is_file() or source.suffix == ".xml":
            continue
        content = source.read_bytes()
        target = HERE / "notices" / dist.metadata["Name"] / str(relative).replace("/", "__")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        notices.append(
            {
                "path": str(relative),
                "saved": str(target.relative_to(HERE)),
                "sha256": hashlib.sha256(content).hexdigest(),
                "bytes": len(content),
            }
        )
    rows.append(
        {
            "name": dist.metadata["Name"],
            "version": dist.version,
            "license": dist.metadata.get("License"),
            "license_expression": dist.metadata.get("License-Expression"),
            "license_classifiers": [
                x for x in dist.metadata.get_all("Classifier", []) if "License" in x
            ],
            "requires": dist.requires or [],
            "notices": notices,
        }
    )
(HERE / "dependency-notices.json").write_text(json.dumps(rows, indent=2) + "\n")
(HERE / "requirements.lock").write_text(
    "\n".join(row["name"] + "==" + row["version"] for row in rows) + "\n"
)
native = []
for path in sorted(SITE.rglob("*")):
    if path.suffix not in (".so", ".dylib") or not path.is_file():
        continue
    links = subprocess.run(
        ["otool", "-L", str(path)], check=True, capture_output=True, text=True
    ).stdout
    native.append(
        {
            "path": str(path.relative_to(ENV)),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "linkage": links.splitlines()[1:],
        }
    )
(HERE / "native-library-inventory.json").write_text(json.dumps(native, indent=2) + "\n")
print(
    json.dumps(
        {
            "distributions": len(rows),
            "native_binaries": len(native),
            "environment_bytes": sum(p.stat().st_size for p in ENV.rglob("*") if p.is_file()),
        }
    )
)
