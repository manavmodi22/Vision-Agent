"""Diagnostic query records are separate from a project's build state."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent.state_contracts import AgentOperation
from spec.evidence import EvidenceAnswer, EvidenceDecision


class EvidenceOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: AgentOperation
    decision: EvidenceDecision | None = None
    answer: EvidenceAnswer | None = None


class EvidenceReplay(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query_id: str
    dry_run: Literal[True] = True
    effects_executed: Literal[False] = False
    reproduced: bool
    errors: list[str]
    answer: EvidenceAnswer | None
