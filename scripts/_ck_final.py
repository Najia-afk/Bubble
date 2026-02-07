import sys, json
sys.path.insert(0, '/app')
from celery.result import AsyncResult
from celery_worker import celery_app

tasks = {
    'rf': 'b2866379-5e44-4fcd-bd70-a09a5fdc0f2b',
    'gb': '2507b166-07f4-44ca-9567-385b16f20ed9',
    'xg': 'e9aa6c30-c0fc-4a5a-b444-85bc6ba9d9dd'
}

out = {}
for n, t in tasks.items():
    r = AsyncResult(t, app=celery_app)
    entry = {'state': r.state}
    if r.state == 'SUCCESS':
        info = r.result
        if isinstance(info, dict):
            entry['status'] = info.get('status')
            if info.get('status') == 'error':
                entry['msg'] = str(info.get('message', ''))[:500]
            else:
                entry['data'] = {}
                for k, v in info.items():
                    if k not in ('status', 'message', 'classification_report'):
                        entry['data'][k] = v
    elif r.state == 'FAILURE':
        entry['error'] = str(r.info)[:500]
    out[n] = entry

with open('/tmp/train_final.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print('OK')
