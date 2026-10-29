"""Narrow synchronous A0 tools; the coordinator owns decisions and receipts."""
from __future__ import annotations

import asyncio
import json
import re
import time
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, JsonValue

from engine.adapters.contracts import BarcodeRequest, DetectionRequest, OcrRequest
from engine.adapters.identity import adapter_id
from engine.blocks.registry import REGISTRY
from engine.capabilities import build_catalog, validate_experiment_capabilities
from engine.investigations.media import DevelopmentMedia
from engine.investigations.probes import (
    JSON_OBJECT,
    Artifacts,
    compact_item,
    result_items,
    run_probe,
)
from engine.models.artifacts import canonical_hash
from engine.models.manager import trained_classes
from engine.service import WorkspaceService
from spec.capabilities import CapabilityManifest
from spec.inference import InferenceResult
from spec.investigation import (
    DiscoverCapabilities,
    InspectCapability,
    InspectMedia,
    InspectObservation,
    InvestigationAction,
    RunProbe,
)
from spec.models import RunResult

if TYPE_CHECKING:
    from engine.investigations.store import InvestigationStore


class ToolOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    status: Literal["completed", "failed"] = "completed"
    payload: dict[str, JsonValue]
    error: dict[str, JsonValue] | str | None = None


def _stable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _stable(item) for key, item in value.items()
                if key not in {"checked_at", "observed_at", "generated_at"}}
    return [_stable(item) for item in value] if isinstance(value, list) else value


def _probe_contract(capability: CapabilityManifest) -> tuple[list[str], bool]:
    """Describe adapter prerequisites without loading models or claiming measured readiness."""
    tasks: list[str] = []
    if capability.kind == "model":
        try:
            adapter_id(capability.id.removeprefix("model."))
            tasks = [task for task in capability.task_types if task in {"detection", "ocr", "barcode"}]
        except ValueError:
            pass
    eligible = bool(tasks and capability.implemented and capability.installation_ready
                    and capability.availability == "installed")
    return tasks, eligible


def _execution_role(capability: CapabilityManifest, probe_tasks: list[str]) -> str:
    if capability.kind == "model":
        return "typed_adapter_model" if probe_tasks else "catalogue_model"
    if capability.id.startswith("block.") and capability.id.removeprefix("block.") in REGISTRY:
        return "graph_block"
    return "catalogue_tool"


def descriptor(capability: CapabilityManifest) -> dict[str, JsonValue]:
    """One actual descriptor plus the exact executable adapter contracts."""
    payload = capability.model_dump(mode="json")
    probe_tasks, probe_eligible = _probe_contract(capability)
    limitations = ["Provisional observations do not establish accuracy, review, or deployment approval."]
    if capability.kind == "model":
        identifier = capability.id.removeprefix("model.")
        if probe_tasks:
            schemas: dict[str, type[BaseModel]] = {"detection": DetectionRequest, "ocr": OcrRequest, "barcode": BarcodeRequest}
            requests = []
            for task in probe_tasks:
                schema = schemas[task].model_json_schema()
                schema["properties"]["model_id"] = {"type": "string", "const": identifier}
                requests.append(schema)
            payload["probe_request_schemas"] = requests
            payload["probe_output_schema"] = InferenceResult.model_json_schema()
            if "detection" in probe_tasks:
                payload["class_vocabulary"] = trained_classes(identifier)
                payload["vocabulary_kind"] = "open" if payload["class_vocabulary"] is None else "closed"
                if identifier == "fixture-color-v1":
                    from engine.models.fixture import PALETTE
                    payload["class_vocabulary"] = list(PALETTE)
                    payload["vocabulary_kind"] = "synthetic_fixture"
        else:
            limitations.append("This capability has no A0 typed adapter probe. Configured VLM judgement is deferred.")
    else:
        limitations.append("Catalogue visibility does not authorize arbitrary MCP calls; only investigation actions execute here.")
    payload["probe_eligible"] = probe_eligible
    payload["probe_tasks"] = probe_tasks
    payload["limitations"] = limitations
    payload["descriptor_hash"] = canonical_hash(_stable(payload))
    return JSON_OBJECT.validate_python(payload)


