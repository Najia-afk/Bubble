# api/tasks/investigation_sync_tasks.py
"""
Celery tasks for syncing investigation transfer data from Etherscan v2 API.
"""
from celery import shared_task
from datetime import datetime, timedelta, timezone
import time
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from typing import List

from utils.database import get_session_factory
from utils.logging_config import setup_logging

import requests

from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationTransfer,
    Token, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID
)
from config.settings import Config
from scripts.src.fetch_erc20_info_coingecko import get_token_info
from scripts.src.fetch_erc20_price_history_coingecko import fetch_and_store_price_history

logger = setup_logging('investigation_tasks.log')

CHAIN_TO_PLATFORM = {
    'ETH': 'ethereum',
    'BSC': 'binance-smart-chain',
    'POL': 'polygon-pos',
    'BASE': 'base'
}


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


@shared_task(name='sync_investigation_transfers')
def sync_investigation_transfers(investigation_id: int, chains: List[str] = None):
    """Fetch ALL ERC20 token transfers for investigation wallets from Etherscan v2 API.
    
    This is the primary data fetching task. It grabs every token transfer 
    involving each tracked wallet address — no need to pre-register tokens.
    
    Rate-limited to ~4 requests/sec to stay within Etherscan free tier limits.
    """
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
        total_addresses = sum(len(addrs) for addrs in wallets_by_chain.values())
        processed = 0
        
        for trigram, addresses in wallets_by_chain.items():
            chain_id = TRIGRAM_TO_CHAIN_ID.get(trigram)
            if not chain_id:
                continue
            
            api_key = _get_scan_key(trigram)
            if not api_key:
                logger.warning(f"No API key for chain {trigram}, skipping")
                continue
            
            # Pre-load existing transfer keys for this chain to skip duplicates
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
                processed += 1
                logger.info(f"Syncing transfers for {address[:10]}... ({trigram}) [{processed}/{total_addresses}]")
                
                # Rate limit: ~4 req/sec for Etherscan free tier
                time.sleep(0.3)
                
                try:
                    url = (
                        f"https://api.etherscan.io/v2/api?chainid={chain_id}"
                        f"&module=account&action=tokentx&address={address}"
                        f"&startblock=0&endblock=99999999&sort=asc&apikey={api_key}"
                    )
                    resp = requests.get(url, timeout=30)
                    if resp.status_code != 200:
                        logger.warning(f"Etherscan returned {resp.status_code} for {address}")
                        continue
                    data = resp.json()
                    if data.get('status') != '1':
                        msg = data.get('message', 'unknown')
                        if 'rate limit' in msg.lower():
                            logger.warning(f"Rate limited, waiting 2s...")
                            time.sleep(2)
                        continue
                except requests.RequestException as e:
                    logger.warning(f"Request failed for {address}: {e}")
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
                    try:
                        timestamp = datetime.fromtimestamp(int(row.get('timeStamp')), tz=timezone.utc)
                    except (ValueError, TypeError):
                        timestamp = None
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
                        logger.info(f"  +{result.rowcount} transfers for {address[:10]}...")
        
        logger.info(f"Sync complete for investigation {investigation_id}: {total_added} transfers added")
        return {
            'status': 'success',
            'investigation_id': investigation_id,
            'transfers_added': total_added,
            'addresses_processed': processed
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error syncing transfers: {e}", exc_info=True)
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
