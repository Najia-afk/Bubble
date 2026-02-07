import sys, json
sys.path.insert(0, '/app')
from celery.result import AsyncResult
from celery_worker import celery_app

tasks = {
    'rf': 'eac4a1b1-62b4-4137-90c9-f5d1398101cd',
    'gb': '2f1ef912-1af2-4098-8df7-73e43209fee6',
    'xg': '02a720d1-7668-45cf-972f-140777cf4f5a'
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
                # Extract key metrics
                for k in ('model_type', 'accuracy', 'f1_weighted', 'run_id', 
                          'model_version', 'training_samples', 'n_classes',
                          'cv_mean_accuracy', 'cv_std_accuracy'):
                    if k in info:
                        entry[k] = info[k]
    elif r.state == 'FAILURE':
        entry['error'] = str(r.info)[:500]
    out[n] = entry

with open('/tmp/train_v4.json', 'w') as f:
    json.dump(out, f, indent=2, default=str)
print('OK')
