from pathlib import Path

import pytest
from PIL import Image

from engine.runtime.autolabel import propose_labels
from spec.models import Annotation, Detection, EvalDataset, PipelineSpec


def detector_spec() -> PipelineSpec:
    return PipelineSpec.model_validate({"name":"labels", "inputs":{"source":{"type":"image_folder","path":"media"}},
        "blocks":[{"id":"sample","type":"frame_sample","in":{"frames":"$inputs.source"}},
                  {"id":"det","type":"detect_open_vocab","params":{"model":"owlv2-base-patch16","classes":["person"]},"in":{"image":"$sample.frame"}}]})


def test_proposals_preserve_human_labels_and_stay_unreviewed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.compiler as compiler
    from engine.adapters import legacy as executor
    monkeypatch.setattr(compiler,"validate_model",lambda *a,**k: None)
    import engine.adapters.identity as adapter_identity
    monkeypatch.setattr(adapter_identity, "execution_provider", lambda adapter: "cpu")
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path / "models"))
    installed = tmp_path / "models" / "owlv2-base-patch16"
    installed.mkdir(parents=True)
    for name in ("model.safetensors", "config.json", "preprocessor_config.json"):
        (installed / name).write_bytes(b"synthetic-test-model-artifact")
    proposal=Detection(label="person",confidence=.7,box=[.1,.1,.5,.9])
    monkeypatch.setattr(executor,"detect",lambda *a,**k: [proposal])
    annotations=[]
    for i in range(4):
        path=tmp_path/f"{i}.png"
        Image.new("RGB",(20,20),(i,0,0)).save(path)
        annotations.append(Annotation(image_path=str(path)))
    annotations[0].reviewed=True
    annotations[1].detections=[proposal.model_copy(update={"label":"manual"})]
    dataset=EvalDataset(id="test",annotations=annotations)
    before=dataset.model_dump_json()
    result=propose_labels(detector_spec(),dataset,tmp_path,max_frames=1)
    assert dataset.model_dump_json()==before
    assert result.annotations[0]==dataset.annotations[0]
    assert result.annotations[1]==dataset.annotations[1]
    assert result.annotations[2].detections==[proposal] and not result.annotations[2].reviewed
    assert result.annotations[2].proposal and result.annotations[2].proposal.status=="unverified_hypothesis"
    assert result.annotations[3].proposal is None


def test_rectangle_fixture_cannot_create_warehouse_proposals(tmp_path: Path) -> None:
    spec=detector_spec()
    spec.blocks[1].params["model"]="fixture-color-v1"
    with pytest.raises(ValueError,match="Rectangle fixture"):
        propose_labels(spec,EvalDataset(id="test",annotations=[Annotation(image_path="test.png")]),tmp_path)
