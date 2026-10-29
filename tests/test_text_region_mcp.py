"""Actual MCP transport sees annotation progress without reserved-label leakage."""
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from PIL import Image

from engine.eval.protocol import read_configuration, save_configuration
from engine.service import WorkspaceService
from spec.evaluation import EvaluationConfigurationUpdate, EvidenceAssignment, EvidencePolicy
from spec.models import Annotation


async def test_region_progress_is_visible_without_reserved_ground_truth(tmp_path: Path) -> None:
    inputs = tmp_path / "images"
    inputs.mkdir()
    for index in range(2):
        Image.new("RGB", (100, 80), (index * 50, 30, 100)).save(inputs / f"frame-{index}.png")
    service = WorkspaceService(tmp_path / "workspace")
    project = service.create_project("MCP text region software test")
    service.import_media(project.id, [str(inputs)])
    dataset = service.annotations(project.id)
    for index, row in enumerate(dataset.annotations):
        value = row.model_dump(mode="json")
        value.update(text_regions=[{"id": f"region-{index}",
            "polygon": [[.1, .2], [.8, .2], [.8, .5], [.1, .5]],
            "transcript": "VISIBLE" if index == 0 else "PRIVATE-HOLDOUT"}], expected_text_source="regions")
        dataset.annotations[index] = Annotation.model_validate(value)
    service.save_annotations(project.id, dataset)
    root = service.root(project.id)
    config = read_configuration(root, dataset)
    save_configuration(root, dataset, EvaluationConfigurationUpdate(expected_revision=config.revision,
        assignments=[EvidenceAssignment(image_path=row.image_path, split="acceptance" if index else "validation",
            scene_group=f"separate-{index}") for index, row in enumerate(config.images)], policy=EvidencePolicy()))
    before = (root / "evaluation/usage.json").read_bytes()
    parameters = StdioServerParameters(command=sys.executable,
        args=["-m", "mcp_server", "--data-dir", str(service.repository.root)])
    async with stdio_client(parameters) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            result = await session.call_tool("dataset_context", {"project_id": project.id})
    assert not result.isError and result.structuredContent is not None
    assert result.structuredContent["image_count"] == 1
    assert result.structuredContent["annotation_count"] == 0
    assert result.structuredContent["text_region_count"] == 1
    assert result.structuredContent["expected_text_count"] == 1
    assert "PRIVATE-HOLDOUT" not in str(result)
    assert (root / "evaluation/usage.json").read_bytes() == before
