"""One diagnostic decision, never an investigation action or acceptance result."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import sys
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True

import httpx  # noqa: E402
from openai import AsyncOpenAI, DefaultAsyncHttpxClient  # noqa: E402

from agent.graph_structure import ordered_nodes  # noqa: E402
from agent.investigation import (  # noqa: E402
    MAX_PROMPT_AND_OUTPUT_CHARS,
    PROMPT_TOKEN_MARGIN,
    SYSTEM,
    action_contracts,
    node_contracts,
    verify_prompt_budget,
    workflow_action_contracts,
)
from agent.planner import local_model_url  # noqa: E402
from engine.investigations.store import InvestigationRecord  # noqa: E402
from engine.runtime_identity import source_identity  # noqa: E402
from mcp_server import investigations as projection  # noqa: E402
from spec.investigation import NextAction, TaskState, WorkflowDecision  # noqa: E402

DEFAULT_LEDGER = ROOT / ".visionapp/a0-investigation/run-20261029T174252Z/workspace/projects/a895814b9a4d4284/investigations/b8356984efca48508eef49f3b543e6d7/task.json"


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def encoded(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, allow_nan=False).encode()


def save(folder: Path, name: str, value: Any) -> None:
    (folder / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def input_diff(before: Any, after: Any, path: str = "") -> list[dict[str, Any]]:
    """Exact recorded differences, never supplied as model instructions."""
    if before == after:
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        changes = []
        for key in sorted(before.keys() | after.keys()):
            child = path + "/" + key.replace("~", "~0").replace("/", "~1")
            if key not in after:
                changes.append({"op": "remove", "path": child, "before": before[key]})
            elif key not in before:
                changes.append({"op": "add", "path": child, "after": after[key]})
            else:
                changes.extend(input_diff(before[key], after[key], child))
        return changes
    return [{"op": "replace", "path": path, "before": before, "after": after}]


def sampling_options(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict) or not value:
        raise ValueError("Sampling override must be a nonempty JSON object")
    if set(value) - {"temperature", "top_p", "presence_penalty", "extra_body"}:
        raise ValueError("Only temperature, top_p, presence_penalty and extra_body sampler fields may change")
    bounds = {"temperature": (0, 2), "top_p": (0, 1), "presence_penalty": (-2, 2),
              "top_k": (0, 1000), "min_p": (0, 1), "repeat_penalty": (0, 4),
              "repeat_last_n": (-1, 16384), "seed": (-1, 4294967295)}
    extra = value.get("extra_body", {})
    if not isinstance(extra, dict) or set(extra) - {"top_k", "min_p", "repeat_penalty", "repeat_last_n", "seed"}:
        raise ValueError("extra_body accepts only bounded llama sampling fields, never model/prompt/template/tool overrides")
    for key, item in {**{k: v for k, v in value.items() if k != "extra_body"}, **extra}.items():
        low, high = bounds[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item) or not low <= item <= high:
            raise ValueError(f"Invalid {key}; expected a finite number from {low} to {high}")
        if key in {"top_k", "repeat_last_n", "seed"} and not isinstance(item, int):
            raise ValueError(f"{key} must be an integer")
    return value


class PrefixStore:
    """Only captured prefix reads exist; no filesystem service, reservations or writes."""
    def __init__(self, record: InvestigationRecord, call_index: int) -> None:
        self.selected = record.model_calls[call_index - 1]
        self.state = TaskState.model_validate(self.selected.context["context"]["state"])
        self.calls = record.model_calls[:call_index - 1]
        prior_ids = {call.id for call in self.calls}
        self.receipts = [item for item in record.actions if item.model_call_id in prior_ids]
        action_ids = {item.id for item in self.receipts}
        self.results = [item for item in record.observations if item.action_id in action_ids]
        if any(item.ended_at is None or item.ended_at > self.selected.started_at for item in self.receipts):
            raise ValueError("Action prefix is incomplete or includes a result after the selected call")
        if any(item.created_at > self.selected.started_at for item in self.results):
            raise ValueError("Observation prefix includes future evidence")
        if len(self.receipts) != self.state.budget.actions or self.state.budget.model_calls != call_index - 1:
            raise ValueError("Captured pre-call counters do not match the reconstructed prefix")
        if self.state.stage not in {"investigating", "workflow"} or self.state.revision != self.selected.state_revision:
            raise ValueError("Replay requires a captured investigation/workflow point with its exact revision")

    def get(self, *_: str) -> TaskState:
        return self.state.model_copy(deep=True)

    def observations(self, *_: str) -> list[Any]:
        return deepcopy(self.results)

    def actions(self, *_: str) -> list[Any]:
        return deepcopy(self.receipts)

    def model_calls(self, *_: str) -> list[Any]:
        return deepcopy(self.calls)


def schema_constraints(value: Any) -> Any:
    """Compare executable schema constraints without regenerating historical prose."""
    if isinstance(value, dict):
        return {key: schema_constraints(item) for key, item in value.items() if key not in {"title", "description"}}
    if isinstance(value, list):
        return [schema_constraints(item) for item in value]
    return value


def decision_type(prefix: PrefixStore) -> type[NextAction] | type[WorkflowDecision]:
    return WorkflowDecision if prefix.state.stage == "workflow" else NextAction


def known_workflow_revisions(prefix: PrefixStore) -> list[str]:
    """Only successful host preview receipts in the already bounded prefix."""
    return sorted({identifier for item in prefix.results
                   if item.result_type == "construct_workflow" and item.status == "completed"
                   and item.payload.get("validated") is True and item.payload.get("preview_success") is True
                   and isinstance(identifier := item.payload.get("workflow_revision_id"), str)
                   and len(identifier) == 32 and all(character in "0123456789abcdef" for character in identifier)})


def reconstruct(ledger: Path, call_index: int, mode: str,
                contracts: str = "captured") -> tuple[dict[str, Any], PrefixStore, dict[str, Any]]:
    record = InvestigationRecord.model_validate_json(ledger.read_bytes())
    if not 1 <= call_index <= len(record.model_calls):
        raise ValueError(f"Call must be from 1 to {len(record.model_calls)}")
    prefix = PrefixStore(record, call_index)
    captured = deepcopy(prefix.selected.context)
    original = captured["context"]
    schema = decision_type(prefix).model_json_schema()
    required = set(schema.get("required", [])) | {"type", "based_on_observation_ids"}
    schema["required"] = [key for key in schema["properties"] if key in required]
    if contracts == "captured" and schema_constraints(schema) != schema_constraints(captured["schema"]):
        raise ValueError("Decision schema constraints changed; use explicit --contracts current for a changed-input diagnostic")
    if captured.get("temperature") != 0 or not 1 <= captured.get("max_tokens", 0) <= 4096:
        raise ValueError("Expected captured temperature 0 and a bounded output allowance")
    if mode == "corrected":
        # Bootstrap is evidence from that exact point, not today's mutable media.
        # Avoid WorkspaceService initialization, SQLite writes, locks and pixel reads.
        with patch.object(projection, "development_media_summary", return_value=deepcopy(original["development_media"])):
            current = projection.investigation_context(prefix, prefix.state.project_id, prefix.state.id)
        stable = {key: deepcopy(original[key]) for key in ("action_contracts", "node_contracts", "planner_modality") if key in original}
        captured["context"] = {**stable, **{key: value for key, value in current.items() if key not in stable}}
        assert captured["context"]["state"] == original["state"]
    elif mode != "original":
        raise ValueError("Context must be original or corrected")
    if contracts == "current":
        from agent.investigation_grounding import DecisionGrounding

        context = captured["context"]
        # Historical indexes identify saved observations; only actual exposure
        # permits citation. Never promote the earlier-observation index here.
        context["citable_observation_ids"] = sorted(set(context["visible_observation_ids"]).union(
            identifier for call in prefix.calls for identifier in call.visible_observation_ids))
        context["known_workflow_revision_ids"] = known_workflow_revisions(prefix)
        stable = {"action_contracts": workflow_action_contracts() if prefix.state.stage == "workflow" else action_contracts()}
        if prefix.state.stage == "workflow":
            stable["node_contracts"] = node_contracts()
        if "planner_modality" in context:
            stable["planner_modality"] = context["planner_modality"]
        captured["context"] = {**stable, **{key: value for key, value in context.items()
                                          if key not in {"action_contracts", "node_contracts", "planner_modality"}}}
        captured["system"] = SYSTEM
        captured["schema"] = DecisionGrounding.from_context(captured["context"], prefix.state.revision).schema(schema)
    elif contracts != "captured":
        raise ValueError("Contracts must be captured or current")
    known = {item.id for item in prefix.results}
    if not set(captured["context"]["visible_observation_ids"]) <= known:
        raise ValueError("Reconstruction exposed observations outside the historical prefix")
    reference = {"historical_call_id": prefix.selected.id, "historical_response": prefix.selected.response,
                 "historical_error": prefix.selected.error,
                 "scope": "Historical output is a comparison reference, not ground truth and never included in the prompt."}
    return captured, prefix, reference


def omit_recent_purpose(context: dict[str, Any]) -> list[dict[str, Any]]:
    """Delete only this one optional prose field; record exact reversible edits."""
    changes = []
    for index, row in enumerate(context.get("recent_actions", [])):
        if "purpose" in row:
            changes.append({"op": "remove", "path": f"/recent_actions/{index}/purpose",
                            "removed_value": row.pop("purpose")})
    if not changes:
        raise ValueError("No recent action purposes were present; refusing an unchanged omission experiment")
    return changes


def validate_candidate(raw: Any, prefix: PrefixStore, context: dict[str, Any],
                       contracts: str = "captured") -> dict[str, Any]:
    try:
        if not isinstance(raw, dict) or "type" not in raw or "based_on_observation_ids" not in raw:
            raise ValueError("Response must explicitly supply type and based_on_observation_ids")
        decision = decision_type(prefix).model_validate(raw)
        if decision.state_revision != prefix.state.revision:
            raise ValueError("Candidate used a different state revision")
        known = {item.id for item in prefix.results}
        exposed = {identifier for call in prefix.calls for identifier in call.visible_observation_ids}
        exposed.update(context["visible_observation_ids"])
        if not set(decision.based_on_observation_ids) <= known & exposed:
            raise ValueError("Candidate cites unknown or never-exposed observations")
        references = set(getattr(decision.action, "evidence_ids", []))
        if decision.action.type == "inspect_observation":
            references.add(decision.action.observation_id)
        if not references <= known:
            raise ValueError("Candidate action references observations outside the captured prefix")
        if contracts == "current":
            from agent.investigation_grounding import DecisionGrounding

            DecisionGrounding.from_context(context, prefix.state.revision).validate(decision)
        result = {"shape_and_provenance_valid": True, "decision": decision.model_dump(mode="json"),
                  "authority_validated": False, "action_dispatched": False,
                  "scope": "Shape, revision and evidence references only; not task correctness, executable authorization or A0 success."}
        if isinstance(decision, WorkflowDecision):
            try:
                ordered_nodes(decision.action.graph)
                result["graph_structure_valid"] = True
            except ValueError as error:
                result.update(graph_structure_valid=False, graph_structure_error=str(error))
        return result
    except (TypeError, ValueError) as error:
        return {"shape_and_provenance_valid": False, "error": str(error), "action_dispatched": False}


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--call-number", "--call", dest="call", type=int, required=True, help="One-based captured model call in --ledger")
    parser.add_argument("--context", choices=("original", "corrected"), default="original")
    parser.add_argument("--contracts", choices=("captured", "current"), default="captured",
                        help="Captured preserves historical contracts; current explicitly regenerates prompt/schema/docs and grounding")
    parser.add_argument("--omit-recent-purpose", action="store_true", help="Diagnostic-only removal of purpose from recent_actions; all other context retained")
    parser.add_argument("--sampling-json", help="Explicit sampling-only JSON override; omitted preserves captured temperature 0")
    parser.add_argument("--model-url", default="http://127.0.0.1:1236/v1")
    parser.add_argument("--model", help="Defaults to the captured model alias")
    parser.add_argument("--model-receipt", type=Path, help="Optional saved artifact provenance; a declared reference, not proof of live server binding")
    parser.add_argument("--output-dir", type=Path, help="New output directory; never overwritten")
    parser.add_argument("--timeout", type=float, default=150, help="Request timeout, 1–150 seconds")
    parser.add_argument("--run", action="store_true", help="Explicitly permit exactly one model request; otherwise offline reconstruction only")
    args = parser.parse_args()
    try:
        args.sampling = sampling_options(args.sampling_json)
        args.model_url = local_model_url(args.model_url)
        if not math.isfinite(args.timeout) or not 1 <= args.timeout <= 150:
            raise ValueError("Timeout must be from 1 to 150 seconds")
        if args.call < 1:
            raise ValueError("Call index must be positive")
    except (ValueError, TypeError) as error:
        parser.error(str(error))
    return args


async def main() -> None:
    args = arguments()
    ledger = args.ledger.resolve(strict=True)
    ledger_hash = digest(ledger.read_bytes())
    source_before = source_identity(ROOT)
    captured, prefix, reference = reconstruct(ledger, args.call, args.context, args.contracts)
    context = captured["context"]
    unmodified_context_sha256 = digest(encoded(context))
    context_changes = omit_recent_purpose(context) if args.omit_recent_purpose else []
    sampling = {"temperature": captured["temperature"], **args.sampling}
    model_name = args.model or prefix.selected.model
    messages = [{"role": "system", "content": captured["system"]},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)}]
    if sum(len(item["content"]) for item in messages) + 4 * (captured["max_tokens"] + PROMPT_TOKEN_MARGIN) > MAX_PROMPT_AND_OUTPUT_CHARS:
        raise ValueError("Actual prompt plus output allowance exceeds the current bounded transport")
    request = {"model": model_name, "messages": messages, "max_tokens": captured["max_tokens"],
               "response_format": {"type": "json_schema", "json_schema": {
                   "name": "InvestigationDecision", "strict": True, "schema": captured["schema"]}}, **sampling}
    folder = (args.output_dir or ROOT / "artifacts/a0-investigation/next-action-replays" /
              (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + f"-call{args.call}-{args.context}-{uuid.uuid4().hex[:6]}")).resolve()
    protected_ledger_root = ledger.parents[2] if ledger.parent.parent.name == "investigations" else ledger.parent
    if folder.is_relative_to(protected_ledger_root) or any(folder.is_relative_to(ROOT / name) for name in ("agent", "engine", "spec", "mcp_server")):
        raise ValueError("Outputs cannot be written inside the source project or production packages")
    folder.mkdir(parents=True, exist_ok=False)
    save(folder, "request.json", request)
    save(folder, "reference.json", reference)
    changed_inputs = input_diff(prefix.selected.context, captured)
    save(folder, "input-diff.json", {"contracts": args.contracts, "context": args.context,
         "changed_input_diagnostic": args.contracts == "current", "changes": changed_inputs})
    save(folder, "context-diff.json", {"omit_recent_purpose": args.omit_recent_purpose,
         "before_sha256": unmodified_context_sha256, "after_sha256": digest(encoded(context)), "changes": context_changes})
    receipt = {"scope": "Diagnostic next-decision candidate only; no action dispatch, task mutation, user reply or A0 success claim.",
               "status": "prepared_offline", "run_requested": args.run, "ledger": str(ledger), "ledger_sha256": ledger_hash,
               "call_number": args.call, "call_id": prefix.selected.id, "context_mode": args.context,
               "decision_type": "workflow_decision" if prefix.state.stage == "workflow" else "next_action",
               "contracts_mode": args.contracts, "changed_input_diagnostic": args.contracts == "current",
               "changed_input_paths": [item["path"] for item in changed_inputs],
               "sampling_override_explicit": args.sampling_json is not None, "sampling": sampling,
               "omit_recent_purpose": args.omit_recent_purpose, "omitted_purpose_count": len(context_changes),
               "unmodified_context_sha256": unmodified_context_sha256,
               "captured_sampling": {"temperature": captured["temperature"]}, "model_url": args.model_url,
               "model": model_name, "captured_model": prefix.selected.model, "runner_sha256": digest(Path(__file__).read_bytes()),
               "source_before": source_before, "context_sha256": digest(encoded(context)),
               "historical_context_sha256": digest(encoded(prefix.selected.context["context"])),
               "historical_request_sha256": digest(encoded(prefix.selected.context)),
               "request_sha256": digest(encoded(request)), "schema_sha256": digest(encoded(captured["schema"])),
               "system_sha256": digest(captured["system"].encode()), "visible_observation_ids": context["visible_observation_ids"],
               "prefix_observations": [item.id for item in prefix.results],
               "context_budget": {"status": "not_checked_offline"},
               "reconstruction": ("Captured state/output allowance/bootstrap retained. Captured contracts retain exact historical system/schema/docs; "
                                  "current contracts explicitly regenerate them and ground references from actual prior exposure. "
                                  "Corrected context uses current history projection. All changes recorded in input-diff.json; optional purpose omission in context-diff.json.")}
    if args.model_receipt:
        receipt["declared_model_provenance"] = json.loads(args.model_receipt.read_text())
        receipt["live_weight_binding_verified"] = False
    save(folder, "receipt.json", receipt)
    try:
        if args.run:
            async with httpx.AsyncClient(timeout=4, trust_env=False) as client:
                receipt["context_budget"] = await verify_prompt_budget(client, args.model_url, model_name, messages, captured["max_tokens"])
                for key, url in (("backend_models", args.model_url + "/models"),
                                 ("backend_properties", args.model_url.removesuffix("/v1") + "/props")):
                    response = await client.get(url)
                    receipt[key] = response.json() if response.is_success else {"http_status": response.status_code}
            if source_identity(ROOT) != source_before or digest(ledger.read_bytes()) != ledger_hash:
                raise ValueError("Source or ledger changed before dispatch; no model request sent")
            async def capture_wire(request: httpx.Request) -> None:
                if request.url.path.endswith("/chat/completions"):
                    body = await request.aread()
                    save(folder, "wire-request.json", json.loads(body))
                    receipt["wire_request_sha256"] = digest(body)
                    receipt["status"] = "model_request_sent"
                    save(folder, "receipt.json", receipt)
            async def capture_response(response: httpx.Response) -> None:
                if response.request.url.path.endswith("/chat/completions"):
                    body = await response.aread()
                    (folder / "wire-response.body").write_bytes(body)
                    receipt["wire_response_sha256"] = digest(body)
                    receipt["wire_response_http_status"] = response.status_code
            timeout = httpx.Timeout(args.timeout, connect=4, write=15, pool=4)
            started = monotonic()
            async with AsyncOpenAI(base_url=args.model_url, api_key="local", max_retries=0, timeout=timeout,
                    http_client=DefaultAsyncHttpxClient(trust_env=False, timeout=timeout,
                        event_hooks={"request": [capture_wire], "response": [capture_response]})) as model:
                response = await model.chat.completions.create(**request)
            raw = response.model_dump(mode="json")
            save(folder, "response.json", raw)
            try:
                decision = json.loads(response.choices[0].message.content or "")
                result = validate_candidate(decision, prefix, context, args.contracts)
            except (ValueError, IndexError) as error:
                result = {"shape_and_provenance_valid": False, "error": str(error), "action_dispatched": False}
            save(folder, "candidate.json", result)
            receipt.update(status="diagnostic_response_captured", elapsed_s=monotonic() - started)
    except Exception as error:
        receipt.update(status="diagnostic_failed", error=f"{type(error).__name__}: {error}")
        raise
    finally:
        receipt["source_after"] = source_identity(ROOT)
        receipt["ledger_sha256_after"] = digest(ledger.read_bytes())
        receipt["source_unchanged"] = receipt["source_after"] == source_before
        receipt["ledger_unchanged"] = receipt["ledger_sha256_after"] == ledger_hash
        receipt["comparison_inputs_unchanged"] = receipt["source_unchanged"] and receipt["ledger_unchanged"]
        save(folder, "receipt.json", receipt)
        print(json.dumps({"output_dir": str(folder), "status": receipt["status"],
                          "model_request_sent": (folder / "wire-request.json").exists(),
                          "ledger_unchanged": receipt["ledger_unchanged"]}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
