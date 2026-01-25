# api/tasks/investigation_tasks.py
"""
Celery tasks for forensic investigation automation.
Auto-follows fund flows from victim wallets across chains.
"""
from celery import shared_task
from datetime import datetime, timedelta
from sqlalchemy import text
from typing import List, Dict, Set

from utils.database import get_session_factory
from utils.logging_config import setup_logging
from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationToken,
    WalletLabel, KnownBridge, Base,
    CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID
)
from api.services.wallet_classifier import get_wallet_classifier

logger = setup_logging('investigation_tasks.log')


@shared_task(name='expand_investigation')
def expand_investigation(investigation_id: int, max_depth: int = 3, max_wallets: int = 100):
    """
    Auto-expand an investigation by following fund flows from tracked wallets.
    
    Args:
        investigation_id: ID of the investigation to expand
        max_depth: Maximum hops from victim wallets (default 3)
        max_wallets: Maximum total wallets to track (default 100)
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        # Get investigation
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            logger.error(f"Investigation {investigation_id} not found")
            return {'status': 'error', 'message': 'Investigation not found'}
        
        # Get current wallets
        current_wallets = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id
        ).all()
        
        if len(current_wallets) >= max_wallets:
            return {
                'status': 'complete',
                'message': f'Max wallets reached ({max_wallets})',
                'total_wallets': len(current_wallets)
            }
        
        # Find wallets at the frontier (not yet expanded)
        frontier_wallets = [
            w for w in current_wallets 
            if w.depth < max_depth and w.role != 'exchange'
        ]
        
        if not frontier_wallets:
            return {
                'status': 'complete',
                'message': 'No more wallets to expand',
                'total_wallets': len(current_wallets)
            }
        
        # Load known bridges and exchanges for detection
        known_bridges = {
            b.address.lower(): b 
            for b in session.query(KnownBridge).filter_by(is_active=True).all()
        }
        
        known_exchanges = {
            l.address.lower(): l 
            for l in session.query(WalletLabel).filter(
                WalletLabel.label_type == 'exchange'
            ).all()
        }
        
        # Get tokens being tracked
        tracked_tokens = session.query(InvestigationToken).filter_by(
            investigation_id=investigation_id
        ).all()
        
        # Track existing addresses to avoid duplicates
        existing_addresses = {(w.address.lower(), w.chain_id) for w in current_wallets}
        
        new_wallets_added = 0
        bridge_transactions = []
        exchange_hits = []
        
        # Process each frontier wallet
        for wallet in frontier_wallets:
            if len(existing_addresses) >= max_wallets:
                break
            
            chain_trigram = CHAIN_ID_TO_TRIGRAM.get(wallet.chain_id, 'ETH')
            
            # Find outgoing transfers from this wallet
            outgoing = _get_outgoing_transfers(
                session, 
                wallet.address, 
                chain_trigram,
                tracked_tokens
            )
            
            for transfer in outgoing:
                to_addr = transfer['to_address'].lower()
                
                # Skip if already tracked
                if (to_addr, wallet.chain_id) in existing_addresses:
                    continue
                
                # Determine role
                role = 'related'
                is_flagged = False
                
                if to_addr in known_exchanges:
                    role = 'exchange'
                    is_flagged = True
                    exchange_hits.append({
                        'address': to_addr,
                        'name': known_exchanges[to_addr].name_tag or known_exchanges[to_addr].label,
                        'amount': transfer['value'],
                        'from_wallet': wallet.address
                    })
                elif to_addr in known_bridges:
                    role = 'bridge'
                    is_flagged = True
                    bridge_transactions.append({
                        'address': to_addr,
                        'protocol': known_bridges[to_addr].protocol,
                        'direction': known_bridges[to_addr].direction,
                        'amount': transfer['value'],
                        'from_wallet': wallet.address
                    })
                
                # Add new wallet
                new_wallet = InvestigationWallet(
                    investigation_id=investigation_id,
                    address=to_addr,
                    chain_id=wallet.chain_id,
                    role=role,
                    depth=wallet.depth + 1,
                    parent_address=wallet.address,
                    total_received=transfer['value'],
                    is_flagged=is_flagged
                )
                session.add(new_wallet)
                existing_addresses.add((to_addr, wallet.chain_id))
                new_wallets_added += 1
                
                if len(existing_addresses) >= max_wallets:
                    break
        
        # Update investigation status
        investigation.status = 'in_progress'
        investigation.updated_at = datetime.utcnow()
        
        session.commit()
        
        result = {
            'status': 'success',
            'investigation_id': investigation_id,
            'new_wallets_added': new_wallets_added,
            'total_wallets': len(existing_addresses),
            'exchange_hits': len(exchange_hits),
            'bridge_transactions': len(bridge_transactions),
            'exchanges_found': exchange_hits[:10],  # First 10
            'bridges_found': bridge_transactions[:10]
        }
        
        logger.info(f"Expanded investigation {investigation_id}: +{new_wallets_added} wallets, "
                   f"{len(exchange_hits)} exchange hits, {len(bridge_transactions)} bridge txs")
        
        return result
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error expanding investigation {investigation_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


def _get_outgoing_transfers(session, address: str, chain_trigram: str, 
                           tracked_tokens: List[InvestigationToken]) -> List[Dict]:
    """Get outgoing transfers from an address for tracked tokens"""
    transfers = []
    address_lower = address.lower()
    
    # Query transfer tables for tracked tokens
    for token in tracked_tokens:
        if token.chain_id != TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1):
            continue
        
        symbol = token.symbol.lower() if token.symbol else 'ghst'
        table_name = f"{symbol}_{chain_trigram.lower()}_erc20_transfer_event"
        
        try:
            query = text(f"""
                SELECT to_contract_address, SUM(value) as total_value
                FROM {table_name}
                WHERE LOWER(from_contract_address) = :addr
                GROUP BY to_contract_address
                ORDER BY total_value DESC
                LIMIT 50
            """)
            
            result = session.execute(query, {'addr': address_lower})
            
            for row in result.fetchall():
                transfers.append({
                    'to_address': row[0],
                    'value': float(row[1] or 0) / 1e18,
                    'token_symbol': symbol.upper()
                })
                
        except Exception as e:
            logger.debug(f"Could not query table {table_name}: {e}")
            continue
    
    return transfers


@shared_task(name='classify_investigation_wallets')
def classify_investigation_wallets(investigation_id: int):
    """
    Run ML classification on all wallets in an investigation.
    Updates wallet_score table and suggests labels.
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        wallets = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id
        ).all()
        
        if not wallets:
            return {'status': 'error', 'message': 'No wallets in investigation'}
        
        classifier = get_wallet_classifier()
        results = []
        
        for wallet in wallets:
            chain_trigram = CHAIN_ID_TO_TRIGRAM.get(wallet.chain_id, 'ETH')
            
            classification = classifier.classify(
                wallet.address, 
                chain_trigram, 
                save_result=True
            )
            
            results.append({
                'address': wallet.address,
                'predicted_type': classification.get('predicted_type'),
                'confidence': classification.get('confidence'),
                'current_role': wallet.role
            })
            
            # Update wallet role if ML is confident and no existing role
            if (wallet.role == 'related' and 
                classification.get('confidence', 0) >= 0.7 and
                classification.get('predicted_type') in ['exchange', 'bridge', 'mixer']):
                wallet.role = classification['predicted_type']
                wallet.is_flagged = True
        
        session.commit()
        
        logger.info(f"Classified {len(wallets)} wallets for investigation {investigation_id}")
        
        return {
            'status': 'success',
            'investigation_id': investigation_id,
            'wallets_classified': len(results),
            'results': results
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error classifying wallets: {e}", exc_info=True)
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


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
            # By role
            role = wallet.role or 'unknown'
            wallet_by_role[role] = wallet_by_role.get(role, 0) + 1
            
            # By depth
            depth = wallet.depth
            wallet_by_depth[depth] = wallet_by_depth.get(depth, 0) + 1
            
            # Flagged
            if wallet.is_flagged:
                flagged_wallets.append({
                    'address': wallet.address,
                    'role': wallet.role,
                    'depth': wallet.depth,
                    'total_received': wallet.total_received
                })
            
            # Exchanges and bridges
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
            'flagged_wallets': flagged_wallets[:20],  # Top 20
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
