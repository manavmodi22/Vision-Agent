"""Training safety/registration contracts; optimizer is isolated from heavy CV."""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from engine.train.validation import validate_training_data
from spec.models import Annotation, Detection, EvalDataset


def reviewed_splits(root: Path) -> tuple[EvalDataset, EvalDataset]:
    annotations = []
    for index in range(4):
        path = root / f"sample-{index}.png"
        Image.new("RGB", (32, 32), (index * 30 + 20, 55, 80)).save(path)
        annotations.append(Annotation(image_path=str(path), reviewed=True,
            detections=[Detection(label="person", confidence=1, box=[0.1, 0.1, 0.5, 0.8])]))
    return EvalDataset(id="train", annotations=annotations[:2]), EvalDataset(id="holdout", annotations=annotations[2:])


def test_training_requires_reviewed_disjoint_images(tmp_path: Path) -> None:
    training, evaluation = reviewed_splits(tmp_path)
    assert validate_training_data(training, evaluation, tmp_path) == ["person"]
    evaluation.annotations[0].image_path = training.annotations[0].image_path
    with pytest.raises(ValueError, match="leakage"):
        validate_training_data(training, evaluation, tmp_path)


def test_renamed_duplicate_cannot_leak_into_holdout(tmp_path: Path) -> None:
    training, evaluation = reviewed_splits(tmp_path)
    destination = Path(evaluation.annotations[0].image_path)
    destination.write_bytes(Path(training.annotations[0].image_path).read_bytes())
    with pytest.raises(ValueError, match="leakage"):
        validate_training_data(training, evaluation, tmp_path)


def test_unreviewed_labels_and_rectangle_demo_rejected(tmp_path: Path) -> None:
    training, evaluation = reviewed_splits(tmp_path)
    training.annotations[0].reviewed = False
    with pytest.raises(ValueError, match="reviewed"):
        validate_training_data(training, evaluation, tmp_path)
    training.annotations[0].reviewed = True
    training.id = "synthetic-lanes-v1"
    with pytest.raises(ValueError, match="fixtures"):
        validate_training_data(training, evaluation, tmp_path)


def test_holdout_new_classes_rejected(tmp_path: Path) -> None:
    training, evaluation = reviewed_splits(tmp_path)
    evaluation.annotations[0].detections[0].label = "forklift"
    with pytest.raises(ValueError, match="Every evaluation class"):
        validate_training_data(training, evaluation, tmp_path)


def test_bounded_training_registers_safetensors_without_promotion(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    torch = pytest.importorskip("torch")
    pytest.importorskip("torchvision")
    import engine.train as training_module
    from engine.models import list_models
    from engine.models.local_manifest import read_manifest

    class ToyDetector(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.weight = torch.nn.Parameter(torch.tensor(1.0))

        def forward(self, images: object, targets: object) -> dict[str, object]:
            return {"loss": self.weight.square()}

    training, evaluation = reviewed_splits(tmp_path)
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "models"))
    monkeypatch.setattr(training_module, "make_model", lambda number: ToyDetector())
    result = training_module._train_ssdlite(training, evaluation, tmp_path, "local-test", max_minutes=1, epochs=1)
    assert result.steps == 1 and result.epochs_completed == 1
    assert (Path(result.model_path) / "model.safetensors").is_file()
    assert not list(Path(result.model_path).glob("*.pth"))
    manifest = read_manifest("local-test", tmp_path / "models")
    assert manifest.training_hash != manifest.evaluation_hash and manifest.base_model_id is None
    assert any(item["id"] == "local-test" for item in list_models())
    assert any("not passed held-out" in warning for warning in result.warnings)
    with pytest.raises(ValueError, match="already exists"):
        training_module._train_ssdlite(training, evaluation, tmp_path, "local-test")


def test_default_training_routes_to_pretrained_specialization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.train as training_module
    import engine.train.rtdetr as pretrained
    from engine.train.contracts import TrainingResult
    training,evaluation=reviewed_splits(tmp_path)
    expected=TrainingResult(model_id='local-pretrained',model_path=str(tmp_path),classes=['person'],
        epochs_completed=1,steps=1,elapsed_s=1,final_loss=1,training_samples=2,evaluation_samples=2,
        training_hash='a',evaluation_hash='b',device='mps',warnings=[],backend='rtdetr-v2-r18',base_model_id='rtdetr-v2-r18')
    seen=[]
    def routed(*args: object) -> TrainingResult:
        seen.append(args)
        return expected
    monkeypatch.setattr(pretrained,'train_rtdetr',routed)
    result=training_module.train_detector(training,evaluation,tmp_path,'local-pretrained')
    assert result.backend=='rtdetr-v2-r18' and seen[0][-1] is None


def test_local_detector_prefix_and_backend_manifest(tmp_path: Path) -> None:
    from engine.models.local_manifest import LocalDetectorManifest, read_manifest
    path=tmp_path/'local-detector-test'
    path.mkdir()
    manifest=LocalDetectorManifest(id='local-detector-test',backend='rtdetr-v2-r18',classes=['pallet'],
        code_license='Apache-2.0',license='Apache-2.0',training_hash='a',evaluation_hash='b',created_at='now',
        training_samples=10,epochs_completed=1,steps=5,final_loss=1,device='mps',upstream_model_id='PekingU/rtdetr_v2_r18vd')
    (path/'manifest.json').write_text(manifest.model_dump_json())
    assert read_manifest('local-detector-test',tmp_path).backend=='rtdetr-v2-r18'


def test_new_class_prior_is_low_and_known_class_rows_are_preserved() -> None:
    torch=pytest.importorskip("torch")
    from engine.train.rtdetr import _transfer_parameters
    source={"class_embed.0.bias":torch.tensor([-2.,-3.]),"class_embed.0.weight":torch.tensor([[1.,2.],[3.,4.]]),"backbone.weight":torch.tensor([9.])}
    target={"class_embed.0.bias":torch.zeros(2),"class_embed.0.weight":torch.zeros((2,2)),"backbone.weight":torch.zeros(1)}
    preserved=_transfer_parameters(source,target,{"person":0,"car":1},["forklift","person"])
    assert preserved==["person"]
    assert float(torch.sigmoid(target["class_embed.0.bias"][0]))==pytest.approx(.01)
    assert target["class_embed.0.bias"][1].item()==-2
    assert target["class_embed.0.weight"][1].tolist()==[1.,2.]
    assert target["backbone.weight"].item()==9


def test_invalid_pretrained_metadata_does_not_break_model_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from engine.models.manager import list_models
    path = tmp_path / 'rtdetr-v2-r18'
    path.mkdir()
    (path / 'config.json').write_text('{broken')
    (path / 'model.safetensors').write_bytes(b'weights')
    monkeypatch.setenv('VISION_MODELS_DIR', str(tmp_path))
    records = {item['id']: item for item in list_models()}
    assert records['rtdetr-v2-r18']['available'] is False
    assert records['fixture-color-v1']['available'] is True


def test_training_checkpoint_fingerprint_covers_processor_configuration(tmp_path: Path) -> None:
    from engine.train.rtdetr import _checkpoint_hashes
    for name in ('model.safetensors', 'config.json', 'preprocessor_config.json'):
        (tmp_path / name).write_text('initial')
    before = _checkpoint_hashes(tmp_path)
    (tmp_path / 'preprocessor_config.json').write_text('changed preprocessing')
    assert _checkpoint_hashes(tmp_path) != before
