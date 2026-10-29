"""Prepare a predeclared local scene pair; never call a model or app service."""
from __future__ import annotations

import hashlib
import io
import json
import struct
from datetime import UTC, datetime
from pathlib import Path

import PIL
from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[4]
HERE = Path(__file__).resolve().parent
CASE_ID = "bus-destination-v1"
IMAGE_ID = "0568d30600d5cf11"
PROMPT = (
    "Build an app that reads only the route number and destination on the front display "
    "of the red-and-white bus in each supplied image. Ignore branding, registration "
    "plates, other buses and background text. Use the supplied pixels to investigate "
    "how to do this."
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pixels_hash(image: Image.Image) -> str:
    pixels = ImageOps.exif_transpose(image).convert("RGB")
    return sha256(b"RGB\0" + struct.pack(">II", *pixels.size) + pixels.tobytes())


def immutable(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError(f"Refusing to overwrite the frozen case file: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def main() -> None:
    if (HERE / "manifest.json").exists():
        raise SystemExit("The case is already frozen. Inspect manifest.json; do not redefine it after a run.")
    dataset = ROOT / ".visionapp/datasets/textocr-v0.1"
    source_manifest_path = ROOT / "artifacts/reader-evaluation/textocr-manifest.json"
    source_manifest_bytes = source_manifest_path.read_bytes()
    source_manifest = json.loads(source_manifest_bytes)
    row = next(item for item in source_manifest["images"] if item["id"] == IMAGE_ID)
    original = dataset / "images" / (IMAGE_ID + ".jpg")
    original_bytes = original.read_bytes()
    assert sha256(original_bytes) == row["original_sha256"]
    annotation_bytes = (dataset / "TextOCR_0.1_val.json").read_bytes()
    assert sha256(annotation_bytes) == source_manifest["annotation_sha256"]
    annotations = json.loads(annotation_bytes)
    reference_rows = [annotations["anns"][IMAGE_ID + "_" + str(index)] for index in (17, 18, 19, 20)]
    assert [item["utf8_string"] for item in reference_rows] == ["43", "PLYMOUTH", "SKI", "CENTRE"]
    with Image.open(io.BytesIO(original_bytes)) as opened:
        original_pixels = ImageOps.exif_transpose(opened).convert("RGB")
        assert original_pixels.size == (1024, 768)
        degraded = original_pixels.resize((128, 96), Image.Resampling.LANCZOS).filter(ImageFilter.GaussianBlur(.6))
        output = io.BytesIO()
        degraded.save(output, format="JPEG", quality=25, subsampling=2, optimize=False, progressive=False)
    degraded_bytes = output.getvalue()
    local = ROOT / ".visionapp/a0-investigation/cases" / CASE_ID
    paths = {"original": local / "original/scene.jpg", "degraded": local / "degraded/scene.jpg"}
    immutable(paths["original"], original_bytes)
    immutable(paths["degraded"], degraded_bytes)
    immutable(HERE / "planner-prompt.txt", (PROMPT + "\n").encode())
    inputs = []
    for variant, path in paths.items():
        with Image.open(path) as image:
            inputs.append({"variant": variant, "path": path.relative_to(ROOT).as_posix(),
                "file_sha256": sha256(path.read_bytes()), "bytes": path.stat().st_size,
                "size": list(image.size), "decoded_rgb_sha256": pixels_hash(image),
                "data_origin": "real photograph" if variant == "original" else "degraded derivative of the same real photograph",
                "source_image_id": IMAGE_ID, "source_group": "openimages:" + IMAGE_ID})
    manifest = {
        "schema_version": "a0.acceptance-case.1", "case_id": CASE_ID,
        "prepared_at": datetime.now(UTC).isoformat(), "status": "proposed_not_executed",
        "selection": {"method": "Selected from the existing full-scene contact sheet for a clear sign target, realistic surrounding text and small display lettering; before any A0 planner or adapter run on this case.",
            "views_inspected": ["existing 20-scene contact sheet", "original full-scene image", "published annotations for selected scene"],
            "reader_scores_or_outputs_consulted": False, "a0_prior_image_id_or_hash_trace_matches_found": False,
            "unfamiliarity_scope": "New full-scene A0 agent task; not a new image to all project diagnostic work or necessarily model pretraining."},
        "planner_input": {"prompt_file": "artifacts/a0-investigation/cases/" + CASE_ID + "/planner-prompt.txt",
            "prompt": PROMPT, "same_prompt_for_both_variants": True,
            "withhold": ["this manifest", "reference text", "annotation polygons", "display region", "prior reader outputs", "other variant pixels"],
            "project_isolation": "Import only one variant per fresh project through normal WorkspaceService.import_media. Never import original and degraded together into the negative-case project.",
            "import_check": "Import may normalize encoding; verify decoded RGB pixels rather than expecting the imported file bytes to equal the JPEG source."},
        "source": {"dataset": source_manifest["dataset"], "image_id": IMAGE_ID,
            "image_download_url": row["source_url"], "source_metadata": row["source_metadata"],
            "license_status": source_manifest["image_license_status"],
            "image_license": "CC-BY-2.0 as declared in official Open Images metadata; original Flickr license not independently reverified",
            "attribution": "Plymouth M53HOD — Graham Richardson. Original Flickr photograph; Open Images image 0568d30600d5cf11. Degraded version resized, blurred and JPEG-compressed for this software experiment.",
            "official_metadata_source": source_manifest["image_metadata_source"],
            "local_provenance_manifest": source_manifest_path.relative_to(ROOT).as_posix(),
            "local_provenance_manifest_sha256": sha256(source_manifest_bytes),
            "source_file_sha256": row["original_sha256"], "source_rotation_degrees": row["source_rotation_degrees"],
            "annotation_source": source_manifest["annotation_source"], "annotation_license": source_manifest["annotation_license"],
            "annotation_attribution": source_manifest["annotation_attribution"], "annotation_sha256": source_manifest["annotation_sha256"],
            "redistribution": "Source and derivative images remain in ignored local storage; only provenance, task and reference are tracked."},
        "inputs": inputs,
        "degradation": {"predeclared_before_model_runs": True, "pillow_version": PIL.__version__,
            "operations": [{"operation": "resize", "input_size": [1024, 768], "output_size": [128, 96], "resampling": "LANCZOS"},
                {"operation": "gaussian_blur", "radius_pixels_at_reduced_size": .6},
                {"operation": "jpeg_encode", "quality": 25, "subsampling": 2, "optimize": False, "progressive": False}],
            "pixel_count_reduction_factor": 64, "target_word_heights_after_resize_before_blur": {item["utf8_string"]: item["bbox"][3] / 8 for item in reference_rows},
            "scope": "Actual information loss in pixels; no mocked adapter error, blocked endpoint or forced first failure. Not tuned after planner/reader outputs."},
        "reference_evaluator_only": {"route_number": "43", "destination": "PLYMOUTH SKI CENTRE",
            "expected_case_sensitive_tokens": ["43", "PLYMOUTH", "SKI", "CENTRE"],
            "published_words": [{"annotation_id": item["id"], "text": item["utf8_string"], "bbox_xywh": item["bbox"], "polygon_xy": item["points"]} for item in reference_rows],
            "display_envelope_xyxy_pixels": [625, 199, 839, 264],
            "display_envelope_xyxy_normalized": [625 / 1024, 199 / 768, 839 / 1024, 264 / 768],
            "reference_status": "Published TextOCR transcripts corroborated by assistant visual inspection of original pixels; no human app-label review or approval.",
            "application_labels_reviewed": False},
        "predeclared_checks": {
            "positive_output": "A compiled, actually previewed draft on the original scene. Final preview frame texts, split only on whitespace without case correction or dictionary repair, contain exactly the four expected tokens once each. Line/reading grouping may vary. Returned text geometry mapped into original coordinates has centres within the evaluator-only display envelope. Branding, registration and other-bus text are excluded.",
            "adaptive_loop": "At least one executed vision action, its captured observation, then a materially different model-selected action justified by that observation. An already-correct first attempt is retained as a useful outcome but does not by itself satisfy the adaptive-trace criterion; do not force a failure or unnecessary retry.",
            "negative_output": "On degraded-only pixels, require supported uncertainty, a specific higher-quality-input request, or an honest bounded blocker if the destination cannot be recovered. No invented exact reference or unsupported draft_ready claim. Retain any genuinely correct unexpected reading as a result; do not relabel it a failure.",
            "counterfactual": "Use the same task prompt, frozen runtime/system prompt and model settings for both variants in isolated projects; compare the next actions against actual differing observations, not prose alone.",
            "side_effects": "No label review, independent-evaluation approval, deployment, events persisted/dispatched, installs, training or external effects.",
            "scope": "One static scene and one intentionally degraded derivative. No warehouse, production, distribution-level accuracy or independent-heldout generalization claim."},
        "prior_exposure_and_limitations": {
            "prior_work": "The same source image contributed five word crops to earlier reader-evaluation diagnostics, including SKI. This case is not a pristine independent reader-accuracy holdout.",
            "previous_word_crop_ids": [item["id"] for item in row["selected_crops"]],
            "pretraining_overlap": "Unknown", "sample_count": 1,
            "geometry_scope": "A crop learned for this fixed composition is a scene-specific draft, not detector-driven association or robust bus localization.",
            "planner_visibility": "Current A0 planner transport is text-only; file references are not evidence that it saw pixels. Image semantics must be supported by actual available observations or declared as a limitation."}}
    immutable(HERE / "manifest.json", (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode())
    print(json.dumps({"manifest": str(HERE / "manifest.json"), "inputs": inputs}, indent=2))


if __name__ == "__main__":
    main()
