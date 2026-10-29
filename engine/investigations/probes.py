"""Actual adapter probes and immutable, bounded evidence artifacts."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from pydantic import JsonValue, TypeAdapter

from engine.adapters.identity import resolve_execution_identity
from engine.adapters.registry import run_inference
from engine.investigations.media import DevelopmentMedia
from engine.models.artifacts import canonical_hash
from spec.inference import InferenceResult
from spec.investigation import RunProbe

JSON_OBJECT = TypeAdapter(dict[str, JsonValue])


class Artifacts:
    def __init__(self, task_root: Path) -> None:
        self.root = task_root / "artifacts"

    def write(self, data: bytes, mime: str) -> dict[str, JsonValue]:
        if len(data) > 64 * 1024 * 1024:
            raise ValueError("Investigation artifact exceeds the 64 MiB limit")
        suffix = {"application/json": ".json", "image/png": ".png"}[mime]
        digest = hashlib.sha256(data).hexdigest()
        identifier = digest + suffix
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / identifier
        temporary = self.root / ("." + uuid.uuid4().hex + ".tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != data:
                    raise ValueError("Existing evidence artifact was modified") from None
        finally:
            temporary.unlink(missing_ok=True)
        return {"artifact_id": identifier, "sha256": digest, "mime_type": mime, "bytes": len(data)}

    def image(self, pixels: Image.Image) -> dict[str, JsonValue]:
        output = io.BytesIO()
        pixels.save(output, format="PNG")
        return self.write(output.getvalue(), "image/png")

    def read(self, reference: dict[str, Any]) -> bytes:
        identifier = reference.get("artifact_id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{64}\.(json|png)", identifier):
            raise ValueError("Invalid owned artifact identifier")
        path = self.root / identifier
        if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
            raise ValueError("Invalid owned artifact")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != reference.get("sha256"):
            raise ValueError("Evidence artifact content changed")
        return data


def transformed(pixels: Image.Image, action: RunProbe) -> tuple[Image.Image, tuple[float, float, float, float]]:
    image = pixels.copy()
    mapping = (0.0, 0.0, 1.0, 1.0)
    for operation in action.transforms:
        if operation.type == "resize":
            if operation.width * operation.height > 40_000_000:
                raise ValueError("Resized input exceeds the 40 megapixel limit")
            image = image.resize((operation.width, operation.height))
        else:
            x0, y0, x1, y1 = operation.box
            width, height = image.size
            left, top, right, bottom = int(x0 * width), int(y0 * height), int(x1 * width), int(y1 * height)
            if right <= left or bottom <= top:
                raise ValueError("Crop does not contain a complete input pixel")
            ox, oy, sx, sy = mapping
            mapping = (ox + left / width * sx, oy + top / height * sy,
                       (right - left) / width * sx, (bottom - top) / height * sy)
            image = image.crop((left, top, right, bottom))
    return image, mapping


def result_items(result: InferenceResult, action_id: str, mapping: tuple[float, float, float, float]) -> list[dict[str, JsonValue]]:
    rows = []
    ox, oy, sx, sy = mapping
    for index, item in enumerate([*result.detections, *result.readings]):
        row = item.model_dump(mode="json")
        box = item.box
        row.update(item_id=f"{action_id}:{index}", identity_scope="frame_local_observation",
                   source_box=[ox + box[0] * sx, oy + box[1] * sy,
                               ox + box[2] * sx, oy + box[3] * sy] if box else None,
                   source_polygon=[[ox + x * sx, oy + y * sy] for x, y in item.polygon] if item.polygon else None)
        rows.append(JSON_OBJECT.validate_python(row))
    return rows


def compact_item(row: dict[str, JsonValue]) -> dict[str, JsonValue]:
    result = dict(row)
    text = result.get("text")
    if isinstance(text, str) and len(text) > 2048:
        result.update(text=text[:2048], text_truncated=True, text_total_characters=len(text))
    return result


def run_probe(media: DevelopmentMedia, action_id: str, action: RunProbe, artifacts: Artifacts) -> dict[str, JsonValue]:
    started = time.perf_counter()
    source = media.resolve(action.media_id, action.source_sha256)
    pixels, mapping = transformed(source.image, action)
    identity = resolve_execution_identity(action.request)
    # Exposure is durable before handing pixels to the actual adapter, including
    # executions that later fail or whose owned worker is killed by the host.
    media.expose(source, pixels, "investigation_probe")
    input_ref = JSON_OBJECT.validate_python(source.metadata())
    image_ref = artifacts.image(pixels)
    base: dict[str, JsonValue] = {"executed": False, "input_refs": [input_ref],
        "artifact_refs": [image_ref], "image_artifact": image_ref, "input_to_source": list(mapping),
        "transforms": [step.model_dump(mode="json") for step in action.transforms],
        "request": action.request.model_dump(mode="json"), "identity_refs": [identity.model_dump(mode="json")]}
    try:
        base["executed"] = True
        base["execution_status"] = "adapter_invoked"
        result = run_inference(pixels, action.request, expected_identity_hash=identity.identity_hash)
    except Exception as error:
        base.update(total_items=0, returned_items=0, truncated=False, next_cursor=None,
                    timing={"total_ms": (time.perf_counter() - started) * 1000},
                    error={"code": "adapter_failed", "message": str(error)[:1000],
                           "retryable": False, "failed_stage": "inference"})
        return base
    try:
        media.resolve(source.media_id, source.source_sha256)
    except Exception as error:
        return {**base, "execution_status": "completed_result_discarded", "error": {
            "code": "input_changed", "message": str(error)[:1000], "retryable": False,
            "failed_stage": "input_revalidation"},
            "timing": {"total_ms": (time.perf_counter() - started) * 1000}}
    base["execution_status"] = "completed"
    try:
        return _save_result(result, base, pixels, mapping, action_id, artifacts, started)
    except Exception as error:
        return {**base, "error": {"code": "artifact_failed", "message": str(error)[:1000],
                "retryable": False, "failed_stage": "evidence_persistence"},
                "timing": {"total_ms": (time.perf_counter() - started) * 1000}}


def _save_result(result: InferenceResult, base: dict[str, JsonValue], pixels: Image.Image,
                 mapping: tuple[float, float, float, float], action_id: str,
                 artifacts: Artifacts, started: float) -> dict[str, JsonValue]:
    rows = result_items(result, action_id, mapping)
    record = {**base, "result": result.model_dump(mode="json"), "items": rows}
    result_ref = artifacts.write(json.dumps(record, sort_keys=True, separators=(",", ":")).encode(), "application/json")
    overlay = pixels.copy()
    draw = ImageDraw.Draw(overlay)
    for row in [*result.detections, *result.readings]:
        if row.box:
            x0, y0, x1, y1 = row.box
            draw.rectangle((x0 * overlay.width, y0 * overlay.height, x1 * overlay.width, y1 * overlay.height), outline="#00d9ff", width=2)
    overlay_ref = artifacts.image(overlay)
    return {**base, "result_artifact": result_ref, "overlay_artifact": overlay_ref,
        "artifact_refs": [result_ref, base["image_artifact"], overlay_ref], "items": [compact_item(row) for row in rows[:20]],
        "total_items": len(rows), "returned_items": min(len(rows), 20), "truncated": len(rows) > 20,
        "next_cursor": canonical_hash({"scope": str(result_ref["sha256"]) + "values", "rows": rows})[:16] + ":20" if len(rows) > 20 else None,
        "warnings": list(result.warnings),
        "input_size": list(result.input_size), "input_pixels_sha256": result.input_pixels_sha256,
        "timing": {"total_ms": (time.perf_counter() - started) * 1000, "adapter": result.timing.model_dump(mode="json")}}
