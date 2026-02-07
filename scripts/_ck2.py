import sys, json
sys.path.insert(0, '/app')
from celery.result import AsyncResult
from celery_worker import celery_app

# These are the RETRY task IDs (after celery restart)
tasks = {
    'rf': 'd073ba98-7d2f-4ddb-a838-606508dd5cca',
    'gb': 'a2d8c39b-1b6c-474b-b6cf-d699c1916b90',
    'xg': '2a6cfde5-e42f-4c5d-a9e1-dc342272a630'
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
                entry['msg'] = str(info.get('message', ''))[:200]
            else:
                entry['data'] = {k: v for k, v in info.items() if k not in ('status', 'message')}
    elif r.state == 'FAILURE':
        entry['error'] = str(r.info)[:200]
    out[n] = entry

with open('/tmp/train2.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print('DONE')
