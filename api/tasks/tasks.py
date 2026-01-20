# api/tasks/task.py
import asyncio
from celery import shared_task
from utils.database import get_session_factory
from utils.logging_config import setup_logging
from celery_worker import celery_app
from api.services.fetch_erc20_transfer_history_service import get_erc20_transfer_history_service
from api.services.fetch_token_price_history_service import get_token_price_history_service
from api.services.fetch_last_token_price_history_service import get_last_token_price_history_service

SessionFactory = get_session_factory()
logger = setup_logging('celery_tasks')

def sync_wrapper(func, *args, **kwargs):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        coro = func(*args, **kwargs)
        return loop.run_until_complete(coro)
    except Exception as e:
        logger.error("Error running async function in sync wrapper", exc_info=True)
        raise
    finally:
        loop.close()

@shared_task(bind=True)
def fetch_last_token_price_history_task(self, symbols):
    session = SessionFactory()
    try:
        result = sync_wrapper(get_last_token_price_history_service, symbols, session)
        session.commit()
        return result
    except Exception as e:
        session.rollback()
        logger.error(f"Error in fetch_last_token_price_history_task: {e}", exc_info=True)
        raise
    finally:
        session.close()

@shared_task(bind=True)
def fetch_erc20_transfer_history_task(self, trigram_info):
    session = SessionFactory()
    try:
        result = sync_wrapper(get_erc20_transfer_history_service, trigram_info, session)
        session.commit()
        return result
    except Exception as e:
        session.rollback()
        logger.error(f"Error in fetch_erc20_transfer_history_task: {e}", exc_info=True)
        raise e
    finally:
        session.close()

@shared_task(bind=True)
def fetch_token_price_history_task(self, symbols, start_date, end_date):
    session = SessionFactory()
    try:
        result = sync_wrapper(get_token_price_history_service,symbols, start_date, end_date, session)
        session.commit()
        return result
    except Exception as e:
        session.rollback()
        logger.error(f"Error in fetch_token_price_history_task: {e}", exc_info=True)
        raise e
    finally:
        session.close()