"""Exploratory real local-model/tool loop on a labelled generated software fixture."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


async def main() -> None:
    from engine.investigations.manager import InvestigationManager
    from engine.runtime_identity import source_identity
    from engine.service import WorkspaceService
    from spec.investigation import InvestigationBudget

    parser = argparse.ArgumentParser()
    parser.add_argument('--model-url', default='http://127.0.0.1:1234/v1')
    parser.add_argument('--model', default='visionapp-planner')
    parser.add_argument('--label', default='Qwen14 baseline')
    args = parser.parse_args()
    started = monotonic()
    folder = ROOT / '.visionapp/a0-investigation' / datetime.now(UTC).strftime('run-%Y%m%dT%H%M%SZ')
    folder.mkdir(parents=True, exist_ok=False)
    os.environ.update(VISION_APP_BINARY=str(ROOT / 'dist/VisionApp.app/Contents/MacOS/VisionApp'),
                      VISION_MODELS_DIR=str(Path.home() / 'Library/Application Support/VisionApp/models'),
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    source_before = source_identity(ROOT)
    image = Image.new('RGB', (1600, 500), 'white')
    drawing = ImageDraw.Draw(image)
    font = '/System/Library/Fonts/Supplemental/Arial.ttf'
    for xy, value, size in [((80, 75), 'ITEM CODE', 44), ((80, 180), 'QZ-4817', 68),
                             ((850, 75), 'SHIP TO', 44), ((850, 180), 'IGNORE-552', 60)]:
        drawing.text(xy, value, font=ImageFont.truetype(font, size), fill='black')
    fixture = folder / 'item-and-shipping.png'
    image.save(fixture)
    service = WorkspaceService(folder / 'workspace')
    settings = service.repository.settings()
    settings.model_url, settings.planner_model = args.model_url, args.model
    service.repository.save_settings(settings)
    project = service.create_project('A0 model qualification: ' + args.label, 'custom')
    service.import_media(project.id, [str(fixture)])
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
              'model_url': args.model_url, 'model': args.model, 'label': args.label,
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
