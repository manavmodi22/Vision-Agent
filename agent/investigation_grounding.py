"""Ground model-output references in explicit host context, never evidence prose."""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

from pydantic import JsonValue

from spec.investigation import (
    BuilderDecision,
    ConstructWorkflow,
    Finish,
    InspectObservation,
    PrepareWorkflow,
)

_RECORD_ID = re.compile(r"[0-9a-f]{32}\Z")


def _ids(values: JsonValue | None) -> set[str]:
    return {item for item in values if isinstance(item, str) and _RECORD_ID.fullmatch(item)} if isinstance(values, list) else set()


@dataclass(frozen=True)
class DecisionGrounding:
    revision: int
    observation_ids: tuple[str, ...]
    citable_ids: tuple[str, ...]
    workflow_revision_ids: tuple[str, ...]
    selected_workflow_revision: str | None
    preview_observation_id: str | None

    @classmethod
    def from_context(cls, context: dict[str, JsonValue], revision: int) -> DecisionGrounding:
        # The host restores actual prior exposure from its captured model calls.
        # An earlier-observation index entry alone does not grant citation rights.
        citable = _ids(context.get("visible_observation_ids")) | _ids(context.get("citable_observation_ids"))
        identifiers = set(citable)
        # These are host-owned record/index headers. IDs inside readings, errors,
        # descriptors, model prose or nested payloads cannot expand either set.
        for field in ("observations", "earlier_observations"):
            rows = context.get(field, [])
            if not isinstance(rows, list):
                continue
            for row in rows:
                identifier = row.get("id") if isinstance(row, dict) else None
                if isinstance(identifier, str) and _RECORD_ID.fullmatch(identifier):
                    identifiers.add(identifier)
        workflow_revisions = _ids(context.get("known_workflow_revision_ids"))
        state = context.get("state")
        selected, preview = None, None
        # Selection is host state, not a claim in a projected payload or model
        # prose. Require a current, known preview whose observation was exposed.
        if isinstance(state, dict) and type(state.get("revision")) is int and state["revision"] == revision:
            candidate, evidence = state.get("selected_workflow_revision"), state.get("preview_observation_id")
            if (isinstance(candidate, str) and _RECORD_ID.fullmatch(candidate) and candidate in workflow_revisions
                    and isinstance(evidence, str) and _RECORD_ID.fullmatch(evidence) and evidence in citable):
                selected, preview = candidate, evidence
        return cls(revision=revision, observation_ids=tuple(sorted(identifiers)), citable_ids=tuple(sorted(citable)),
                   workflow_revision_ids=tuple(sorted(workflow_revisions)),
                   selected_workflow_revision=selected, preview_observation_id=preview)

    def schema(self, source: dict[str, Any]) -> dict[str, Any]:
        """Specialize this response only; public DTOs retain their wire contract."""
        result = copy.deepcopy(source)
        result["properties"]["state_revision"]["const"] = self.revision
        self._array(result["properties"]["based_on_observation_ids"], self.citable_ids)
        definitions = result.get("$defs", {})
        for name in ("PrepareWorkflow", "Finish", "ConstructWorkflow"):
            if name in definitions:
                self._array(definitions[name]["properties"]["evidence_ids"], self.observation_ids)
        for definition, field in (("ConstructWorkflow", "parent_revision_id"), ("Finish", "workflow_revision_id")):
            if definition in definitions:
                self._nullable_reference(definitions[definition]["properties"][field], self.workflow_revision_ids)
        if "Finish" in definitions:
            # Keep the backend grammar simple: this outcome-dependent contract
            # is checked below before dispatch even if descriptions are ignored.
            requirement = (
                "For outcome draft_ready, workflow_revision_id must equal the current selected workflow revision "
                "and evidence_ids must include its exposed preview observation. "
                "These requirements do not apply to blocked or inconclusive. "
            )
            if self.selected_workflow_revision is not None:
                requirement += (f"Current selected revision: {self.selected_workflow_revision}; "
                                f"required preview evidence ID: {self.preview_observation_id}.")
            else:
                requirement += "No current known selected revision with exposed preview evidence is available; draft_ready is not valid."
            previous = definitions["Finish"].get("description", "")
            definitions["Finish"]["description"] = (previous + " " + requirement).strip()
        if "InspectObservation" in definitions:
            if self.observation_ids:
                definitions["InspectObservation"]["properties"]["observation_id"]["enum"] = list(self.observation_ids)
            else:
                # There is no legal inspect target yet. Empty enums can produce
                # invalid grammars in local backends; omit only this impossible
                # variant, leaving every independent action choice available.
                reference = "#/$defs/InspectObservation"
                action = result["properties"]["action"]
                action["oneOf"] = [item for item in action["oneOf"] if item.get("$ref") != reference]
                action["discriminator"]["mapping"].pop("inspect_observation", None)
                definitions.pop("InspectObservation")
        return result

    @staticmethod
    def _array(field: dict[str, Any], identifiers: tuple[str, ...]) -> None:
        if identifiers:
            field["items"]["enum"] = list(identifiers)
        else:
            # [] remains legal, while any invented array member is impossible.
            field["maxItems"] = 0

    @staticmethod
    def _nullable_reference(field: dict[str, Any], identifiers: tuple[str, ...]) -> None:
        if identifiers:
            for variant in field["anyOf"]:
                if variant.get("type") == "string":
                    variant["enum"] = list(identifiers)
        else:
            # No previewed revision exists. Null is the only valid reference;
            # never substitute a task/action/observation ID or empty sentinel.
            field.pop("anyOf", None)
            field["type"] = "null"

    def validate(self, decision: BuilderDecision) -> None:
        """Backends ignoring grammar get feedback, not corrected references.

        This is an output-contract check, not execution authority. The durable
        host still checks ownership, actual exposure, stage and current revision.
        """
        if decision.state_revision != self.revision:
            raise ValueError(f"state_revision must equal the supplied current revision {self.revision}")
        if set(decision.based_on_observation_ids) - set(self.citable_ids):
            raise ValueError("based_on_observation_ids must use exact currently or previously exposed IDs from context; no action was executed")
        references: set[str] = set()
        if isinstance(decision.action, InspectObservation):
            references.add(decision.action.observation_id)
        elif isinstance(decision.action, (PrepareWorkflow, Finish, ConstructWorkflow)):
            references.update(decision.action.evidence_ids)
        if references - set(self.observation_ids):
            raise ValueError("Observation references must use exact known IDs supplied in the model context; no action was executed")
        workflow_revision = None
        if isinstance(decision.action, ConstructWorkflow):
            workflow_revision = decision.action.parent_revision_id
        elif isinstance(decision.action, Finish):
            workflow_revision = decision.action.workflow_revision_id
        if workflow_revision is not None and workflow_revision not in self.workflow_revision_ids:
            raise ValueError("Workflow revision references must use an exact owned validated preview ID from known_workflow_revision_ids, or null; no action was executed")
        if isinstance(decision.action, Finish) and decision.action.outcome == "draft_ready":
            if self.selected_workflow_revision is None or self.preview_observation_id is None:
                raise ValueError("draft_ready requires a current known selected workflow revision with exposed preview evidence in host state; no action was executed")
            if decision.action.workflow_revision_id != self.selected_workflow_revision:
                raise ValueError(f"draft_ready must select the current workflow revision {self.selected_workflow_revision}; no action was executed")
            if self.preview_observation_id not in decision.action.evidence_ids:
                raise ValueError(f"draft_ready evidence_ids must include the selected workflow preview observation {self.preview_observation_id}; no action was executed")
