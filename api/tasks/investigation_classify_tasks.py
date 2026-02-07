# api/tasks/investigation_classify_tasks.py
"""
Celery tasks for classifying investigation wallets via ML and heuristics.
"""
from celery import shared_task
from sqlalchemy import func
from typing import Dict

from utils.database import get_session_factory
from utils.logging_config import setup_logging

from api.application.erc20models import (
    InvestigationWallet, InvestigationTransfer, CHAIN_ID_TO_TRIGRAM
)
from api.tasks.investigation_expand_tasks import _load_known_addresses
from api.services.wallet_classifier import get_wallet_classifier

logger = setup_logging('investigation_tasks.log')


def _classify_from_transfers(session, address: str, investigation_id: int, chain_id: int) -> Dict:
    """Classify a wallet based on its InvestigationTransfer data.
    
    Uses heuristic rules on transfer patterns:
    - Many unique counterparties + high volume → exchange
    - Few counterparties + round amounts → mixer
    - Sends to many different wallets in quick succession → bot/attacker
    - Receives from one, sends to one → intermediate/layering
    """
    addr_lower = address.lower()
    
    out_stats = session.query(
        func.count(InvestigationTransfer.id).label('count'),
        func.sum(InvestigationTransfer.value).label('total'),
        func.count(func.distinct(InvestigationTransfer.to_address)).label('unique_recipients')
    ).filter(
        InvestigationTransfer.investigation_id == investigation_id,
        func.lower(InvestigationTransfer.from_address) == addr_lower,
        InvestigationTransfer.chain_id == chain_id
    ).first()
    
    in_stats = session.query(
        func.count(InvestigationTransfer.id).label('count'),
        func.sum(InvestigationTransfer.value).label('total'),
        func.count(func.distinct(InvestigationTransfer.from_address)).label('unique_senders')
    ).filter(
        InvestigationTransfer.investigation_id == investigation_id,
        func.lower(InvestigationTransfer.to_address) == addr_lower,
        InvestigationTransfer.chain_id == chain_id
    ).first()
    
    out_count = out_stats.count or 0
    out_total = float(out_stats.total or 0)
    unique_recipients = out_stats.unique_recipients or 0
    in_count = in_stats.count or 0
    in_total = float(in_stats.total or 0)
    unique_senders = in_stats.unique_senders or 0
    
    total_txs = in_count + out_count
    total_counterparties = unique_senders + unique_recipients
    
    if total_txs == 0:
        return {'predicted_type': 'unknown', 'confidence': 0.0, 'features': {}}
    
    features = {
        'in_count': in_count, 'out_count': out_count,
        'in_total': in_total, 'out_total': out_total,
        'unique_senders': unique_senders, 'unique_recipients': unique_recipients,
        'total_txs': total_txs, 'total_counterparties': total_counterparties
    }
    
    # Heuristic classification
    predicted_type = 'normal'
    confidence = 0.3
    
    if total_counterparties >= 100 and total_txs >= 200:
        predicted_type = 'exchange'
        confidence = min(0.9, 0.5 + total_counterparties / 1000)
    elif unique_senders >= 10 and unique_recipients >= 10 and total_txs >= 50:
        predicted_type = 'mixer'
        confidence = 0.6
    elif total_txs >= 20 and total_counterparties < 20:
        ratio = min(in_total, out_total) / max(in_total, out_total) if max(in_total, out_total) > 0 else 0
        if ratio > 0.8:
            predicted_type = 'bridge'
            confidence = 0.5
    elif out_total > 100000 or in_total > 100000:
        predicted_type = 'whale'
        confidence = 0.6
    elif total_txs >= 100 and total_counterparties < 10:
        predicted_type = 'bot'
        confidence = 0.5
    elif total_txs >= 20:
        predicted_type = 'defi'
        confidence = 0.4
    
    return {'predicted_type': predicted_type, 'confidence': confidence, 'features': features}


@shared_task(name='classify_investigation_wallets')
def classify_investigation_wallets(investigation_id: int):
    """
    Classify all wallets in an investigation using InvestigationTransfer data.
    
    Two-pass approach:
    1. First check known addresses DB (mixers, bridges, exchanges) — fast, high confidence
    2. Then analyze transfer patterns from InvestigationTransfer for behavioral classification
    
    Also tries the full ML classifier if per-token transfer tables exist.
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        wallets = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id
        ).all()
        
        if not wallets:
            return {'status': 'error', 'message': 'No wallets in investigation'}
        
        known_mixers, known_bridges, known_exchanges = _load_known_addresses(session)
        
        try:
            classifier = get_wallet_classifier()
        except Exception:
            classifier = None
        
        results = []
        updated = 0
        
        for wallet in wallets:
            addr_lower = wallet.address.lower()
            chain_trigram = CHAIN_ID_TO_TRIGRAM.get(wallet.chain_id, 'ETH')
            
            # Pass 1: Check known addresses (highest confidence)
            if addr_lower in known_exchanges:
                entity = known_exchanges[addr_lower]
                classification = {
                    'predicted_type': 'exchange', 
                    'confidence': 1.0,
                    'source': 'known_db',
                    'name': getattr(entity, 'name_tag', None) or getattr(entity, 'label', '')
                }
            elif addr_lower in known_mixers:
                m = known_mixers[addr_lower]
                classification = {
                    'predicted_type': 'mixer',
                    'confidence': 1.0,
                    'source': 'known_db',
                    'name': m.name or m.protocol
                }
            elif addr_lower in known_bridges:
                b = known_bridges[addr_lower]
                classification = {
                    'predicted_type': 'bridge',
                    'confidence': 1.0,
                    'source': 'known_db',
                    'name': b.name or b.protocol
                }
            else:
                # Pass 2: Try full ML classifier
                ml_classification = None
                if classifier:
                    try:
                        ml_classification = classifier.classify(
                            wallet.address, chain_trigram, save_result=True
                        )
                        if ml_classification.get('predicted_type') == 'unknown':
                            ml_classification = None
                    except Exception:
                        ml_classification = None
                
                if ml_classification and ml_classification.get('confidence', 0) > 0.5:
                    classification = {
                        'predicted_type': ml_classification['predicted_type'],
                        'confidence': ml_classification['confidence'],
                        'source': 'ml_classifier'
                    }
                else:
                    # Pass 3: Heuristic from InvestigationTransfer data
                    classification = _classify_from_transfers(
                        session, wallet.address, investigation_id, wallet.chain_id
                    )
                    classification['source'] = 'transfer_heuristics'
            
            results.append({
                'address': wallet.address,
                'predicted_type': classification.get('predicted_type'),
                'confidence': classification.get('confidence'),
                'source': classification.get('source'),
                'current_role': wallet.role
            })
            
            if (wallet.role in ('related', 'suspect') and 
                classification.get('confidence', 0) >= 0.6 and
                classification.get('predicted_type') in ('exchange', 'bridge', 'mixer')):
                wallet.role = classification['predicted_type']
                wallet.is_flagged = True
                wallet.notes = (wallet.notes or '') + f" [auto-classified: {classification.get('source')}]"
                updated += 1
        
        session.commit()
        
        logger.info(f"Classified {len(wallets)} wallets for investigation {investigation_id}, "
                    f"{updated} roles updated")
        
        return {
            'status': 'success',
            'investigation_id': investigation_id,
            'wallets_classified': len(results),
            'roles_updated': updated,
            'results': results
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error classifying wallets: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()
