"""Human review handoff contracts; none confer inference or deployment authority."""
from typing import Literal

from pydantic import Field

from spec.inference import SHA256
from spec.investigation import RecordId
from spec.models import Contract


class PrepareHandoff(Contract):
    expected_revision: int = Field(strict=True, ge=0)
    workflow_revision_id: RecordId
    preview_observation_id: RecordId


class AcceptHandoff(Contract):
    proposal_id: RecordId
    proposal_hash: SHA256
    client_request_id: str = Field(min_length=1, max_length=128)
    acknowledge_source_rebind: Literal[True]


class AbortHandoff(Contract):
    proposal_id: RecordId
    proposal_hash: SHA256
    acknowledge_discard: Literal[True]


class HandoffProposal(Contract):
    schema_version: Literal["a0.handoff.1"] = "a0.handoff.1"
    id: RecordId
    project_id: str
    task_id: RecordId
    task_revision: int
    workflow_revision_id: RecordId
    preview_observation_id: RecordId
    proposal_hash: SHA256
    origin_task_status: Literal["draft_ready", "inconclusive"]
    origin_stop_reason: str | None = None
    original_spec_hash: SHA256
    candidate_spec_hash: SHA256
    source_before: str
    source_after: Literal["media"] = "media"
    original_media_count: int
    project_media_count: int
    candidate_name: str
    metric: str
    target: float
    limitations: list[str]
    created_at: str


class HandoffReceipt(Contract):
    schema_version: Literal["a0.handoff.1"] = "a0.handoff.1"
    id: RecordId
    project_id: str
    task_id: RecordId
    workflow_revision_id: RecordId
    preview_observation_id: RecordId
    proposal_id: RecordId
    proposal_hash: SHA256
    client_request_id: str
    build_id: RecordId
    candidate_index: Literal[0] = 0
    original_spec_hash: SHA256
    candidate_spec_hash: SHA256
    created_at: str
    origin_task_status: Literal["draft_ready", "inconclusive"]
    origin_stop_reason: str | None = None
