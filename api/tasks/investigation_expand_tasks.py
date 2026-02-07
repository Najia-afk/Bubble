# api/tasks/investigation_expand_tasks.py
"""
Celery tasks for expanding investigations — tracing fund flows and discovering wallets.
"""
from celery import shared_task
from datetime import datetime, timezone
from sqlalchemy import func
from typing import Dict, Set

from utils.database import get_session_factory
from utils.logging_config import setup_logging

from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationTransfer,
    WalletLabel, CHAIN_ID_TO_TRIGRAM
)
from api.application.models import Mixer, Bridge

logger = setup_logging('investigation_tasks.log')

# Roles that are "terminal" — don't expand beyond these
TERMINAL_ROLES = {'exchange', 'mixer', 'bridge'}

# Max counterparties before we consider a wallet "too busy" (exchange-like)
HIGH_COUNTERPARTY_THRESHOLD = 200


def _load_known_addresses(session) -> tuple:
    """Load known mixer, bridge, and labeled exchange addresses from DB.
    Returns (known_mixers: dict, known_bridges: dict, known_exchanges: dict)
    Each dict maps lowercase_address -> model instance.
    """
    known_mixers = {}
    known_bridges = {}
    known_exchanges = {}
    
    try:
        for m in session.query(Mixer).filter_by(is_active=True).all():
            known_mixers[m.address.lower()] = m
    except Exception as e:
        logger.warning(f"Could not load mixers: {e}")
    
    try:
        for b in session.query(Bridge).filter_by(is_active=True).all():
            known_bridges[b.address.lower()] = b
    except Exception as e:
        logger.warning(f"Could not load bridges: {e}")
    
    try:
        for label in session.query(WalletLabel).filter(
            WalletLabel.label_type.in_(['exchange', 'cex']),
            WalletLabel.confidence >= 0.7
        ).all():
            known_exchanges[label.address.lower()] = label
    except Exception as e:
        logger.warning(f"Could not load exchange labels: {e}")
    
    logger.info(f"Loaded known addresses: {len(known_mixers)} mixers, "
                f"{len(known_bridges)} bridges, {len(known_exchanges)} exchanges")
    return known_mixers, known_bridges, known_exchanges


def _determine_role(address: str, known_mixers: dict, known_bridges: dict, 
                    known_exchanges: dict, direction: str = 'outgoing') -> tuple:
    """Determine the role and flag status for a discovered address.
    Returns (role, is_flagged, entity_name).
    """
    addr = address.lower()
    
    if addr in known_exchanges:
        entity = known_exchanges[addr]
        name = getattr(entity, 'name_tag', None) or getattr(entity, 'label', 'exchange')
        return 'exchange', True, name
    
    if addr in known_mixers:
        m = known_mixers[addr]
        return 'mixer', True, m.name or m.protocol
    
    if addr in known_bridges:
        b = known_bridges[addr]
        return 'bridge', True, b.name or b.protocol
    
    if direction == 'incoming':
        return 'suspect', False, None
    
    return 'related', False, None


