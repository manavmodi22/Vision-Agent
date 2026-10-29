"""Local detector adapters with explicit availability and licensing."""
from PIL import Image

from engine.models.fixture import detect_fixture
from engine.models.manager import ModelUnavailable, list_models, validate_model
from spec.models import Detection


def detect(image: Image.Image, model: str, classes: list[str], min_conf: float) -> list[Detection]:
    validate_model(model)
    if model == "fixture-color-v1":
        return detect_fixture(image, classes, min_conf)
    if model == "owlv2-base-patch16":
        from engine.models.owlv2 import detect_owlv2
        return detect_owlv2(image, classes, min_conf)
    if model == "rtdetr-v2-r18":
        from engine.models.rtdetr import detect_rtdetr
        return detect_rtdetr(image, model, classes, min_conf)
    if model.startswith("local-"):
        from engine.models.local_manifest import read_manifest
        from engine.models.manager import model_directory
        if read_manifest(model, model_directory()).backend == "rtdetr-v2-r18":
            from engine.models.rtdetr import detect_rtdetr
            return detect_rtdetr(image, model, classes, min_conf)
        from engine.models.ssdlite import detect_ssdlite
        return detect_ssdlite(image, model, classes, min_conf)
    raise ModelUnavailable(f"No detector backend is implemented for '{model}'")


__all__ = ["detect", "list_models", "validate_model", "ModelUnavailable"]
