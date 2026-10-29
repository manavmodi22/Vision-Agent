"""Versioned packaged playbook references; guidance cannot confer authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SkillReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SkillManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    format: Literal["visionapp.skill.v1"]
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    title: str = Field(min_length=1, max_length=120)
    selection_rule: str = Field(min_length=1, max_length=500)
    task_types: tuple[str, ...] = Field(min_length=1)
    phases: tuple[str, ...] = Field(min_length=1)
    required_inputs: tuple[str, ...] = Field(min_length=1)
    allowed_tools: tuple[str, ...]
    output_artifacts: tuple[str, ...] = Field(min_length=1)
    validation_recipe: tuple[str, ...] = Field(min_length=1)
    failure_modes: tuple[str, ...] = Field(min_length=1)