def descriptor_model_view(full: dict[str, JsonValue]) -> dict[str, JsonValue]:
    """Keep exact execution arguments and vocabulary visible without result-schema repetition."""
    keys = ("id", "descriptor_hash", "probe_eligible", "probe_tasks", "probe_request_schemas",
            "class_vocabulary", "vocabulary_kind", "availability", "installation_ready",
            "version", "limitations")
    result = {key: full[key] for key in keys if key in full}
    readiness = full.get("readiness")
    if isinstance(readiness, dict):
        result["readiness"] = {key: readiness[key] for key in ("state", "reason", "evidence_scope") if key in readiness}
    provenance = full.get("provenance")
    if isinstance(provenance, dict):
        result["provenance"] = {key: provenance[key] for key in ("scope", "revision", "source_urls", "hashes") if key in provenance}
    hardware = full.get("hardware")
    if isinstance(hardware, dict):
        result["hardware"] = {key: hardware[key] for key in ("platforms", "accelerators", "required_packages") if key in hardware}
    result["output_summary"] = "Actual detections/readings, normalized geometry, input-to-source transform, identity, timing, warnings; full result available as a saved artifact."
    return result


def _page(rows: list[Any], cursor: str | None, limit: int, scope: str) -> tuple[list[Any], dict[str, JsonValue]]:
    fingerprint = canonical_hash({"scope": scope, "rows": rows})[:16]
    offset = 0
    if cursor is not None:
        match = re.fullmatch(r"([0-9a-f]{16}):(\d{1,6})", cursor)
        if not match or match[1] != fingerprint:
            raise ValueError("Cursor is invalid or the discovered inventory changed; restart inspection")
        offset = int(match[2])
        if offset > len(rows):
            raise ValueError("Cursor exceeds the available observations")
    selected = rows[offset:offset + limit]
    more = offset + len(selected) < len(rows)
    return selected, {"total_items": len(rows), "returned_items": len(selected), "truncated": more,
                      "next_cursor": f"{fingerprint}:{offset + len(selected)}" if more else None}


