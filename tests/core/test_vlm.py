"""Local-model compatibility, output validation and immutable evidence tests."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from PIL import Image

from engine.llm_client import VLMConfig, VLMError, judge_image, preflight
from engine.llm_client.contracts import VLMDecision


def server_response(request: httpx.Request, *, label: str = "person", vision: bool = True,
                    model: str = "visionapp-vlm", marker: str = "session-1") -> httpx.Response:
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": model, "created": 123,
            "architecture": {"input_modalities": ["text", "image"] if vision else ["text"]}}]})
    if request.url.path == "/props":
        return httpx.Response(200, json={"model_alias": model, "modalities": {"vision": vision}, "media_marker": marker})
    body = json.loads(request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    return httpx.Response(200, json={"model": model, "choices": [{"finish_reason": "stop",
        "message": {"content": VLMDecision(label=label, reason="A visible person is centered in the crop.", confidence=.8).model_dump_json()}}]})


@pytest.mark.parametrize("url", ["https://example.com/v1", "http://192.168.1.2/v1", "http://localhost/v1?x=1", "http://user@localhost/v1", "http://localhost/api"])
def test_vlm_rejects_nonlocal_or_ambiguous_urls(url: str) -> None:
    with pytest.raises(ValueError):
        VLMConfig(base_url=url)


def test_typed_image_request_returns_hypothesis_with_identity() -> None:
    with httpx.Client(transport=httpx.MockTransport(server_response)) as client:
        result = judge_image(Image.new("RGB", (120, 80)), VLMConfig(), "Is a person visible?", ["person", "none"], client=client)
    assert result.label == "person" and result.status == "model_hypothesis"
    assert result.identity_scope == "server_metadata_only" and result.attempts == 1
    assert len(result.image_sha256) == 64 and result.input_size == (120, 80)


def test_text_only_model_is_rejected_before_image_request() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda r: server_response(r, vision=False))) as client:
        with pytest.raises(VLMError, match="image input"):
            judge_image(Image.new("RGB", (100, 100)), VLMConfig(), "Inspect", ["yes", "no"], client=client)


def test_wrong_model_is_not_silently_used() -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda r: server_response(r, model="other"))) as client:
        with pytest.raises(VLMError, match="not loaded"):
            preflight(VLMConfig(), client=client)


def test_invalid_labels_have_bounded_retries() -> None:
    calls = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("completions"):
            calls += 1
        return server_response(request, label="unallowed")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(VLMError, match="after 2 attempts"):
            judge_image(Image.new("RGB", (10, 10)), VLMConfig(retries=1), "Inspect", ["yes", "no"], client=client)
    assert calls == 2


def test_bad_json_and_truncation_do_not_become_answers() -> None:
    for content, finish in (("not json", "stop"), ('{"label":"person"}', "length")):
        def handler(request: httpx.Request, body: str = content, ending: str = finish) -> httpx.Response:
            if request.url.path.endswith("completions"):
                return httpx.Response(200, json={"model": "visionapp-vlm", "choices": [{"finish_reason": ending, "message": {"content": body}}]})
            return server_response(request)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(VLMError, match="valid judgement"):
                judge_image(Image.new("RGB", (10, 10)), VLMConfig(retries=0), "Inspect", ["person", "none"], client=client)


def test_server_replacement_during_call_invalidates_result() -> None:
    calls = 0
    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path.endswith("completions"):
            calls += 1
        return server_response(request, marker="session-2" if calls else "session-1")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(VLMError, match="changed during inference"):
            judge_image(Image.new("RGB", (10, 10)), VLMConfig(), "Inspect", ["person", "none"], client=client)


def test_local_weight_replacement_changes_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_MODELS_DIR", str(tmp_path))
    weights = tmp_path / "test.gguf"
    weights.write_bytes(b"test weights revision one")
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/props":
            return httpx.Response(200, json={"model_alias": "visionapp-vlm", "model_path": str(weights), "modalities": {"vision": True}})
        return server_response(request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        first = preflight(VLMConfig(), client=client)
        weights.write_bytes(b"test weights revision two with different bytes")
        second = preflight(VLMConfig(), client=client)
    assert first.identity_scope == "local_weights_verified"
    assert first.identity_hash != second.identity_hash and first.weights_sha256 != second.weights_sha256


def test_offline_model_fails_explicitly() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline")
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(VLMError, match="preflight failed"):
            preflight(VLMConfig(), client=client)


def test_vlm_block_preserves_crop_evidence_and_cannot_use_count_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import engine.compiler as compiler
    import engine.llm_client as llm
    from engine.llm_client import VLMJudgement, VLMPreflight
    from engine.runtime import run_pipeline
    from spec.models import PipelineSpec
    identity=VLMPreflight(model='visionapp-vlm',base_url='http://127.0.0.1:1235/v1',vision_supported=True,
                          identity_hash='a'*64,identity_scope='local_weights_verified',weights_sha256='b'*64)
    monkeypatch.setattr(compiler,'preflight',lambda config: identity)
    def judge(image: Image.Image, config: VLMConfig, question: str, labels: list[str]) -> VLMJudgement:
        return VLMJudgement(label='person',reason='A person is visible.',confidence=.8,model=config.model,base_url=config.base_url,
            image_sha256='c'*64,model_identity_hash=identity.identity_hash,identity_scope=identity.identity_scope,
            input_size=image.size,sent_size=image.size,elapsed_s=.1,attempts=1)
    monkeypatch.setattr(llm,'judge_image',judge)
    Image.new('RGB',(100,100)).save(tmp_path/'frame.png')
    spec=PipelineSpec.model_validate({'name':'visual-judgement','inputs':{'source':{'type':'image_file','path':'frame.png'}},
        'blocks':[{'id':'sample','type':'frame_sample','in':{'frames':'$inputs.source'}},
                  {'id':'roi','type':'crop','params':{'box':[.2,.3,.7,.8]},'in':{'image':'$sample.frame'}},
                  {'id':'judge','type':'vlm_judge','params':{'question':'Person?','labels':['person','none']},'in':{'image':'$roi.image'}},
                  {'id':'out','type':'sink_event','in':{'event':'$judge.event'}}],
        'eval':{'metric':'text_accuracy','target':.9}})
    result=run_pipeline(spec,tmp_path)
    assert result.frames[0].judgements[0].box==[.2,.3,.7,.8]
    assert result.frames[0].texts==['person'] and result.frames[0].detections==[]
    assert result.frames[0].events[0]['status']=='model_hypothesis'
    spec.eval.metric='count_mae'
    with pytest.raises(ValueError,match='text_accuracy'):
        compiler.compile_pipeline(spec,tmp_path)
