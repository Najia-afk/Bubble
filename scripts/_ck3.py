import sys, json
sys.path.insert(0, '/app')
from celery.result import AsyncResult
from celery_worker import celery_app

r = AsyncResult('6575ab91-e03c-4fa4-ada4-0ccf22bb3394', app=celery_app)
out = {'state': r.state}
if r.state == 'SUCCESS':
    info = r.result
    if isinstance(info, dict):
        out['status'] = info.get('status')
        if info.get('status') == 'error':
            out['msg'] = str(info.get('message', ''))[:500]
        else:
            out['data'] = {k: v for k, v in info.items() if k not in ('status', 'message')}
elif r.state == 'FAILURE':
    out['error'] = str(r.info)[:500]
with open('/tmp/ck3.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print('OK')