@shared_task(name='expand_investigation')
def expand_investigation(investigation_id: int, max_depth: int = 3, max_wallets: int = 100):
    """
    Auto-expand an investigation by analyzing InvestigationTransfer data.
    
    This is the core tracing algorithm:
    - For attacker/suspect wallets: trace OUTGOING (where did the money go?)
    - For victim wallets: trace INCOMING (who drained them?)  
    - Stop expanding at known exchanges, mixers, bridges (flag them)
    - Stop if a wallet has too many counterparties (exchange-like behavior)
    
    PREREQUISITE: Run sync_investigation_transfers first to fetch transfer data.
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            logger.error(f"Investigation {investigation_id} not found")
            return {'status': 'error', 'message': 'Investigation not found'}
        
        transfer_count = session.query(func.count(InvestigationTransfer.id)).filter_by(
            investigation_id=investigation_id
        ).scalar()
        
        if not transfer_count:
            return {
                'status': 'no_data',
                'message': 'No transfer data. Run sync_transfers first to fetch transactions from Etherscan.'
            }
        
        current_wallets = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id
        ).all()
        
        if len(current_wallets) >= max_wallets:
            return {
                'status': 'complete',
                'message': f'Max wallets reached ({max_wallets})',
                'total_wallets': len(current_wallets)
            }
        
        known_mixers, known_bridges, known_exchanges = _load_known_addresses(session)
        
        existing_addresses = {(w.address.lower(), w.chain_id) for w in current_wallets}
        wallet_lookup = {w.address.lower(): w for w in current_wallets}
        
        frontier_wallets = [
            w for w in current_wallets 
            if w.depth < max_depth and w.role not in TERMINAL_ROLES
        ]
        
        if not frontier_wallets:
            return {
                'status': 'complete',
                'message': 'No more wallets to expand (all at max depth or terminal)',
                'total_wallets': len(current_wallets)
            }
        
        new_wallets_added = 0
        exchange_hits = []
        mixer_hits = []
        bridge_hits = []
        
        for wallet in frontier_wallets:
            if len(existing_addresses) >= max_wallets:
                break
            
            addr_lower = wallet.address.lower()
            chain_id = wallet.chain_id
            
            # === TRACE OUTGOING: Where did money FROM this wallet go? ===
            outgoing = session.query(
                InvestigationTransfer.to_address,
                func.sum(InvestigationTransfer.value).label('total_value'),
                func.count(InvestigationTransfer.id).label('tx_count')
            ).filter(
                InvestigationTransfer.investigation_id == investigation_id,
                func.lower(InvestigationTransfer.from_address) == addr_lower,
                InvestigationTransfer.chain_id == chain_id
            ).group_by(
                InvestigationTransfer.to_address
            ).all()
            
            for to_addr, total_value, tx_count in outgoing:
                to_addr_lower = to_addr.lower()
                
                if (to_addr_lower, chain_id) in existing_addresses:
                    if to_addr_lower in wallet_lookup:
                        existing_w = wallet_lookup[to_addr_lower]
                        existing_w.total_received = (existing_w.total_received or 0) + (total_value or 0)
                    continue
                
                role, is_flagged, entity_name = _determine_role(
                    to_addr_lower, known_mixers, known_bridges, known_exchanges, 'outgoing'
                )
                
                new_wallet = InvestigationWallet(
                    investigation_id=investigation_id,
                    address=to_addr_lower,
                    chain_id=chain_id,
                    role=role,
                    depth=wallet.depth + 1,
                    parent_address=wallet.address,
                    total_received=total_value or 0,
                    is_flagged=is_flagged,
                    notes=f"Received from {addr_lower[:10]}... ({tx_count} txs)" + 
                          (f" [{entity_name}]" if entity_name else "")
                )
                session.add(new_wallet)
                existing_addresses.add((to_addr_lower, chain_id))
                wallet_lookup[to_addr_lower] = new_wallet
                new_wallets_added += 1
                
                if role == 'exchange':
                    exchange_hits.append({'address': to_addr_lower, 'name': entity_name, 
                                         'amount': total_value, 'from': addr_lower})
                elif role == 'mixer':
                    mixer_hits.append({'address': to_addr_lower, 'name': entity_name,
                                      'amount': total_value, 'from': addr_lower})
                elif role == 'bridge':
                    bridge_hits.append({'address': to_addr_lower, 'name': entity_name,
                                       'amount': total_value, 'from': addr_lower})
                
                if len(existing_addresses) >= max_wallets:
                    break
            
            # === TRACE INCOMING: Who sent money TO this wallet? ===
            if wallet.role in ('victim', 'attacker', 'theft_origin') and len(existing_addresses) < max_wallets:
                incoming = session.query(
                    InvestigationTransfer.from_address,
                    func.sum(InvestigationTransfer.value).label('total_value'),
                    func.count(InvestigationTransfer.id).label('tx_count')
                ).filter(
                    InvestigationTransfer.investigation_id == investigation_id,
                    func.lower(InvestigationTransfer.to_address) == addr_lower,
                    InvestigationTransfer.chain_id == chain_id
                ).group_by(
                    InvestigationTransfer.from_address
                ).all()
                
                for from_addr, total_value, tx_count in incoming:
                    from_addr_lower = from_addr.lower()
                    
                    if (from_addr_lower, chain_id) in existing_addresses:
                        continue
                    
                    role, is_flagged, entity_name = _determine_role(
                        from_addr_lower, known_mixers, known_bridges, known_exchanges, 'incoming'
                    )
                    
                    new_wallet = InvestigationWallet(
                        investigation_id=investigation_id,
                        address=from_addr_lower,
                        chain_id=chain_id,
                        role=role,
                        depth=wallet.depth + 1,
                        parent_address=wallet.address,
                        total_sent=total_value or 0,
                        is_flagged=is_flagged,
                        notes=f"Sent to {addr_lower[:10]}... ({tx_count} txs)" +
                              (f" [{entity_name}]" if entity_name else "")
                    )
                    session.add(new_wallet)
                    existing_addresses.add((from_addr_lower, chain_id))
                    wallet_lookup[from_addr_lower] = new_wallet
                    new_wallets_added += 1
                    
                    if role == 'exchange':
                        exchange_hits.append({'address': from_addr_lower, 'name': entity_name,
                                             'amount': total_value, 'direction': 'incoming'})
                    elif role == 'mixer':
                        mixer_hits.append({'address': from_addr_lower, 'name': entity_name,
                                          'amount': total_value, 'direction': 'incoming'})
                    
                    if len(existing_addresses) >= max_wallets:
                        break
        
        investigation.status = 'in_progress'
        investigation.updated_at = datetime.now(timezone.utc)
        
        session.commit()
        
        result = {
            'status': 'success',
            'investigation_id': investigation_id,
            'new_wallets_added': new_wallets_added,
            'total_wallets': len(existing_addresses),
            'transfer_data_used': transfer_count,
            'exchange_hits': exchange_hits[:10],
            'mixer_hits': mixer_hits[:10],
            'bridge_hits': bridge_hits[:10],
            'summary': {
                'exchanges_found': len(exchange_hits),
                'mixers_found': len(mixer_hits),
                'bridges_found': len(bridge_hits)
            }
        }
        
        logger.info(f"Expanded investigation {investigation_id}: +{new_wallets_added} wallets, "
                    f"{len(exchange_hits)} exchanges, {len(mixer_hits)} mixers, "
                    f"{len(bridge_hits)} bridges found")
        
        return result
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error expanding investigation {investigation_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


@shared_task(name='sync_and_expand')
def sync_and_expand(investigation_id: int, max_depth: int = 3, max_wallets: int = 100):
    """
    Full pipeline: sync transfers for all wallets, then expand, then sync new wallets.
    This is the "one-click investigate" task.
    """
    from api.tasks.investigation_sync_tasks import sync_investigation_transfers
    
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        iteration = 0
        total_new_wallets = 0
        total_transfers = 0
        
        while iteration < max_depth:
            iteration += 1
            logger.info(f"Investigation {investigation_id}: iteration {iteration}/{max_depth}")
            
            sync_result = sync_investigation_transfers(investigation_id)
            if sync_result.get('status') == 'error':
                return {'status': 'error', 'message': f"Sync failed: {sync_result.get('message')}", 
                        'iteration': iteration}
            
            transfers_added = sync_result.get('transfers_added', 0)
            total_transfers += transfers_added
            
            expand_result = expand_investigation(investigation_id, max_depth=max_depth, 
                                                 max_wallets=max_wallets)
            
            new_wallets = expand_result.get('new_wallets_added', 0)
            total_new_wallets += new_wallets
            
            logger.info(f"Iteration {iteration}: +{transfers_added} transfers, +{new_wallets} wallets")
            
            if new_wallets == 0:
                break
            if expand_result.get('total_wallets', 0) >= max_wallets:
                break
        
        return {
            'status': 'success',
            'investigation_id': investigation_id,
            'iterations': iteration,
            'total_new_wallets': total_new_wallets,
            'total_transfers_synced': total_transfers,
            'final_expand_result': expand_result
        }
        
    except Exception as e:
        logger.error(f"Error in sync_and_expand for investigation {investigation_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()
