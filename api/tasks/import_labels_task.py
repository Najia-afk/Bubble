# api/tasks/import_labels_task.py
"""
Celery tasks for importing wallet labels from eth-labels public API
API Docs: https://eth-labels-production.up.railway.app/swagger
"""
import requests
from celery import shared_task
from datetime import datetime
from sqlalchemy.dialects.postgresql import insert as pg_insert
from utils.database import get_session_factory
from utils.logging_config import setup_logging
from api.application.erc20models import WalletLabel, LabelType, KnownBridge, Base

logger = setup_logging('import_labels_task.log')

# eth-labels API base URL
ETH_LABELS_API = "https://eth-labels-production.up.railway.app"

# Chain IDs supported by eth-labels API
SUPPORTED_CHAINS = {
    1: 'ETH',      # Ethereum
    56: 'BSC',     # BNB Smart Chain
    137: 'POL',    # Polygon
    8453: 'BASE',  # Base
}

# Label types to import (priority order)
LABEL_TYPES_TO_IMPORT = [
    ('exchange', 'Centralized exchange wallet', '#4CAF50', 10),
    ('bridge', 'Cross-chain bridge contract', '#2196F3', 9),
    ('mixer', 'Mixing service or tumbler', '#F44336', 8),
    ('phishing', 'Known phishing/scam address', '#FF5722', 8),
    ('token', 'Token contract', '#9C27B0', 5),
    ('defi', 'DeFi protocol contract', '#00BCD4', 5),
    ('nft', 'NFT marketplace or contract', '#E91E63', 4),
    ('gambling', 'Gambling platform', '#FF9800', 4),
    ('mev', 'MEV bot or bundler', '#795548', 3),
    ('whale', 'High volume holder', '#607D8B', 2),
]

# Known bridge addresses (fallback if API doesn't have them)
KNOWN_BRIDGES_FALLBACK = [
    ('0x40ec5b33f54e0e8a33a975908c5ba1c14e5bbbdf', 1, 'polygon_bridge', 'ETH→POL', 'Polygon Bridge (ETH)'),
    ('0xa0c68c638235ee32657e8f720a23cec1bfc77c77', 137, 'polygon_bridge', 'POL→ETH', 'Polygon Bridge (POL)'),
    ('0x3ee18b2214aff97000d974cf647e7c347e8fa585', 1, 'wormhole', 'multi', 'Wormhole Token Bridge'),
    ('0x3a23f943181408eac424116af7b7790c94cb97a5', 1, 'stargate', 'multi', 'Stargate Router'),
    ('0xb8901acb165ed027e32754e0ffe830802919727f', 1, 'hop', 'multi', 'Hop Protocol'),
    ('0x88ad09518695c6c3712ac10a214be5109a655671', 137, 'hop', 'multi', 'Hop Protocol (POL)'),
    ('0x1231deb6f5749ef6ce6943a275a1d3e7486f4eae', 1, 'lifi', 'multi', 'LI.FI Diamond'),
    ('0xdef1c0ded9bec7f1a1670819833240f027b25eff', 1, 'zeroex', 'multi', '0x Exchange Proxy'),
]


def ensure_label_types(session):
    """Ensure all label types exist in the database"""
    for name, description, color, priority in LABEL_TYPES_TO_IMPORT:
        existing = session.query(LabelType).filter_by(name=name).first()
        if not existing:
            label_type = LabelType(
                name=name,
                description=description,
                color=color,
                priority=priority
            )
            session.add(label_type)
            logger.info(f"Created label type: {name}")
    session.commit()


def ensure_known_bridges(session):
    """Ensure known bridge addresses are in the database"""
    for address, chain_id, protocol, direction, name in KNOWN_BRIDGES_FALLBACK:
        existing = session.query(KnownBridge).filter_by(
            address=address.lower(),
            chain_id=chain_id
        ).first()
        if not existing:
            bridge = KnownBridge(
                address=address.lower(),
                chain_id=chain_id,
                protocol=protocol,
                direction=direction,
                name=name
            )
            session.add(bridge)
            logger.info(f"Added known bridge: {name} ({address[:10]}...)")
    session.commit()


def fetch_labels_from_api(chain_id: int, label: str, limit: int = 5000) -> list:
    """Fetch labels from eth-labels API for a specific chain and label type"""
    try:
        url = f"{ETH_LABELS_API}/accounts"
        params = {
            'chainId': str(chain_id),
            'label': label,
            'limit': str(limit)
        }
        
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        logger.info(f"Fetched {len(data)} {label} addresses for chain {chain_id}")
        return data
        
    except requests.RequestException as e:
        logger.error(f"Error fetching {label} for chain {chain_id}: {e}")
        return []


