"""Read-only capture of the actual investigation started in the native UI."""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

# This standalone evidence runner adds the repository root before local imports.
from engine.runtime_identity import source_identity  # noqa: E402

workspace = ROOT / '.visionapp/a0-investigation/run-20261029T170438Z/workspace'
project_id = 'a5c75eebf2574ccd'
task_id = 'f052ca681d1945a0b3be2ada319ebc8a'
path = workspace / 'projects' / project_id / 'investigations' / task_id / 'task.json'
output = ROOT / 'artifacts/a0-investigation/native-run'
output.mkdir(exist_ok=True)
start = json.loads((ROOT / 'artifacts/a0-investigation/native-run-start.json').read_text())
seen = set()
while True:
    record = json.loads(path.read_text())
    for action in record['actions']:
        if action['id'] not in seen and action['status'] != 'reserved':
            seen.add(action['id'])
            print(json.dumps({'status': action['status'], **action['decision']}), flush=True)
    if record['task']['status'] != 'running':
        break
    time.sleep(3)
snapshot = {key: record[key] for key in ('actions', 'observations')}
snapshot['state'] = record['task']
preview = next((item['payload'].get('preview') for item in record['observations']
                if item['id'] == record['task']['preview_observation_id']), None)
texts = [text for frame in preview.get('frames', []) for text in frame.get('texts', [])] if isinstance(preview, dict) else []
report = {'source_before': start['source_identity'], 'source_after': source_identity(ROOT),
          'entrypoint': 'Native development app composer, verified through CUA',
          'workspace': str(workspace), 'task_id': task_id, 'snapshot': snapshot,
          'reference_check': {'expected_texts': ['QZ-4817'], 'actual_preview_texts': texts,
                              'exact': texts == ['QZ-4817'] if isinstance(preview, dict) else None},
          'scope': 'Generated software fixture, actual local planner and local vision adapters. Reference excluded from planner. No representative accuracy or A0 milestone claim implied.'}
for name, value in [('task.json', record), ('snapshot.json', snapshot), ('report.json', report)]:
    (output / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
print(json.dumps({'status': record['task']['status'], 'reason': record['task']['stop_reason'],
                  'report': str(output / 'report.json')}), flush=True)
