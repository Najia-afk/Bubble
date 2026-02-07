# api/tasks/investigation_report_tasks.py
"""
Celery task for generating investigation summary reports.
"""
from celery import shared_task
from typing import Dict

from utils.database import get_session_factory
from utils.logging_config import setup_logging

from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationToken
)

logger = setup_logging('investigation_tasks.log')


@shared_task(name='generate_investigation_report')
def generate_investigation_report(investigation_id: int) -> Dict:
    """
    Generate a summary report for an investigation.
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            return {'status': 'error', 'message': 'Investigation not found'}
        
        wallets = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id
        ).all()
        
        tokens = session.query(InvestigationToken).filter_by(
            investigation_id=investigation_id
        ).all()
        
        # Aggregate statistics
        wallet_by_role = {}
        wallet_by_depth = {}
        flagged_wallets = []
        exchange_endpoints = []
        bridge_endpoints = []
        
        for wallet in wallets:
            role = wallet.role or 'unknown'
            wallet_by_role[role] = wallet_by_role.get(role, 0) + 1
            
            depth = wallet.depth
            wallet_by_depth[depth] = wallet_by_depth.get(depth, 0) + 1
            
            if wallet.is_flagged:
                flagged_wallets.append({
                    'address': wallet.address,
                    'role': wallet.role,
                    'depth': wallet.depth,
                    'total_received': wallet.total_received
                })
            
            if wallet.role == 'exchange':
                exchange_endpoints.append({
                    'address': wallet.address,
                    'total_received': wallet.total_received
                })
            elif wallet.role == 'bridge':
                bridge_endpoints.append({
                    'address': wallet.address,
                    'total_received': wallet.total_received
                })
        
        report = {
            'investigation': {
                'id': investigation.id,
                'name': investigation.name,
                'status': investigation.status,
                'incident_date': investigation.incident_date.isoformat() if investigation.incident_date else None,
                'reported_loss_usd': investigation.reported_loss_usd,
                'created_at': investigation.created_at.isoformat() if investigation.created_at else None,
            },
            'summary': {
                'total_wallets': len(wallets),
                'total_tokens': len(tokens),
                'flagged_wallets': len(flagged_wallets),
                'exchange_endpoints': len(exchange_endpoints),
                'bridge_endpoints': len(bridge_endpoints),
            },
            'wallets_by_role': wallet_by_role,
            'wallets_by_depth': wallet_by_depth,
            'flagged_wallets': flagged_wallets[:20],
            'exchange_endpoints': exchange_endpoints,
            'bridge_endpoints': bridge_endpoints,
            'tokens_tracked': [
                {
                    'symbol': t.symbol,
                    'contract': t.contract_address,
                    'chain_id': t.chain_id,
                    'stolen_amount': t.stolen_amount
                }
                for t in tokens
            ]
        }
        
        return {
            'status': 'success',
            'report': report
        }
        
    except Exception as e:
        logger.error(f"Error generating report: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()
