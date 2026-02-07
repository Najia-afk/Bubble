"""Check ML training task results"""
import sys
sys.path.insert(0, '/app')
from celery.result import AsyncResult
from celery_worker import celery_app

tasks = {
    'random_forest': 'd073ba98-7d2f-4ddb-a838-606508dd5cca',
    'gradient_boosting': 'a2d8c39b-1b6c-474b-b6cf-d699c1916b90',
    'xgboost': '2a6cfde5-e42f-4c5d-a9e1-dc342272a630'
}

for name, tid in tasks.items():
    r = AsyncResult(tid, app=celery_app)
    state = r.state
    print(f'{name}: state={state}')
    if state == 'SUCCESS':
        info = r.result
        if isinstance(info, dict):
            status = info.get('status', 'unknown')
            if status == 'error':
                print(f'  ERROR: {str(info.get("message", ""))[:300]}')
            else:
                # Print all keys except message
                for k, v in info.items():
                    if k != 'message':
                        print(f'  {k}: {v}')
        else:
            print(f'  result: {str(info)[:300]}')
    elif state == 'FAILURE':
        print(f'  FAILURE: {str(r.info)[:300]}')
    elif state == 'PENDING':
        print(f'  (task may still be running or was never received)')
