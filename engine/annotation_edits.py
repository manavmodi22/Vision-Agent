"""Validated annotation updates shared by image, bulk and import save paths."""
from pathlib import Path

from spec.models import Annotation, EvalDataset


def normalize_annotation_edits(root: Path, previous: EvalDataset, incoming: EvalDataset) -> EvalDataset:
    originals = {(root / row.image_path).resolve(): row for row in previous.annotations}
    validated = []
    for incoming_row in incoming.annotations:
        original = originals.get((root / incoming_row.image_path).resolve())
        if original is not None and (original.text_regions or original.expected_text_source != "manual"):
            if not {"text_regions", "expected_text_source"}.issubset(incoming_row.model_fields_set):
                raise ValueError("This image has text-region labels. Update the editor before saving; omitted fields cannot erase them.")
        # model_copy and Python mutation bypass Pydantic validation, unlike HTTP input.
        row = Annotation.model_validate(incoming_row.model_dump(mode="json"))
        if original is not None:
            old_regions = {region.id: region for region in original.text_regions}
            for region in row.text_regions:
                old = old_regions.get(region.id)
                if old is not None and old.seed is not None and region.seed != old.seed:
                    raise ValueError("Original model-seed provenance cannot be changed or removed from an existing text region")
            if row.text_regions != original.text_regions or row.expected_text_source != original.expected_text_source:
                row.reviewed = False
        validated.append(row)
    return EvalDataset(id=incoming.id, annotations=validated)
