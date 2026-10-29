"""Generated layout counterfactuals only: no models, native adapters or services."""
import hashlib
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location('smoke_layout_harness', HERE / 'run_smoke.py')
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
pytestmark = pytest.mark.skipif(not Path('/System/Library/Fonts/Supplemental/Arial.ttf').is_file(),
                                reason='Exact fixture rendering requires its documented local Arial font')
ORIGINAL_SHA256 = '36c7d4ba68b402026183b91f8705393b27fc56d4175ed80f007010517f4b3051'


def test_original_default_preserves_the_preexisting_fixture_bytes(tmp_path: Path):
    output = tmp_path / 'original.png'
    metadata = HARNESS.generate_fixture(output)
    assert hashlib.sha256(output.read_bytes()).hexdigest() == metadata['sha256'] == ORIGINAL_SHA256
    assert metadata['layout'] == 'original' and metadata['dimensions'] == [1600, 500]
    assert metadata['evidence_scope'] == 'development' and metadata['acceptance_case'] is False
    with Image.open(output) as image:
        assert metadata['rgb_pixels_sha256'] == hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def test_swapped_pixels_exchange_columns_without_changing_text_rendering(tmp_path: Path):
    original_path, swapped_path = tmp_path / 'original.png', tmp_path / 'swapped.png'
    original = HARNESS.generate_fixture(original_path)
    swapped = HARNESS.generate_fixture(swapped_path, 'swapped')
    assert swapped['layout'] == 'swapped'
    assert swapped['sha256'] != original['sha256'] and swapped['rgb_pixels_sha256'] != original['rgb_pixels_sha256']
    assert swapped['evidence_scope'] == 'development' and swapped['acceptance_case'] is False
    with Image.open(original_path) as first, Image.open(swapped_path) as second:
        # Each region includes both its header and its value. This fails if only
        # the code moves, if a header is wrong, or if glyph rendering changes.
        left, right = (80, 0, 780, 500), (850, 0, 1550, 500)
        assert first.crop(left).tobytes() == second.crop(right).tobytes()
        assert first.crop(right).tobytes() == second.crop(left).tobytes()
        assert first.crop(left).tobytes() != second.crop(left).tobytes()


def test_generated_project_origin_is_persisted_without_enabling_fixture_adapters(tmp_path: Path):
    from engine.service import WorkspaceService

    source = tmp_path / 'generated.png'
    HARNESS.generate_fixture(source)
    service = WorkspaceService(tmp_path / 'workspace')
    project = service.create_project('Origin metadata software test', 'custom')
    service.import_media(project.id, [str(source)])
    before = service.get_project(project.id)
    assert before.media and not before.fixture
    metadata = HARNESS.mark_generated_project(service, project.id)
    restored = WorkspaceService(tmp_path / 'workspace').get_project(project.id)
    assert restored.synthetic is True and restored.fixture is False
    assert restored.data_origin == metadata['data_origin']
    assert 'Generated software fixture' in restored.data_origin and 'not acceptance data' in restored.data_origin
    assert restored.media == before.media
    assert Path(restored.media[0]).read_bytes() == source.read_bytes()
