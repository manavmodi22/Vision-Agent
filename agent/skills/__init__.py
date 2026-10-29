"""Trusted packaged Markdown playbooks. Code, not Markdown, grants authority."""
from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from importlib.resources import files

from agent.machine import TOOLS, Phase
from spec.skills import SkillManifest, SkillReference

_PACKAGES = ("authoring", "detection", "reading", "segmentation", "tracking", "alerting")
_MAX_BYTES = 16000
_MAX_CONTEXT = 18000


@dataclass(frozen=True)
class LoadedSkill:
    manifest: SkillManifest
    body: str
    reference: SkillReference


def parse_skill(raw: bytes, expected_id: str) -> LoadedSkill:
    """Parse bounded TOML and Markdown data without evaluating code."""
    if len(raw) > _MAX_BYTES:
        raise ValueError("Packaged skill exceeds its size budget")
    text = raw.decode("utf-8")
    if not text.startswith("+++\n") or "\n+++\n" not in text[4:]:
        raise ValueError("A skill needs TOML metadata between +++ delimiters")
    header, body = text[4:].split("\n+++\n", 1)
    manifest = SkillManifest.model_validate(tomllib.loads(header))
    if manifest.id != expected_id:
        raise ValueError("Skill package identity does not match its registered name")
    if not body.strip() or "## Examples" not in body:
        raise ValueError("A skill needs guidance and examples")
    if any(phase not in {item.value for item in Phase} for phase in manifest.phases):
        raise ValueError("Skill declares an unknown orchestration phase")
    return LoadedSkill(manifest, body.strip(), SkillReference(
        id=manifest.id, version=manifest.version, sha256=hashlib.sha256(raw).hexdigest()))


def load_skill(identifier: str) -> LoadedSkill:
    if identifier not in _PACKAGES:
        raise ValueError("Only registered application skill packages can be loaded")
    raw = files(__package__).joinpath("packages", identifier, "SKILL.md").read_bytes()
    return parse_skill(raw, identifier)


def catalog() -> tuple[LoadedSkill, ...]:
    return tuple(load_skill(identifier) for identifier in _PACKAGES)


def select_skills(goal: str, use_case: str = "custom", phase: str = "plan",
                  task_types: tuple[str, ...] = ()) -> tuple[LoadedSkill, ...]:
    """Select relevant guidance; selection never enables an adapter or tool."""
    Phase(phase)
    tasks = set(task_types)
    unquoted = re.sub(r'"[^"\n]*"|“[^”\n]*”|(?<!\w)\x27[^\x27\n]*\x27', " ", goal.lower())
    reading = bool(re.search(r"\b(?:read|reading|ocr|barcodes?|printed|sku|text recognition)\b", unquoted))
    segmentation = bool(re.search(r"\b(?:segment(?:ation)?|masks?|pixel[- ]level|outlines?)\b", unquoted))
    tracking = bool(re.search(r"\b(?:track(?:ing)?|dwell|line[- ]cross(?:ing)?|trajector(?:y|ies))\b", unquoted))
    if reading or use_case == "labels":
        tasks.add("reading")
    if segmentation:
        tasks.add("segmentation")
    if tracking:
        tasks.add("tracking")
    detection = bool(re.search(r"\b(?:detect(?:ion)?|count(?:ing)?|bounding\s+boxes)\b", unquoted))
    if detection or use_case in {"pallets", "damage"} or (not tasks and not reading):
        tasks.add("detection")
    if re.search(r"\b(?:alerts?|events?|email|webhook|mqtt|notifications?|save (?:a )?crop)\b", unquoted):
        tasks.add("alerting")
    aliases = {"ocr": "reading", "barcode": "reading", "instance_segmentation": "segmentation",
               "object_detection": "detection", "counting": "detection"}
    tasks |= {aliases.get(task, task) for task in tasks}
    selected = tuple(skill for skill in catalog() if phase in skill.manifest.phases
                     and (skill.manifest.id == "authoring" or tasks.intersection(skill.manifest.task_types)))
    render_skills(selected)
    return selected


def render_skills(skills: tuple[LoadedSkill, ...]) -> str:
    text = "\n\n".join(
        f"Application playbook: {skill.manifest.title} ({skill.reference.id}@{skill.reference.version}; sha256 {skill.reference.sha256})\n"
        f"Required inputs: {'; '.join(skill.manifest.required_inputs)}\n"
        f"Validation: {'; '.join(skill.manifest.validation_recipe)}\n"
        f"Failure modes: {'; '.join(skill.manifest.failure_modes)}\n{skill.body}"
        for skill in skills)
    if len(text) > _MAX_CONTEXT:
        raise ValueError("Selected playbooks exceed the model context budget")
    return text


def permitted_skill_tools(skills: tuple[LoadedSkill, ...], phase: Phase,
                          granted: frozenset[str]) -> frozenset[str]:
    """Guidance may narrow an existing code grant; it cannot expand one."""
    suggested = {tool for skill in skills if phase.value in skill.manifest.phases
                 for tool in skill.manifest.allowed_tools}
    return TOOLS[phase].intersection(granted, suggested)


def for_task(use_case: str) -> str:
    """Compatibility for callers until they supply the actual goal and phase."""
    return render_skills(select_skills("", use_case))