class InvestigationTools:
    """Call from a worker thread/process; run_probe needs the host process deadline."""
    def __init__(self, service: WorkspaceService, store: InvestigationStore) -> None:
        self.service, self.store = service, store

    def _catalog(self) -> list[CapabilityManifest]:
        return asyncio.run(build_catalog(self.service)).capabilities

    def _descriptor(self, capability_id: str) -> dict[str, JsonValue]:
        matches = [item for item in self._catalog() if item.id == capability_id]
        if len(matches) != 1:
            raise ValueError("Capability ID is not registered on this host")
        return descriptor(matches[0])

    @staticmethod
    def _fixture_policy(capability_id: str, fixture_project: bool | None) -> dict[str, JsonValue]:
        required = capability_id == "model.fixture-color-v1"
        allowed = not required or fixture_project is True
        return {"allowed": allowed, "requires_fixture_project": required, "fixture_project": fixture_project,
                "reason": None if allowed else "Synthetic fixture models cannot process nonfixture project media; project.synthetic alone does not grant fixture-adapter permission."}

    def execute(self, project_id: str, task_id: str, action_id: str,
                action: InvestigationAction) -> ToolOutcome:
        started = time.perf_counter()
        # The store verifies project/task ownership. Actions must be typed; there
        # is deliberately no arbitrary tool name, endpoint, code, or path input.
        artifacts = Artifacts(self.store.root(project_id, task_id))
        media = DevelopmentMedia(self.service, project_id)
        try:
            state = self.store.get(project_id, task_id)
            receipt = next((row for row in self.store.actions(project_id, task_id) if row.id == action_id), None)
            if (state.status != "running" or state.pending_action_id != action_id or receipt is None
                    or receipt.status != "reserved" or receipt.action != action):
                raise ValueError("Tool execution requires the current reserved action with exact typed arguments")
            if isinstance(action, DiscoverCapabilities):
                payload = self._discover(action, project_id)
            elif isinstance(action, InspectCapability):
                full = self._descriptor(action.capability_id)
                policy = self._fixture_policy(action.capability_id, self.service.get_project(project_id).fixture)
                view = descriptor_model_view(full)
                view.update(probe_eligible=bool(full["probe_eligible"] and policy["allowed"]), project_eligibility=policy)
                payload = {"executed": False, "descriptor": full, "model_view": view, "project_eligibility": policy,
                           "total_items": 1, "returned_items": 1, "truncated": False}
            elif isinstance(action, InspectMedia):
                payload = self._media(media, artifacts, action)
            elif isinstance(action, RunProbe):
                self._authorize_probe(project_id, task_id, action)
                payload = run_probe(media, action_id, action, artifacts)
            elif isinstance(action, InspectObservation):
                payload = self._observation(project_id, task_id, media, artifacts, action)
            elif action.type == "ask_user":
                payload = {"executed": False, "question": action.question}
            elif action.type == "finish":
                payload = {"executed": False, "outcome": action.outcome, "summary": action.summary,
                           "evidence_ids": list(action.evidence_ids)}
            else:
                raise ValueError("Workflow preparation is handled by the investigation coordinator")
            payload = JSON_OBJECT.validate_python(payload)
            error = payload.get("error")
            return ToolOutcome(status="failed" if error else "completed", payload=payload,
                               error=JSON_OBJECT.validate_python(error) if error else None)
        except Exception as error:
            detail: dict[str, JsonValue] = {"code": "tool_rejected", "message": str(error)[:1000],
                "retryable": False, "failed_stage": "authorization_or_preparation"}
            return ToolOutcome(status="failed", payload={"executed": False, "error": detail,
                "timing": {"total_ms": (time.perf_counter() - started) * 1000}}, error=detail)

    def _discover(self, action: DiscoverCapabilities, project_id: str | None = None) -> dict[str, JsonValue]:
        fixture_project = self.service.get_project(project_id).fixture if project_id is not None else None
        stop_words = frozenset("a an and are as at be by for from in is it of on or that the this to was were with".split())
        def tokens(value: str) -> set[str]:
            return {word for word in re.findall(r"[^\W_]+", value.casefold())
                    if len(word) > 1 and word not in stop_words}
        def fields(item: CapabilityManifest) -> list[tuple[set[str], int]]:
            return [(tokens(item.id), 3), (tokens(item.name), 3),
                    (tokens(" ".join(item.task_types)), 4), (tokens(item.description), 1)]
        def compact(item: CapabilityManifest) -> dict[str, Any]:
            probe_tasks, eligible = _probe_contract(item)
            policy = self._fixture_policy(item.id, fixture_project)
            row = {"capability_id": item.id, "name": item.name, "description": item.description[:400],
                    "kind": item.kind, "task_types": item.task_types, "availability": item.availability,
                    "readiness": item.readiness.state, "installation_ready": item.installation_ready,
                    "probe_tasks": probe_tasks, "probe_eligible": bool(eligible and policy["allowed"]),
                    "execution_role": _execution_role(item, probe_tasks)}
            if item.id == "model.fixture-color-v1":
                row["project_eligibility"] = policy
            return row
        terms = tokens(action.query)
        inventory = not action.query.strip()
        catalog = self._catalog()
        kinds = sorted({item.kind for item in catalog})
        task_types = sorted({task for item in catalog for task in item.task_types})
        invalid_task = action.task_type is not None and action.task_type not in task_types
        diagnostics: list[dict[str, Any]] = []
        if invalid_task:
            diagnostics.append({"code": "unknown_filter_value", "filter": "task_type", "requested": action.task_type,
                                "message": "No registered capability uses this task type; choose a returned task type or omit the filter."})
        rows: list[dict[str, Any]] = []
        for item in catalog:
            if ((action.kind is not None and item.kind != action.kind)
                    or (action.task_type is not None and action.task_type not in item.task_types)):
                continue
            metadata = fields(item)
            matched = set().union(*(terms & words for words, _weight in metadata))
            if not inventory and not matched:
                continue
            rows.append({**compact(item), "matched_terms": sorted(matched), "unmatched_terms": sorted(terms - matched),
                "match_score": sum(len(terms & words) * weight for words, weight in metadata)})
        rows.sort(key=lambda row: (-int(row["match_score"]), str(row["capability_id"])))
        scope = canonical_hash({"terms": sorted(terms), "inventory": inventory,
                                "kind": action.kind, "task_type": action.task_type})
        selected, counts = _page(rows, action.cursor, action.limit, scope)
        suggestions: list[dict[str, Any]] = []
        ignored_filters: list[str] = []
        if not rows:
            pool = [item for item in catalog if (action.kind is None or item.kind == action.kind)
                    and (action.task_type is None or invalid_task or action.task_type in item.task_types)]
            if invalid_task:
                ignored_filters.append("task_type")
            if not pool and action.task_type is not None:
                ignored_filters.append("task_type")
                pool = [item for item in catalog if action.kind is None or item.kind == action.kind]
                diagnostics.append({"code": "empty_filter_combination", "message": "No registered capabilities match the requested filter combination."})
            for item in pool:
                matches: list[dict[str, Any]] = []
                score = 0.0
                exact_terms = set().union(*(terms & words for words, _weight in fields(item)))
                for words, weight in fields(item):
                    for term in sorted(terms):
                        choices = []
                        for word in sorted(words):
                            ratio = SequenceMatcher(None, term, word).ratio()
                            similarity = (1.0 if term == word else .75 if min(len(term), len(word)) >= 4 and
                                          (term in word or word in term) else ratio * .5 if min(len(term), len(word)) >= 4 and ratio >= .72 else 0.0)
                            if similarity:
                                choices.append((similarity, word))
                        if choices:
                            similarity, word = sorted(choices, key=lambda match: (-match[0], match[1]))[0]
                            score += similarity * weight
                            pair = {"query_term": term, "metadata_term": word}
                            if pair not in matches:
                                matches.append(pair)
                suggestions.append({**compact(item), "description": item.description[:160],
                    "matched_terms": sorted(exact_terms), "unmatched_terms": sorted(terms - exact_terms),
                    "suggestion_type": "approximate_metadata" if score else "inventory",
                    "suggestion_score": round(score, 3), "related_terms": matches[:4], "exact_query_match": False})
            suggestions.sort(key=lambda row: (-float(row["suggestion_score"]), not row["installation_ready"],
                                              row["availability"] != "installed", str(row["capability_id"])))
            if suggestions and suggestions[0]["suggestion_score"]:
                suggestions = [row for row in suggestions if row["suggestion_score"]]
            suggestions = suggestions[:min(3, action.limit)]
        return JSON_OBJECT.validate_python({"executed": False, "items": selected, **counts,
                "query": action.query, "active_filters": {"kind": action.kind, "task_type": action.task_type},
                "query_terms": sorted(terms), "available_kinds": kinds, "available_task_types": task_types,
                "filter_diagnostics": diagnostics, "suggestions": suggestions, "suggestion_ignored_filters": ignored_filters,
                "suggestion_semantics": "Suggestions are labelled catalogue alternatives, not exact query results or execution recommendations; related terms use generic substring/character similarity. Inventory suggestions have no measured query relevance.",
                "search_semantics": "Empty query lists inventory. Otherwise match any casefolded alphanumeric metadata token; punctuation, one-character tokens and common function words are ignored. Rank weighted ID/name/task/description matches, then capability ID. Explicit kind/task filters remain exact.",
                "warnings": ["Discovery metadata grants no execution or installation authority."]})

    def _media(self, media: DevelopmentMedia, artifacts: Artifacts, action: InspectMedia) -> dict[str, JsonValue]:
        identifiers = action.media_ids or media.identifiers()
        selected, counts = _page(identifiers, getattr(action, "cursor", None), action.limit, "media")
        rows: list[JsonValue] = []
        references: list[JsonValue] = []
        for identifier in selected:
            source = media.resolve(identifier)
            row = JSON_OBJECT.validate_python(source.metadata())
            if action.representation == "pixels":
                media.expose(source, source.image, "investigation_image_inspection")
                reference = artifacts.image(source.image)
                references.append(reference)
                row["image_artifact"] = reference
            rows.append(row)
        return {"executed": False, "items": rows, "input_refs": rows, "artifact_refs": references,
                "pixels_visible_to_planner": False, **counts,
                "warnings": ["pixels_not_visible_to_planner: this planner receives structured text; artifact references are not image attachments."]}

    def _authorize_probe(self, project_id: str, task_id: str, action: RunProbe) -> None:
        if not action.capability_id.startswith("model."):
            raise ValueError(f"run_probe requires an inspected model.* capability, not a graph block or catalogue tool; "
                f"received capability_id={action.capability_id!r}. Inspect an eligible model capability and copy "
                "request.model_id from its probe_request_schemas; discovery does not supply an inspected descriptor hash.")
        if action.capability_id != "model." + action.request.model_id:
            raise ValueError(f"Probe capability_id={action.capability_id!r} does not match request.model_id={action.request.model_id!r}. "
                "capability_id must equal 'model.' + request.model_id. Copy the exact request.model_id from the "
                "inspected capability's probe_request_schemas, not the catalogue capability ID.")
        policy = self._fixture_policy(action.capability_id, self.service.get_project(project_id).fixture)
        if not policy["allowed"]:
            raise ValueError(str(policy["reason"]))
        inspected = False
        for row in self.store.observations(project_id, task_id):
            saved = row.payload.get("descriptor")
            if (row.result_type == "inspect_capability" and row.status == "completed" and isinstance(saved, dict)
                    and saved.get("id") == action.capability_id
                    and saved.get("descriptor_hash") == action.inspected_descriptor_hash):
                inspected = True
        if not inspected:
            raise ValueError("Inspect this capability in the current investigation before probing it")
        current = self._descriptor(action.capability_id)
        if current["descriptor_hash"] != action.inspected_descriptor_hash:
            raise ValueError("Capability descriptor changed; inspect it again before execution")
        tasks = current["probe_tasks"]
        if not current["probe_eligible"] or not isinstance(tasks, list) or action.request.task not in tasks:
            raise ValueError("Capability is not eligible for this A0 adapter probe")
        validate_experiment_capabilities(self.service, [action.capability_id])

    def _observation(self, project_id: str, task_id: str, media: DevelopmentMedia,
                     artifacts: Artifacts, action: InspectObservation) -> dict[str, JsonValue]:
        saved = self.store.get_observation(project_id, task_id, action.observation_id)
        payload = saved.payload
        inputs = payload.get("input_refs", [])
        if not isinstance(inputs, list):
            raise ValueError("Observation input references are invalid")
        for reference in inputs:
            if not isinstance(reference, dict):
                raise ValueError("Observation input references are invalid")
            media.resolve(str(reference["media_id"]), str(reference["source_sha256"]))
        public_inputs = [{key: value for key, value in reference.items() if key not in {"source_path", "preview_path"}}
                         for reference in inputs if isinstance(reference, dict)]
        common: dict[str, Any] = {"executed": False, "observation_id": saved.id, "source_result_type": saved.result_type,
                  "source_status": saved.status, "input_refs": public_inputs,
                  **{key: payload[key] for key in ("workflow_revision_id", "spec_hash", "preview_spec_hash") if key in payload}}
        if action.view == "error":
            return JSON_OBJECT.validate_python({**common, "observed_error": saved.error})
        if action.view in {"image", "overlay"}:
            references = []
            reference = payload.get(action.view + "_artifact")
            if isinstance(reference, dict):
                references.append(reference)
            elif action.view == "image":
                items = payload.get("items", [])
                if isinstance(items, list):
                    for row in items:
                        ref = row.get("image_artifact") if isinstance(row, dict) else None
                        if isinstance(ref, dict):
                            references.append(ref)
            if not references:
                raise ValueError("Observation has no requested image artifact")
            selected, counts = _page(references, action.cursor, action.limit, saved.id + action.view)
            for ref in selected:
                artifacts.read(ref)
            return JSON_OBJECT.validate_python({**common, "artifact_refs": selected, **counts,
                    "pixels_visible_to_planner": False,
                    "warnings": ["pixels_not_visible_to_planner: an artifact reference is not an image attachment."]})
        result_ref = payload.get("result_artifact")
        refs: list[dict[str, Any]] = []
        scope = saved.id + action.view
        if isinstance(result_ref, dict):
            record = json.loads(artifacts.read(result_ref))
            rows = record["items"]
            refs = [result_ref]
            scope = str(result_ref["sha256"]) + action.view
        elif isinstance(payload.get("preview_artifact"), dict):
            rows, preview_ref = self._workflow_items(payload, artifacts, saved.action_id)
            refs = [preview_ref]
        else:
            rows = self._saved_items(payload)
        if action.view == "geometry":
            keys = {"item_id", "record_type", "frame_index", "media_id", "block_id", "identity_scope", "identity_hash",
                    "input_to_source", "box", "polygon", "source_box", "source_polygon"}
            rows = [{key: value for key, value in row.items() if key in keys} for row in rows
                    if any(row.get(key) is not None for key in ("box", "polygon", "source_box", "source_polygon"))]
        selected, counts = _page(rows, action.cursor, action.limit, scope)
        metadata_keys = ("search_semantics", "suggestion_semantics", "suggestion_ignored_filters", "available_kinds",
                         "available_task_types", "filter_diagnostics", "query", "active_filters", "query_terms",
                         "limitations", "validated", "preview_success")
        metadata = {key: payload[key] for key in metadata_keys if key in payload}
        if "items" in payload and not isinstance(result_ref, dict):
            metadata.update(source_total_items=payload.get("total_items"), source_next_cursor=payload.get("next_cursor"),
                            source_truncated=payload.get("truncated"))
        return JSON_OBJECT.validate_python({**common, "items": [compact_item(row) for row in selected],
                "artifact_refs": refs, **counts, **metadata})

    @staticmethod
    def _saved_items(payload: dict[str, JsonValue]) -> list[dict[str, Any]]:
        rows = payload.get("items")
        if isinstance(rows, list):
            result = [dict(row) if isinstance(row, dict) else {"value": row} for row in rows]
            suggestions = payload.get("suggestions", [])
            if isinstance(suggestions, list):
                result.extend({"record_type": "catalog_suggestion", **row} for row in suggestions if isinstance(row, dict))
            return result
        descriptor_view = payload.get("model_view", payload.get("descriptor"))
        if isinstance(descriptor_view, dict):
            return [{"record_type": "capability_descriptor", **descriptor_view}]
        return [{"record_type": "saved_field", "field": key, "value": value} for key, value in payload.items()
                if key not in {"input_refs", "artifact_refs", "executed"}]

    @staticmethod
    def _workflow_items(payload: dict[str, JsonValue], artifacts: Artifacts,
                        action_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        reference = payload["preview_artifact"]
        if not isinstance(reference, dict):
            raise ValueError("Workflow preview artifact is invalid")
        preview = RunResult.model_validate_json(artifacts.read(reference))
        if isinstance(payload.get("preview"), dict) and preview.model_dump(mode="json") != payload["preview"]:
            raise ValueError("Saved preview differs from its immutable result artifact")
        if payload.get("spec_hash") != payload.get("preview_spec_hash"):
            raise ValueError("Saved workflow and preview identity differ")
        inputs = payload.get("input_refs")
        if not isinstance(inputs, list) or len(inputs) != len(preview.frames):
            raise ValueError("Workflow preview source references are incomplete")
        rows: list[dict[str, Any]] = []
        for index, (frame, source) in enumerate(zip(preview.frames, inputs, strict=True)):
            if (not isinstance(source, dict) or frame.source_image_sha256 != source.get("source_sha256")
                    or frame.image_path != source.get("preview_path")):
                raise ValueError("Workflow preview source differs from its saved input reference")
            common = {"frame_index": index, "media_id": source["media_id"]}
            def add(kind: str, value: dict[str, Any], context: dict[str, Any] = common, frame_index: int = index) -> None:
                rows.append({**context, "item_id": f"{action_id}:frame-{frame_index}:{len(rows)}", "record_type": kind, **value})
            add("frame_summary", {"timestamp_s": frame.timestamp_s, "elapsed_ms": frame.elapsed_ms,
                "detection_count": len(frame.detections), "text_count": len(frame.texts),
                "inference_count": len(frame.inferences), "comparison_count": len(frame.comparisons), "event_count": len(frame.events)})
            for name, count in frame.counts.items():
                add("frame_count", {"name": name, "count": count})
            for detection in frame.detections:
                add("frame_detection", {**detection.model_dump(mode="json"), "source_box": detection.box})
            for text in frame.texts:
                add("frame_text", {"text": text})
            for comparison in frame.comparisons:
                value = comparison.model_dump(mode="json", exclude={"observed"})
                add("text_comparison", {**value, "observed_count": len(comparison.observed)})
                for text in comparison.observed:
                    add("comparison_observation", {"block_id": comparison.block_id, "text": text})
            for event in frame.events:
                add("simulated_event", {"event": event, "persisted_or_dispatched": False})
            for judgement in frame.judgements:
                add("model_judgement", judgement.model_dump(mode="json"))
            for inference in frame.inferences:
                result = inference.result
                node = {"block_id": inference.block_id, "input_to_source": list(inference.input_to_frame),
                        "identity_hash": result.identity.identity_hash, "identity_scope": result.identity.identity_scope}
                add("inference_summary", {**node, "model_id": result.identity.model_id, "task": result.task,
                    "input_size": list(result.input_size), "input_pixels_sha256": result.input_pixels_sha256,
                    "timing": result.timing.model_dump(mode="json"), "warnings": result.warnings,
                    "detection_count": len(result.detections), "reading_count": len(result.readings)})
                for item in result_items(result, action_id + ":" + str(index) + ":" + inference.block_id, inference.input_to_frame):
                    add("inference_detection" if result.task == "detection" else "inference_reading", {**node, **item})
        return rows, reference
