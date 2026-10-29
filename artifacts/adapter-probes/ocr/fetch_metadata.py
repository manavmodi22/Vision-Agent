"""Fetch only upstream documentation/metadata; no packages, weights or inference."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen

OUT = Path(__file__).parent


def fetch(name: str, url: str) -> tuple[str, dict]:
    request = Request(url, headers={"User-Agent": "VisionApp-readonly-ocr-research"})
    with urlopen(request, timeout=25) as response:
        body = response.read(2_000_001)
    if len(body) > 2_000_000:
        raise ValueError("Metadata response exceeds 2MB bound")
    (OUT / name).write_bytes(body)
    return name, {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}


def batch(items: dict[str, str]) -> dict[str, dict]:
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fetch, name, url): name for name, url in items.items()}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                key, value = future.result()
                results[key] = value
            except Exception as exc:
                results[name] = {"url": items[name], "error": str(exc)}
    return results


def read(name: str) -> dict:
    return json.loads((OUT / name).read_text())


def main() -> None:
    models = ["PP-OCRv5_mobile_det", "en_PP-OCRv5_mobile_rec", "PaddleOCR-VL-1.6"]
    metadata = {
        "paddleocr-commit.json": "https://api.github.com/repos/PaddlePaddle/PaddleOCR/commits/main",
        "tesseract-release.json": "https://api.github.com/repos/tesseract-ocr/tesseract/releases/latest",
        "tessdata-commit.json": "https://api.github.com/repos/tesseract-ocr/tessdata_fast/commits/main",
        "tessdoc-commit.json": "https://api.github.com/repos/tesseract-ocr/tessdoc/commits/main",
        "mlx-vlm-commit.json": "https://api.github.com/repos/Blaizzy/mlx-vlm/commits/main",
        "paddlepaddle-pypi.json": "https://pypi.org/pypi/paddlepaddle/3.2.1/json",
        "paddleocr-pypi.json": "https://pypi.org/pypi/paddleocr/json",
        "mlx-vlm-pypi.json": "https://pypi.org/pypi/mlx-vlm/json",
        "tesseract-homebrew.json": "https://formulae.brew.sh/api/formula/tesseract.json",
    }
    for model in models:
        metadata[f"{model}-metadata.json"] = (
            f"https://huggingface.co/api/models/PaddlePaddle/{model}?blobs=true"
        )
    evidence = batch(metadata)
    documents = {}
    paddle_sha = read("paddleocr-commit.json")["sha"]
    for name, path in {
        "paddleocr-license.txt": "LICENSE",
        "paddleocr-apple-silicon.md": "docs/version3.x/pipeline_usage/PaddleOCR-VL-Apple-Silicon.en.md",
        "paddleocr-ocr.md": "docs/version3.x/pipeline_usage/OCR.en.md",
        "paddleocr-text-recognition.md": "docs/version3.x/module_usage/text_recognition.en.md",
    }.items():
        documents[name] = (
            f"https://raw.githubusercontent.com/PaddlePaddle/PaddleOCR/{paddle_sha}/{path}"
        )
    for prefix, repo, files in [
        (
            "tessdata",
            "tesseract-ocr/tessdata_fast",
            {"README.md": "README.md", "LICENSE": "LICENSE"},
        ),
        (
            "tessdoc",
            "tesseract-ocr/tessdoc",
            {"Installation.md": "Installation.md", "Data-Files.md": "Data-Files.md"},
        ),
        ("mlx-vlm", "Blaizzy/mlx-vlm", {"README.md": "README.md", "LICENSE": "LICENSE"}),
    ]:
        revision = read(f"{prefix}-commit.json")["sha"]
        for filename, path in files.items():
            documents[f"{prefix}-{filename}"] = (
                f"https://raw.githubusercontent.com/{repo}/{revision}/{path}"
            )
    tag = read("tesseract-release.json")["tag_name"]
    documents["tesseract-license.txt"] = (
        f"https://raw.githubusercontent.com/tesseract-ocr/tesseract/{tag}/LICENSE"
    )
    documents["tesseract-commit.json"] = (
        f"https://api.github.com/repos/tesseract-ocr/tesseract/commits/{tag}"
    )
    tessdata_sha = read("tessdata-commit.json")["sha"]
    documents["eng-traineddata-metadata.json"] = (
        f"https://api.github.com/repos/tesseract-ocr/tessdata_fast/contents/eng.traineddata?ref={tessdata_sha}"
    )
    for model in models:
        revision = read(f"{model}-metadata.json")["sha"]
        documents[f"{model}-README.md"] = (
            f"https://huggingface.co/PaddlePaddle/{model}/raw/{revision}/README.md"
        )
    evidence.update(batch(documents))
    (OUT / "sources.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(
        json.dumps(
            {
                "saved": len(evidence),
                "errors": {k: v for k, v in evidence.items() if "error" in v},
                "paddleocr_revision": paddle_sha,
                "tesseract_tag": tag,
                "models": {
                    model: {
                        "revision": read(f"{model}-metadata.json")["sha"],
                        "license": read(f"{model}-metadata.json")
                        .get("cardData", {})
                        .get("license"),
                    }
                    for model in models
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
