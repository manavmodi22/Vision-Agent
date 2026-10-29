"""Install the reviewed publisher checkpoint at an immutable revision."""
from pathlib import Path

from huggingface_hub import snapshot_download

from engine.models.manager import rtdetr_path

MODEL = "PekingU/rtdetr_v2_r18vd"
REVISION = "5650961749fa93567c0d46fc7f43ea4f9e914107"


def main() -> None:
    path = rtdetr_path()
    snapshot_download(MODEL, revision=REVISION, local_dir=path,
                      allow_patterns=["config.json", "preprocessor_config.json", "model.safetensors", "README.md"])
    (Path(path) / "VISIONAPP_REVISION.txt").write_text(REVISION + "\n")
    print(f"Installed {MODEL} at {REVISION} in {path}")


if __name__ == "__main__":
    main()
