"""
Celery tasks for wallet monitoring and alerting.
All data from PostgreSQL - no YAML.
"""
from celery import shared_task
import logging
from datetime import datetime, timedelta
from utils.logging_config import setup_logging

logger = setup_logging('monitor_tasks.log')


@shared_task(name='check_wallet_activity')
def check_wallet_activity(chain: str = None):
    """Check for new activity on monitored wallets."""
    from utils.database import get_session_factory
    from api.services.data_access import DataAccess
    
    Session = get_session_factory()
    session = Session()
    data = DataAccess(session)
    
    wallets = data.get_monitored_wallets(chain_code=chain)
    
    if not wallets:
        session.close()
        return {'status': 'ok', 'wallets_checked': 0, 'alerts': 0}
    
    alerts_generated = 0
    for wallet in wallets:
        alerts = _check_wallet_transactions(wallet, data)
        alerts_generated += len(alerts)
    
    session.close()
    return {'status': 'completed', 'wallets_checked': len(wallets), 'alerts_generated': alerts_generated}


def _check_wallet_transactions(wallet, data):
    """Check database for new transactions involving wallet."""
    from utils.database import get_session_factory
    from sqlalchemy import text
    
    alerts = []
    Session = get_session_factory()
    session = Session()
    cutoff = datetime.utcnow() - timedelta(hours=1)
    
    try:
        tables = session.execute(text(
            "SELECT table_name FROM information_schema.tables WHERE table_name LIKE :pattern"
        ), {'pattern': f'%_{wallet.chain_code.lower()}_erc20_transfer_event'}).fetchall()
        
        for (table_name,) in tables:
            for tx in session.execute(text(f"""
                SELECT to_contract_address, hash FROM {table_name}
                WHERE LOWER(from_contract_address) = :addr AND timestamp >= :cutoff LIMIT 50
            """), {'addr': wallet.address.lower(), 'cutoff': cutoff}):
                to_addr, tx_hash = tx
                alert_type = 'mixer' if data.is_mixer(to_addr) else 'outgoing'
                alerts.append({'type': alert_type, 'counterparty': to_addr, 'tx_hash': tx_hash})
    finally:
        session.close()
    
    return alerts


@shared_task(name='start_case_monitoring')
def start_case_monitoring(case_id: str):
    """Start monitoring all addresses from a specific case."""
    from utils.database import get_session_factory
    from api.services.data_access import DataAccess
    from api.application.models import MonitoredWallet
    
    Session = get_session_factory()
    session = Session()
    data = DataAccess(session)
    
    case = data.get_case(case_id)
    if not case:
        session.close()
        return {'status': 'error', 'message': f'Case not found: {case_id}'}
    
    count = 0
    for wallet in case.wallets:
        exists = session.query(MonitoredWallet).filter(
            MonitoredWallet.address == wallet.address.lower(),
            MonitoredWallet.chain_code == wallet.chain_code
        ).first()
        
        if not exists:
            session.add(MonitoredWallet(
                address=wallet.address.lower(),
                chain_code=wallet.chain_code,
                case_id=case_id,
                label=wallet.label,
                role=wallet.role,
                is_active=True
            ))
            count += 1
    
    session.commit()
    session.close()
    return {'status': 'success', 'case_id': case_id, 'wallets_added': count}


@shared_task(name='generate_alert_report')
def generate_alert_report(hours: int = 24):
    """Generate a report of recent alerts."""
    from utils.database import get_session_factory
    from api.services.data_access import DataAccess
    
    Session = get_session_factory()
    session = Session()
    data = DataAccess(session)
    
    stats = data.get_alert_stats()
    session.close()
    return {'period_hours': hours, 'stats': stats}


@shared_task(name='run_notebook_task', bind=True)
def run_notebook_task(self, notebook_name: str, parameters: dict = None):
    """Execute a notebook asynchronously via Celery."""
    from api.services.notebook_runner import get_notebook_runner
    
    try:
        runner = get_notebook_runner()
        execution = runner.execute_notebook(notebook_name=notebook_name, parameters=parameters or {}, timeout=1800, generate_html=True)
        return execution.to_dict()
    except Exception as e:
        return {'status': 'failed', 'error': str(e)}
