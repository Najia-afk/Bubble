# api/tasks/investigation_tasks.py
"""
Celery tasks for forensic investigation automation.
Auto-follows fund flows from victim wallets across chains.
"""
from celery import shared_task
from datetime import datetime, timedelta
import time
from sqlalchemy import text, func
from sqlalchemy.dialects.postgresql import insert
from typing import List, Dict, Set

from utils.database import get_session_factory
from utils.logging_config import setup_logging
import requests

from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationToken, InvestigationTransfer,
    CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID
)
from api.application.erc20models import Token
from config.settings import Config
from api.services.wallet_classifier import get_wallet_classifier
from scripts.src.fetch_erc20_info_coingecko import get_token_info
from scripts.src.fetch_erc20_price_history_coingecko import fetch_and_store_price_history

logger = setup_logging('investigation_tasks.log')

CHAIN_TO_PLATFORM = {
    'ETH': 'ethereum',
    'BSC': 'binance-smart-chain',
    'POL': 'polygon-pos',
    'BASE': 'base'
}


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
        
        # Load known bridges and exchanges from core DB
        known_bridges = {}
        known_exchanges = {}
        
        # Get tokens being tracked
        tracked_tokens = session.query(InvestigationToken).filter_by(
            investigation_id=investigation_id
        ).all()
        if not tracked_tokens:
            return {
                'status': 'no_tokens',
                'message': 'No tokens tracked for this investigation'
            }
        
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


@shared_task(name='sync_investigation_transfers')
def sync_investigation_transfers(investigation_id: int, chains: List[str] = None):
    """Fetch transfers involving investigation wallets and store in DB."""
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            return {'status': 'error', 'message': 'Investigation not found'}
        
        InvestigationTransfer.__table__.create(session.get_bind(), checkfirst=True)
        
        wallets = session.query(InvestigationWallet).filter_by(investigation_id=investigation_id).all()
        if not wallets:
            return {'status': 'error', 'message': 'No wallets in investigation'}
        
        chain_filter = {c.upper() for c in chains} if chains else None
        wallets_by_chain = {}
        for w in wallets:
            trigram = CHAIN_ID_TO_TRIGRAM.get(w.chain_id)
            if not trigram:
                continue
            if chain_filter and trigram not in chain_filter:
                continue
            wallets_by_chain.setdefault(trigram, []).append(w.address.lower())
        
        total_added = 0
        for trigram, addresses in wallets_by_chain.items():
            chain_id = TRIGRAM_TO_CHAIN_ID.get(trigram)
            if not chain_id:
                continue
            
            api_key = _get_scan_key(trigram)
            if not api_key:
                continue
            
            existing = session.query(
                InvestigationTransfer.tx_hash,
                InvestigationTransfer.from_address,
                InvestigationTransfer.to_address,
                InvestigationTransfer.token_contract
            ).filter_by(
                investigation_id=investigation_id,
                chain_id=chain_id
            ).all()
            existing_keys = {(h[0], h[1], h[2], h[3]) for h in existing}
            
            for address in addresses:
                url = (
                    f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                    f"&module=account&action=tokentx&address={address}"
                    f"&startblock=0&endblock=99999999&sort=asc&apikey={api_key}"
                )
                resp = requests.get(url, timeout=30)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                if data.get('status') != '1':
                    continue
                
                rows_to_insert = []
                for row in data.get('result', []):
                    tx_hash = row.get('hash')
                    if not tx_hash:
                        continue
                    from_addr = row.get('from', '').lower()
                    to_addr = row.get('to', '').lower()
                    token_contract = row.get('contractAddress', '').lower()
                    unique_key = (tx_hash, from_addr, to_addr, token_contract)
                    if unique_key in existing_keys:
                        continue
                    token_symbol = (row.get('tokenSymbol') or '').lower()
                    value_raw = row.get('value')
                    decimals = int(row.get('tokenDecimal') or 0)
                    value = None
                    try:
                        value = float(value_raw) / (10 ** decimals) if value_raw is not None else None
                    except Exception:
                        value = None
                    timestamp = datetime.utcfromtimestamp(int(row.get('timeStamp')))
                    block_number = int(row.get('blockNumber')) if row.get('blockNumber') else None
                    
                    rows_to_insert.append({
                        'investigation_id': investigation_id,
                        'chain_id': chain_id,
                        'chain_code': trigram,
                        'tx_hash': tx_hash,
                        'block_number': block_number,
                        'timestamp': timestamp,
                        'from_address': from_addr,
                        'to_address': to_addr,
                        'token_symbol': token_symbol,
                        'token_contract': token_contract,
                        'value': value,
                        'value_raw': value_raw,
                        'token_decimals': decimals,
                    })
                    existing_keys.add(unique_key)

                if rows_to_insert:
                    insert_stmt = insert(InvestigationTransfer).values(rows_to_insert)
                    insert_stmt = insert_stmt.on_conflict_do_nothing(
                        index_elements=[
                            'investigation_id',
                            'chain_id',
                            'tx_hash',
                            'from_address',
                            'to_address',
                            'token_contract'
                        ]
                    )
                    result = session.execute(insert_stmt)
                    session.commit()
                    if result.rowcount:
                        total_added += result.rowcount
        
        return {
            'status': 'success',
            'investigation_id': investigation_id,
            'transfers_added': total_added
        }
        
    except Exception as e:
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


