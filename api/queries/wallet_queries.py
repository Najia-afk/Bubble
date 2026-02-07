"""
Atomic DB queries for wallet scoring/classification data.
Each function takes a session, returns data. No business logic.
Pure SQLAlchemy ORM — zero raw SQL.
"""
from sqlalchemy import func, inspect as sa_inspect
from typing import Dict, List, Optional, Set
from datetime import datetime, timedelta

from api.application.erc20models import (
    WalletLabel, WalletScore, Token,
    CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID,
    get_transfer_event_class
)
from api.application.models import Mixer, Bridge


# ─── Wallet Labels ───────────────────────────────────────────────────────────

def get_wallet_labels(session, address: str, chain_id: int) -> List[WalletLabel]:
    return session.query(WalletLabel).filter(
        WalletLabel.address == address.lower(),
        WalletLabel.chain_id == chain_id
    ).all()


def get_trusted_labels(session, address: str, chain_id: int) -> List[WalletLabel]:
    return session.query(WalletLabel).filter(
        WalletLabel.address == address.lower(),
        WalletLabel.chain_id == chain_id,
        WalletLabel.is_trusted == True
    ).all()


def get_all_labels_by_type(session, label_types: List[str], min_confidence: float = 0.7) -> List[WalletLabel]:
    return session.query(WalletLabel).filter(
        WalletLabel.label_type.in_(label_types),
        WalletLabel.confidence >= min_confidence
    ).all()


# ─── Wallet Scores ───────────────────────────────────────────────────────────

def get_wallet_score(session, address: str, chain_id: int) -> Optional[WalletScore]:
    return session.query(WalletScore).filter_by(
        address=address.lower(), chain_id=chain_id
    ).first()


def get_scores_by_cluster(session, chain_id: int, cluster_id: int, limit: int = 50) -> List[WalletScore]:
    return session.query(WalletScore).filter(
        WalletScore.chain_id == chain_id,
        WalletScore.cluster_id == cluster_id
    ).limit(limit).all()


def get_all_scores(session, chain_id: int = None) -> List[WalletScore]:
    q = session.query(WalletScore)
    if chain_id:
        q = q.filter(WalletScore.chain_id == chain_id)
    return q.all()


# ─── Per-token transfer table queries ────────────────────────────────────────

def discover_transfer_tables(session, chain_trigram: str) -> List[str]:
    """Find all ERC20 transfer event tables for a chain using SQLAlchemy inspector."""
    try:
        inspector = sa_inspect(session.get_bind())
        all_tables = inspector.get_table_names()
        suffix = f'_{chain_trigram.lower()}_erc20_transfer_event'
        return [t for t in all_tables if t.endswith(suffix)]
    except Exception:
        return []


def get_token_transfer_features(session, address: str, chain_trigram: str) -> Optional[Dict]:
    """Extract basic features from per-token transfer tables using dynamic ORM classes.
    Returns dict with tx_count, tx_in/out, unique_counterparties, etc.
    Pure SQLAlchemy ORM — zero raw SQL.
    """
    # Discover dynamic ORM classes
    available_classes = []
    try:
        tokens = session.query(Token).filter(
            Token.trigram == chain_trigram.upper()
        ).all()
        
        inspector = sa_inspect(session.get_bind())
        existing_tables = set(inspector.get_table_names())
        
        for token in tokens:
            table_name = f"{token.symbol.lower()}_{chain_trigram.lower()}_erc20_transfer_event"
            if table_name in existing_tables:
                cls = get_transfer_event_class(token.symbol, chain_trigram)
                if cls:
                    available_classes.append(cls)
    except Exception:
        return None
    
    if not available_classes:
        return None

    address_lower = address.lower()
    total_tx_in = 0
    total_tx_out = 0
    total_value_in = 0.0
    total_value_out = 0.0
    max_value = 0.0
    counterparties = set()

    for cls in available_classes:
        try:
            # Incoming — pure ORM
            in_row = session.query(
                func.count(cls.id),
                func.coalesce(func.sum(cls.value), 0),
                func.coalesce(func.max(cls.value), 0),
            ).filter(
                func.lower(cls.to_contract_address) == address_lower
            ).first()

            if in_row and in_row[0]:
                total_tx_in += in_row[0]
                total_value_in += float(in_row[1] or 0) / 1e18
                max_value = max(max_value, float(in_row[2] or 0) / 1e18)
            
            in_senders = session.query(
                func.lower(cls.from_contract_address)
            ).filter(
                func.lower(cls.to_contract_address) == address_lower
            ).distinct().all()
            counterparties.update([r[0] for r in in_senders if r[0]])

            # Outgoing — pure ORM
            out_row = session.query(
                func.count(cls.id),
                func.coalesce(func.sum(cls.value), 0),
                func.coalesce(func.max(cls.value), 0),
            ).filter(
                func.lower(cls.from_contract_address) == address_lower
            ).first()

            if out_row and out_row[0]:
                total_tx_out += out_row[0]
                total_value_out += float(out_row[1] or 0) / 1e18
                max_value = max(max_value, float(out_row[2] or 0) / 1e18)
            
            out_receivers = session.query(
                func.lower(cls.to_contract_address)
            ).filter(
                func.lower(cls.from_contract_address) == address_lower
            ).distinct().all()
            counterparties.update([r[0] for r in out_receivers if r[0]])
        except Exception:
            continue

    total_tx = total_tx_in + total_tx_out
    if total_tx == 0:
        return None

    total_volume = total_value_in + total_value_out
    return {
        'tx_count': total_tx,
        'tx_in_count': total_tx_in,
        'tx_out_count': total_tx_out,
        'unique_counterparties': len(counterparties),
        'avg_tx_value': total_volume / total_tx,
        'max_tx_value': max_value,
        'total_volume': total_volume,
        'in_out_ratio': (total_tx_in / total_tx_out) if total_tx_out > 0 else 100.0,
        'active_days': 1,  # Needs timestamp data for accuracy
    }
