"""Small transport envelopes; engine data remains typed in spec.models."""

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class ToolModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalogResult(ToolModel):
    blocks: list[dict[str, JsonValue]]


class BlockSchemaResult(ToolModel):
    block: dict[str, JsonValue]


class ValidationResult(ToolModel):
    valid: bool
    errors: list[str] = Field(default_factory=list)


class ProjectResult(ToolModel):
    project: dict[str, JsonValue]


class FramesResult(ToolModel):
    paths: list[str]


class RecordsResult(ToolModel):
    records: list[dict[str, JsonValue]]


class DatasetContext(ToolModel):
    revision: int
    classes: list[str]
    image_count: int
    reviewed_count: int
    annotation_count: int
    text_region_count: int = 0
    expected_text_count: int = 0
    split_counts: dict[str, int]
    saved_zone_ids: list[str] = Field(default_factory=list)
    zones_confirmed: bool = False
    zone_origin: str = "unconfirmed"