@shared_task(name='backfill_token_prices_for_transfers')
def backfill_token_prices_for_transfers(max_days: int = 120):
    """Backfill token metadata and price history for contracts seen in investigation transfers."""
    SessionFactory = get_session_factory()
    session = SessionFactory()

    try:
        rows = session.query(
            InvestigationTransfer.token_contract,
            InvestigationTransfer.chain_code,
            func.min(InvestigationTransfer.timestamp),
            func.max(InvestigationTransfer.timestamp)
        ).filter(
            InvestigationTransfer.token_contract.isnot(None)
        ).group_by(
            InvestigationTransfer.token_contract,
            InvestigationTransfer.chain_code
        ).all()

        results = {
            'processed': 0,
            'price_history_updated': 0,
            'token_created': 0,
            'skipped': 0,
            'errors': []
        }

        for contract_address, chain_code, min_ts, max_ts in rows:
            results['processed'] += 1
            if not contract_address or not chain_code or not min_ts or not max_ts:
                results['skipped'] += 1
                continue

            chain_code = chain_code.upper()
            asset_platform_id = CHAIN_TO_PLATFORM.get(chain_code)
            if not asset_platform_id:
                results['skipped'] += 1
                continue

            contract_address = contract_address.lower()
            token = session.query(Token).filter_by(contract_address=contract_address).first()
            if not token:
                token_data = get_token_info(asset_platform_id, contract_address)
                if token_data:
                    token_data['trigram'] = chain_code
                    token = Token(**token_data)
                    session.add(token)
                    session.commit()
                    results['token_created'] += 1
                else:
                    results['skipped'] += 1
                    continue

            from_ts = int(min_ts.timestamp())
            to_ts = int(max_ts.timestamp())
            if max_days:
                cap_from = int((max_ts - timedelta(days=max_days)).timestamp())
                from_ts = max(from_ts, cap_from)

            try:
                if fetch_and_store_price_history(contract_address, asset_platform_id, from_ts, to_ts, session):
                    results['price_history_updated'] += 1
            except Exception as e:
                results['errors'].append(f"{contract_address}:{chain_code}:{e}")

            session.commit()
            time.sleep(1)

        return {'status': 'success', **results}

    except Exception as e:
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


def _get_scan_key(trigram: str) -> str:
    if trigram == 'ETH':
        return Config.ETHERSCAN_API_KEY
    if trigram == 'BSC':
        return Config.BSCSCAN_API_KEY
    if trigram == 'POL':
        return Config.POLYGONSCAN_API_KEY
    if trigram == 'BASE':
        return Config.BASESCAN_API_KEY
    return Config.ETHERSCAN_API_KEY


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
