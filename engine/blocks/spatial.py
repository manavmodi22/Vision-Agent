"""Polygon containment and stable first-zone assignment."""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from spec.models import Detection, Zone


def inside_polygon(x: float, y: float, polygon: list[tuple[float, float]]) -> bool:
    inside = False
    for index, (ax, ay) in enumerate(polygon):
        bx, by = polygon[(index + 1) % len(polygon)]
        cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
        if abs(cross) <= 1e-10 and min(ax, bx) <= x <= max(ax, bx) and min(ay, by) <= y <= max(ay, by):
            return True
        if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
            inside = not inside
    return inside


def load_zones(value: str | list[Zone], project_root: Path) -> list[Zone]:
    if isinstance(value, list):
        zones = value
    else:
        path = (project_root / value).resolve()
        if not path.is_relative_to(project_root.resolve()):
            raise ValueError("Zone file must be inside the project")
        if not path.is_file():
            raise ValueError(f"Zone file does not exist: {value}. Draw or save zones first.")
        if path == (project_root / "zones/lanes.json").resolve():
            from engine.zones import read_zone_state

            if not read_zone_state(project_root).confirmed:
                raise ValueError("Region geometry is unconfirmed. Review or draw the actual regions and save them first.")
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict) or set(raw) != {"zones"}:
            raise ValueError("Zone file must contain only a 'zones' array")
        zones = TypeAdapter(list[Zone]).validate_python(raw["zones"])
    if not zones or len({z.id for z in zones}) != len(zones):
        raise ValueError("Zones must be nonempty with unique IDs")
    return zones


def assign_zones(detections: list[Detection], zones: list[Zone]) -> list[Detection]:
    results: list[Detection] = []
    for detection in detections:
        x = (detection.box[0] + detection.box[2]) / 2
        y = (detection.box[1] + detection.box[3]) / 2
        for zone in zones:
            if inside_polygon(x, y, zone.polygon):
                results.append(detection.model_copy(update={"zone": zone.id}))
                break
    return results