def upsert_wallet_labels(session, labels_data: list, chain_id: int, label_type: str):
    """Upsert wallet labels into the database"""
    if not labels_data:
        return 0
    
    inserted = 0
    for item in labels_data:
        address = item.get('address', '').lower()
        label = item.get('label', '') or item.get('nameTag', '') or label_type
        name_tag = item.get('nameTag', '')
        
        if not address or len(address) != 42:
            continue
        
        # Check if exists
        existing = session.query(WalletLabel).filter_by(
            address=address,
            chain_id=chain_id,
            label=label
        ).first()
        
        if existing:
            # Update if from API and not manually trusted
            if existing.source == 'api' and not existing.is_trusted:
                existing.name_tag = name_tag or existing.name_tag
                existing.updated_at = datetime.utcnow()
        else:
            # Insert new
            wallet_label = WalletLabel(
                address=address,
                chain_id=chain_id,
                label=label,
                label_type=label_type,
                name_tag=name_tag,
                source='api',
                confidence=1.0,
                is_trusted=False
            )
            session.add(wallet_label)
            inserted += 1
    
    session.commit()
    return inserted


@shared_task(name='import_labels_from_api')
def import_labels_from_api(chain_ids: list = None, label_types: list = None):
    """
    Import wallet labels from eth-labels public API
    
    Args:
        chain_ids: List of chain IDs to import (default: all supported)
        label_types: List of label types to import (default: exchange, bridge, mixer)
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        # Ensure tables exist
        Base.metadata.create_all(session.get_bind())
        
        # Ensure label types exist
        ensure_label_types(session)
        
        # Ensure known bridges exist
        ensure_known_bridges(session)
        
        # Default chains and labels
        if chain_ids is None:
            chain_ids = list(SUPPORTED_CHAINS.keys())
        
        if label_types is None:
            label_types = ['exchange', 'bridge', 'mixer', 'phishing']
        
        results = {}
        total_imported = 0
        
        for chain_id in chain_ids:
            chain_name = SUPPORTED_CHAINS.get(chain_id, f'Chain_{chain_id}')
            results[chain_name] = {}
            
            for label_type in label_types:
                logger.info(f"Importing {label_type} labels for {chain_name} (chain_id={chain_id})...")
                
                # Fetch from API
                labels_data = fetch_labels_from_api(chain_id, label_type)
                
                # Upsert to database
                imported = upsert_wallet_labels(session, labels_data, chain_id, label_type)
                
                results[chain_name][label_type] = {
                    'fetched': len(labels_data),
                    'imported': imported
                }
                total_imported += imported
                
                logger.info(f"✓ {chain_name}/{label_type}: fetched={len(labels_data)}, imported={imported}")
        
        logger.info(f"Label import completed. Total new labels: {total_imported}")
        
        return {
            'status': 'success',
            'total_imported': total_imported,
            'results': results
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error importing labels: {e}", exc_info=True)
        return {
            'status': 'error',
            'message': str(e)
        }
    finally:
        session.close()


@shared_task(name='import_labels_for_address')
def import_labels_for_address(address: str):
    """
    Import labels for a specific address from eth-labels API
    Useful for on-demand lookup during investigations
    """
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        url = f"{ETH_LABELS_API}/labels/{address.lower()}"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        data = response.json()
        
        if not data:
            return {'status': 'not_found', 'address': address}
        
        imported = 0
        for item in data:
            chain_id = int(item.get('chainId', 1))
            label = item.get('label', '')
            name_tag = item.get('nameTag', '')
            
            existing = session.query(WalletLabel).filter_by(
                address=address.lower(),
                chain_id=chain_id,
                label=label
            ).first()
            
            if not existing:
                wallet_label = WalletLabel(
                    address=address.lower(),
                    chain_id=chain_id,
                    label=label,
                    name_tag=name_tag,
                    source='api',
                    confidence=1.0
                )
                session.add(wallet_label)
                imported += 1
        
        session.commit()
        
        return {
            'status': 'success',
            'address': address,
            'labels_found': len(data),
            'imported': imported
        }
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error importing labels for {address}: {e}")
        return {
            'status': 'error',
            'address': address,
            'message': str(e)
        }
    finally:
        session.close()
