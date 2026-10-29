"""Read catalog prerequisites; never load learned models or download weights.

Catalog discovery retains its tiny CPU synthetic-adapter self-test.
"""
import hashlib
import json
from typing import Literal

from engine.capabilities.models import model_catalog
from engine.models.fixture import PALETTE
from engine.models.manager import list_models, trained_classes
from engine.platform.model_provenance import default_exclusion, provenance
from engine.platform.model_request import explicit_model_ids, request_hash
from engine.service import WorkspaceService
from spec.planning import BlockedModelOption, PlanningModelOption, PlanningOptions, TaskType


def options_digest(options: PlanningOptions) -> str:
    payload = options.model_dump(mode="json", exclude={"snapshot_id"})
    if options.schema_version == "0.1":
        for field in ("experimental_models", "explicit_model_ids", "request_hash"):
            payload.pop(field)
        for option in payload["eligible_models"]:
            for field in ("training_provenance", "selection_basis", "selection_reason"):
                option.pop(field)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def planning_options(service: WorkspaceService, project_id: str, detection_constraint: str | None = None,
                     *, request: str = "") -> PlanningOptions:
    registered = [str(item["id"]) for item in list_models()]
    return _project_options(service, project_id, detection_constraint, explicit_model_ids(request, registered), request_hash(request))


def _project_options(service: WorkspaceService, project_id: str, detection_constraint: str | None,
                     requested: list[str], authorization_hash: str | None) -> PlanningOptions:
    project = service.get_project(project_id)
    if detection_constraint is not None and (detection_constraint != "fixture-color-v1" or not project.fixture):
        raise ValueError("Only an explicitly synthetic project may constrain detection to the fixture adapter")
    eligible: list[PlanningModelOption] = []
    blocked: list[BlockedModelOption] = []
    experiments: list[PlanningModelOption] = []
    backends = {str(item["id"]): str(item.get("backend", "unknown")) for item in list_models()}
    for capability in model_catalog():
        model_id = capability.id.removeprefix("model.")
        reason = None
        synthetic = model_id == "fixture-color-v1"
        reading = model_id == "apple-vision"
        if (not capability.implemented or capability.availability != "installed" or not capability.installation_ready
                or capability.readiness.state not in {"ready", "unchecked"}):
            reason = capability.readiness.reason
        elif synthetic and not project.fixture:
            reason = "Synthetic fixture models cannot process real project media"
        elif detection_constraint and not reading and model_id != detection_constraint:
            reason = "Excluded by the explicit synthetic detection constraint"
        if reason:
            blocked.append(BlockedModelOption(capability_id=capability.id, reason=reason))
            continue
        try:
            classes = list(PALETTE) if synthetic else [] if reading else trained_classes(model_id)
            facts = provenance(model_id)
        except (OSError, ValueError) as error:
            blocked.append(BlockedModelOption(capability_id=capability.id, reason=str(error)))
            continue
        if classes == [] and not reading:
            blocked.append(BlockedModelOption(capability_id=capability.id, reason="Closed model has no verified class vocabulary"))
            continue
        tasks: list[TaskType] = ["ocr", "barcode"] if reading else ["detection"]
        # Model metadata already names a registered backend; model IDs never become paths or code.
        adapter = "apple-vision" if reading else "fixture-color-v1" if synthetic else (
            "owlv2" if model_id == "owlv2-base-patch16" else backends.get(model_id, "unknown"))
        if adapter not in {"apple-vision", "fixture-color-v1", "owlv2", "rtdetr-v2-r18", "ssdlite320"}:
            blocked.append(BlockedModelOption(capability_id=capability.id, reason="No compatible registered adapter contract"))
            continue
        exclusion = default_exclusion(facts)
        selection: Literal["explicit_experiment", "requires_explicit_request", "default"] = "explicit_experiment" if model_id in requested else "requires_explicit_request" if exclusion else "default"
        option = PlanningModelOption(capability_id=capability.id, model_id=model_id, adapter_id=adapter,
            task_types=tasks, output_contract="texts/v1" if reading else "detections/v1",
            vocabulary="not_applicable" if reading else "open" if classes is None else "closed",
            supported_classes=classes or [], synthetic=synthetic,
            readiness="ready" if capability.callable else "unchecked", provenance_hashes=capability.provenance.hashes,
            version=capability.version, training_provenance=facts, selection_basis=selection,
            selection_reason=exclusion if exclusion else "Compatible recorded registration; quality still requires project evaluation.",
            limitations=["Synthetic software-check adapter; no real-world quality claim."] if synthetic
            else ["Prerequisites permit a bounded experiment, not a quality claim.", "No scored evaluation report is attached to this option; a dataset hash is not a score.",
                  "Training facts are recorded provenance; scene independence is not established here."])
        if exclusion and model_id not in requested:
            experiments.append(option)
            blocked.append(BlockedModelOption(capability_id=capability.id, reason=exclusion))
        else:
            eligible.append(option)
    options = PlanningOptions(schema_version="0.2", snapshot_id="", project_id=project_id, fixture_source=project.fixture,
        detection_constraint=detection_constraint, eligible_models=sorted(eligible, key=lambda item: item.capability_id),
        blocked_options=sorted(blocked, key=lambda item: item.capability_id),
        experimental_models=sorted(experiments, key=lambda item: item.capability_id),
        explicit_model_ids=requested, request_hash=authorization_hash)
    options.snapshot_id = options_digest(options)
    return options


def validate_current_options(service: WorkspaceService, saved: PlanningOptions, selected_ids: list[str]) -> None:
    if options_digest(saved) != saved.snapshot_id:
        raise ValueError("The saved planning-options hash is invalid")
    current = _project_options(service, saved.project_id, saved.detection_constraint, saved.explicit_model_ids, saved.request_hash)
    before = {item.capability_id: item for item in saved.eligible_models}
    after = {item.capability_id: item for item in current.eligible_models}
    for identifier in selected_ids:
        excluded = {"training_provenance", "selection_basis", "selection_reason"} if saved.schema_version == "0.1" else set()
        if (identifier not in before or identifier not in after
                or before[identifier].model_dump(exclude=excluded) != after[identifier].model_dump(exclude=excluded)):
            raise ValueError(f"Selected capability {identifier} changed or became unavailable; plan again against current options")
