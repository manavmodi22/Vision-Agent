"""Exploratory real local-model/tool loop on a labelled generated software fixture."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


def generate_fixture(fixture: Path, layout: str = 'original') -> dict[str, object]:
    """Render development pixels; reference values remain outside planner input."""
    if layout not in {'original', 'swapped'}:
        raise ValueError('Unknown fixture layout')
    image = Image.new('RGB', (1600, 500), 'white')
    drawing = ImageDraw.Draw(image)
    font = '/System/Library/Fonts/Supplemental/Arial.ttf'
    for xy, value, size in [((80, 75), 'ITEM CODE', 44), ((80, 180), 'QZ-4817', 68),
                             ((850, 75), 'SHIP TO', 44), ((850, 180), 'IGNORE-552', 60)]:
        if layout == 'swapped':
            xy = (850 if xy[0] == 80 else 80, xy[1])
        drawing.text(xy, value, font=ImageFont.truetype(font, size), fill='black')
    image.save(fixture)
    return {'layout': layout, 'sha256': hashlib.sha256(fixture.read_bytes()).hexdigest(),
            'rgb_pixels_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
            'pixel_hash_recipe': 'SHA256 of RGB image.tobytes()', 'dimensions': list(image.size),
            'provenance': 'Generated software fixture using Pillow and local Arial font; '
                          'contents preexposed during development. Swapped layout is a deliberate '
                          'development counterfactual, not a held-out acceptance case.',
            'evidence_scope': 'development', 'acceptance_case': False}


def mark_generated_project(service: Any, project_id: str) -> dict[str, object]:
    """Label imported pixels truthfully without enabling synthetic adapters."""
    project = service.get_project(project_id)
    project.synthetic = True
    project.fixture = False
    project.data_origin = 'Generated software fixture; contents preexposed during development, not acceptance data'
    service.repository.save(project)
    return {'synthetic': project.synthetic, 'fixture': project.fixture, 'data_origin': project.data_origin}


async def main() -> None:
    from engine.investigations.manager import InvestigationManager
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService
    from spec.investigation import InvestigationBudget

    parser = argparse.ArgumentParser()
    parser.add_argument('--model-url', default='http://127.0.0.1:1234/v1')
    parser.add_argument('--model', default='visionapp-planner')
    parser.add_argument('--label', default='Qwen14 baseline')
    parser.add_argument('--layout', choices=['original', 'swapped'], default='original',
                        help='Generated development fixture layout; original preserves the existing image bytes')
    parser.add_argument('--transport', choices=['structured_json', 'decision_function'], default='structured_json',
                        help='Explicit response transport; saved only in this run\'s isolated workspace settings')
    args = parser.parse_args()
    started = monotonic()
    folder = ROOT / '.visionapp/a0-investigation' / datetime.now(UTC).strftime('run-%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True, exist_ok=False)
    os.environ.update(VISION_APP_BINARY=str(ROOT / 'dist/VisionApp.app/Contents/MacOS/VisionApp'),
                      VISION_MODELS_DIR=str(Path.home() / 'Library/Application Support/VisionApp/models'),
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    source_before = source_identity(ROOT)
    fixture = folder / 'item-and-shipping.png'
    fixture_metadata = generate_fixture(fixture, args.layout)
    service = WorkspaceService(folder / 'workspace')
    settings = service.repository.settings()
    settings.model_url, settings.planner_model = args.model_url, args.model
    settings.investigation_transport = args.transport
    service.repository.save_settings(settings)
    project = service.create_project('A0 model qualification: ' + args.label, 'custom')
    service.import_media(project.id, [str(fixture)])
    fixture_metadata['project_provenance'] = mark_generated_project(service, project.id)
    manager = InvestigationManager(service)
    task = await manager.start(project.id,
        'Build an app that reads only the item code from each image. Ignore the shipping label. Use the supplied image to figure out how.',
        'generated-fixture-smoke', InvestigationBudget(max_model_calls=20, max_actions=16, max_probes=6, max_elapsed_s=900))
    print(json.dumps({'workspace': str(folder), 'project_id': project.id, 'task_id': task.id, 'source_identity': source_before}), flush=True)
    runner = manager.tasks[project.id, task.id]
    seen: set[str] = set()
    while not runner.done():
        for action in manager.store.actions(project.id, task.id):
            if action.id not in seen and action.status != 'reserved':
                seen.add(action.id)
                print(json.dumps({'action': action.action.type, 'purpose': action.decision.decision_summary,
                                  'based_on': action.decision.based_on_observation_ids, 'status': action.status}), flush=True)
        await asyncio.sleep(2)
    await runner
    snapshot = manager.snapshot(project.id, task.id)
    preview = next((item.payload.get('preview') for item in snapshot.observations
                    if item.id == snapshot.state.preview_observation_id), None)
    preview_texts = [text for frame in preview.get('frames', []) for text in frame.get('texts', [])] if isinstance(preview, dict) else []
    report = {'source_before': source_before, 'source_after': source_identity(ROOT),
              'fixture': fixture_metadata,
              'model_url': args.model_url, 'model': args.model, 'label': args.label, 'transport': args.transport,
              'elapsed_s': monotonic()-started, 'workspace': str(folder), 'snapshot': snapshot.model_dump(mode='json'),
              'reference': {'origin': 'Generated software fixture; these expected values were not supplied to the planner',
                            'expected_preview_texts': ['QZ-4817'], 'excluded_readings': ['ITEM CODE', 'SHIP TO', 'IGNORE-552']},
              'reference_check': {'actual_preview_texts': preview_texts,
                                  'exact': preview_texts == ['QZ-4817'] if isinstance(preview, dict) else None},
              'scope': 'Exploratory local planner and real local adapters on a generated software fixture. No A0 milestone or representative quality acceptance claim. Native integration is verified separately.'}
    (folder / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({'status': snapshot.state.status, 'reason': snapshot.state.stop_reason,
                      'actions': len(snapshot.actions), 'report': str(folder/'report.json')}), flush=True)
    await manager.close()


if __name__ == '__main__':
    asyncio.run(main())
