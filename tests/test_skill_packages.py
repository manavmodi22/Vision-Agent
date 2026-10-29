"""Packaged guidance identity, selection, context bounds and authority boundary."""
from dataclasses import replace
from importlib.resources import files

import pytest
from pydantic import ValidationError

from agent.machine import Phase
from agent.skills import (
    catalog,
    load_skill,
    parse_skill,
    permitted_skill_tools,
    render_skills,
    select_skills,
)


def test_real_packages_have_versioned_complete_contracts_and_examples() -> None:
    skills = catalog()
    assert {skill.manifest.id for skill in skills} == {
        "authoring", "detection", "reading", "segmentation", "tracking", "alerting"}
    for skill in skills:
        assert skill.reference.id == skill.manifest.id
        assert skill.reference.version == "1.0.0"
        assert len(skill.reference.sha256) == 64
        assert skill.manifest.required_inputs and skill.manifest.validation_recipe
        assert skill.manifest.failure_modes and "## Examples" in skill.body


@pytest.mark.parametrize(("goal", "expected"), [
    ("Read package labels and show their codes", {"authoring", "reading"}),
    ("Count people inside lane A and save a crop", {"authoring", "detection", "alerting"}),
    ("Segment every carton with pixel-level masks", {"authoring", "segmentation"}),
    ("Track unique forklifts crossing the line", {"authoring", "tracking"}),
    ("Detect boxes and read their printed codes", {"authoring", "detection", "reading"}),
    ('Read text containing "tracking alert masks"', {"authoring", "reading"}),
    ("Read text containing 'tracking alert masks'", {"authoring", "reading"}),
])
def test_task_relevant_selection_does_not_load_irrelevant_capability_hints(goal: str, expected: set[str]) -> None:
    assert {item.reference.id for item in select_skills(goal)} == expected


def test_unknown_goal_is_guidance_selection_not_a_capability_grant() -> None:
    selected = select_skills("Segment the object")
    assert "segmentation" in {item.reference.id for item in selected}
    assert "segment" not in permitted_skill_tools(selected, Phase.PLAN, frozenset({"segment"}))


def test_content_and_metadata_changes_both_change_identity() -> None:
    raw = files("agent.skills").joinpath("packages", "reading", "SKILL.md").read_bytes()
    original = parse_skill(raw, "reading")
    changed_body = parse_skill(raw + b"\nAn additional validation requirement.\n", "reading")
    changed_version = parse_skill(raw.replace(b'"1.0.0"', b'"1.0.1"'), "reading")
    assert len({original.reference.sha256, changed_body.reference.sha256, changed_version.reference.sha256}) == 3
    assert changed_version.reference.version == "1.0.1"
    assert original.reference == load_skill("reading").reference


@pytest.mark.parametrize("identifier", ["../reading", "/tmp/SKILL.md", "https://example.com/SKILL.md", "unknown"])
def test_project_paths_and_remote_pages_cannot_be_loaded_as_skills(identifier: str) -> None:
    with pytest.raises(ValueError, match="registered"):
        load_skill(identifier)


def test_metadata_cannot_grant_a_tool_or_human_approval() -> None:
    skill = load_skill("reading")
    malicious = replace(skill, manifest=skill.manifest.model_copy(update={
        "allowed_tools": ("pipeline_deploy", "alerts_set", "pipeline_run", "blocks_list")
    }))
    assert permitted_skill_tools((malicious,), Phase.PLAN, frozenset({"blocks_list"})) == {"blocks_list"}
    assert not permitted_skill_tools((malicious,), Phase.DEPLOY, frozenset({"pipeline_deploy", "alerts_set"}))
    assert not permitted_skill_tools((malicious,), Phase.COMPILE, frozenset())


def test_wrong_identity_unknown_phase_and_oversized_documents_fail_closed() -> None:
    raw = files("agent.skills").joinpath("packages", "reading", "SKILL.md").read_bytes()
    with pytest.raises(ValueError, match="identity"):
        parse_skill(raw, "detection")
    with pytest.raises(ValueError, match="size budget"):
        parse_skill(raw + b"x" * 16000, "reading")
    with pytest.raises(ValueError):
        select_skills("Read codes", phase="approve-everything")
    with pytest.raises(ValidationError):
        parse_skill(raw.replace(b'version = "1.0.0"', b'version = "latest"'), "reading")


def test_prompt_is_bounded_and_contains_selected_version_references() -> None:
    chosen = select_skills("Read printed labels")
    text = render_skills(chosen)
    assert "reading@1.0.0" in text
    assert chosen[-1].reference.sha256 in text
    assert len(text) < 8000
    huge = replace(chosen[0], body="x" * 18001)
    with pytest.raises(ValueError, match="context budget"):
        render_skills((huge,))
