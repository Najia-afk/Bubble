# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================

#celery_worker.py
from celery import Celery
from config.settings import get_config
from utils.database import get_session_factory
import api.application.erc20models as erc20models
from utils.logging_config import setup_logging

celery_logger = setup_logging('celery_worker.log')

def initialize_dynamic_models():
    """Initialize dynamic models for Celery worker.
    Retries a few times since the web container may still be creating tables.
    """
    import time
    max_retries = 5
    for attempt in range(max_retries):
        SessionFactory = get_session_factory()
        session = SessionFactory()
        try:
            erc20models.generate_block_transfer_event_classes(session)
            erc20models.generate_erc20_classes(session)
            session.commit()
            celery_logger.info("Dynamic models initialized successfully for Celery worker")
            return
        except Exception as e:
            session.rollback()
            if attempt < max_retries - 1:
                celery_logger.warning(f"Model init attempt {attempt + 1}/{max_retries} failed: {e}. Retrying in 5s...")
                time.sleep(5)
            else:
                celery_logger.warning(f"Dynamic model init skipped after {max_retries} attempts: {e}")
        finally:
            SessionFactory.remove()

def make_celery(app_name=__name__):
    app_config = get_config()
    celery = Celery(
        app_name, 
        broker=app_config['CELERY_BROKER_URL'], 
        backend=app_config['result_backend'],
        include=[
            'api.tasks.tasks', 
            'api.tasks.fetch_token_data_task', 
            'api.tasks.tigergraph_tasks', 
            'api.tasks.import_labels_task', 
            'api.tasks.investigation_tasks',
            'api.tasks.ml_tasks'
        ]
    )
    celery.conf.update(app_config)
    celery.conf.broker_connection_retry_on_startup = True 
    
    
    class ContextTask(celery.Task):
        def __call__(self, *args, **kwargs):
            # Assuming you have a way to get Flask app context here if needed
            return super(ContextTask, self).__call__(*args, **kwargs)
                
    celery.Task = ContextTask
    # Auto-discover tasks from the specified modules
    # celery.autodiscover_tasks(['api.tasks'], force=True)
    
    return celery

celery_app = make_celery()

# Initialize dynamic models when Celery worker starts
initialize_dynamic_models()

#celery -A celery_worker.celery_app worker -l info -P solo
#nohup celery -A celery_worker.celery_app worker --loglevel=info &
#ps aux | grep 'celery' | grep -v grep | awk '{print $2}' | xargs kill -9


