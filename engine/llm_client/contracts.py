"""Typed local VLM request, preflight and evidence contracts."""
from __future__ import annotations

from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator

from spec.models import Contract
from spec.models import JudgementEvidence as VLMJudgement


class VLMConfig(Contract):
    base_url: str = "http://127.0.0.1:1235/v1"
    model: str = Field(default="visionapp-vlm", min_length=1, max_length=200)
    timeout_s: float = Field(default=45, gt=0, le=120)
    max_tokens: int = Field(default=512, ge=64, le=2048)
    max_image_side: int = Field(default=768, ge=64, le=1536)
    retries: int = Field(default=1, ge=0, le=2)
    model_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("base_url")
    @classmethod
    def local_only(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("VLM URL must be a loopback HTTP endpoint")
        if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.rstrip("/").endswith("/v1"):
            raise ValueError("VLM URL must end with /v1 and contain no credentials, query or fragment")
        return value.rstrip("/")


class VLMDecision(Contract):
    label: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=1, max_length=1500)
    confidence: float = Field(ge=0, le=1)


class VLMPreflight(Contract):
    model: str
    base_url: str
    vision_supported: bool
    identity_hash: str
    identity_scope: Literal["local_weights_verified", "server_metadata_only"]
    weights_sha256: str | None = None
    model_license: str = "Not verified; consult the model card"
    warnings: list[str] = Field(default_factory=list)


class VLMError(ValueError):
    """Unavailable, incompatible or invalid model output; never a fallback result."""

__all__ = ["VLMConfig", "VLMDecision", "VLMPreflight", "VLMJudgement", "VLMError"]
