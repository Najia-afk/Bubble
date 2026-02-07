"""
Atomic DB queries for investigation data.
Each function takes a session, returns data. No business logic.
"""
from sqlalchemy import func
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime, timezone

from api.application.erc20models import (
    Investigation, InvestigationWallet, InvestigationToken,
    InvestigationTransfer, WalletLabel, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID
)
from api.application.models import Mixer, Bridge


# ─── Investigation CRUD ──────────────────────────────────────────────────────

def get_investigation(session, investigation_id: int) -> Optional[Investigation]:
    return session.query(Investigation).filter_by(id=investigation_id).first()


def get_investigation_wallets(session, investigation_id: int) -> List[InvestigationWallet]:
    return session.query(InvestigationWallet).filter_by(
        investigation_id=investigation_id
    ).all()


def get_investigation_tokens(session, investigation_id: int) -> List[InvestigationToken]:
    return session.query(InvestigationToken).filter_by(
        investigation_id=investigation_id
    ).all()


def count_transfers(session, investigation_id: int) -> int:
    return session.query(func.count(InvestigationTransfer.id)).filter_by(
        investigation_id=investigation_id
    ).scalar() or 0


# ─── Wallet queries ──────────────────────────────────────────────────────────

def get_frontier_wallets(
    session, investigation_id: int, max_depth: int, terminal_roles: Set[str]
) -> List[InvestigationWallet]:
    """Get wallets eligible for expansion (not max depth, not terminal)."""
    return session.query(InvestigationWallet).filter(
        InvestigationWallet.investigation_id == investigation_id,
        InvestigationWallet.depth < max_depth,
        ~InvestigationWallet.role.in_(terminal_roles)
    ).all()


def get_existing_address_set(session, investigation_id: int) -> Set[Tuple[str, int]]:
    """Return set of (lowercase_address, chain_id) already in investigation."""
    wallets = session.query(
        InvestigationWallet.address, InvestigationWallet.chain_id
    ).filter_by(investigation_id=investigation_id).all()
    return {(w.address.lower(), w.chain_id) for w in wallets}


def wallet_address_lookup(session, investigation_id: int) -> Dict[str, InvestigationWallet]:
    """Return dict mapping lowercase address → InvestigationWallet."""
    wallets = get_investigation_wallets(session, investigation_id)
    return {w.address.lower(): w for w in wallets}


# ─── Transfer aggregation queries ────────────────────────────────────────────

def get_outgoing_aggregates(
    session, investigation_id: int, from_address: str, chain_id: int
) -> List[Tuple[str, float, int]]:
    """Aggregate outgoing transfers: (to_address, total_value, tx_count)."""
    return session.query(
        InvestigationTransfer.to_address,
        func.sum(InvestigationTransfer.value).label('total_value'),
        func.count(InvestigationTransfer.id).label('tx_count')
    ).filter(
        InvestigationTransfer.investigation_id == investigation_id,
        func.lower(InvestigationTransfer.from_address) == from_address.lower(),
        InvestigationTransfer.chain_id == chain_id
    ).group_by(
        InvestigationTransfer.to_address
    ).all()


def get_incoming_aggregates(
    session, investigation_id: int, to_address: str, chain_id: int
) -> List[Tuple[str, float, int]]:
    """Aggregate incoming transfers: (from_address, total_value, tx_count)."""
    return session.query(
        InvestigationTransfer.from_address,
        func.sum(InvestigationTransfer.value).label('total_value'),
        func.count(InvestigationTransfer.id).label('tx_count')
    ).filter(
        InvestigationTransfer.investigation_id == investigation_id,
        func.lower(InvestigationTransfer.to_address) == to_address.lower(),
        InvestigationTransfer.chain_id == chain_id
    ).group_by(
        InvestigationTransfer.from_address
    ).all()


def get_address_transfer_stats(
    session, investigation_id: int, address: str, chain_id: int
) -> Dict:
    """Get detailed transfer stats for a single address.
    Returns {out_count, out_total, unique_recipients, in_count, in_total, unique_senders}.
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

    return {
        'out_count': out_stats.count or 0,
        'out_total': float(out_stats.total or 0),
        'unique_recipients': out_stats.unique_recipients or 0,
        'in_count': in_stats.count or 0,
        'in_total': float(in_stats.total or 0),
        'unique_senders': in_stats.unique_senders or 0,
    }


def get_all_transfers_dataframe(session, investigation_id: int) -> List[Dict]:
    """Get all transfers as list of dicts (for Pandas/Plotly use in notebooks)."""
    transfers = session.query(InvestigationTransfer).filter_by(
        investigation_id=investigation_id
    ).order_by(InvestigationTransfer.timestamp).all()

    return [
        {
            'tx_hash': t.tx_hash,
            'chain_id': t.chain_id,
            'chain_code': t.chain_code,
            'block_number': t.block_number,
            'timestamp': t.timestamp,
            'from_address': t.from_address,
            'to_address': t.to_address,
            'token_symbol': t.token_symbol,
            'token_contract': t.token_contract,
            'value': t.value,
        }
        for t in transfers
    ]


def get_wallets_dataframe(session, investigation_id: int) -> List[Dict]:
    """Get all wallets as list of dicts (for Pandas/Plotly use in notebooks)."""
    wallets = get_investigation_wallets(session, investigation_id)
    return [
        {
            'address': w.address,
            'chain_id': w.chain_id,
            'role': w.role,
            'depth': w.depth,
            'parent_address': w.parent_address,
            'total_received': w.total_received,
            'total_sent': w.total_sent,
            'is_flagged': w.is_flagged,
            'notes': w.notes,
            'discovered_at': w.discovered_at,
        }
        for w in wallets
    ]


# ─── Existing transfer key lookups (for dedup during sync) ───────────────────

def get_existing_transfer_keys(
    session, investigation_id: int, chain_id: int
) -> Set[Tuple[str, str, str, str]]:
    """Return set of (tx_hash, from_address, to_address, token_contract) for dedup."""
    existing = session.query(
        InvestigationTransfer.tx_hash,
        InvestigationTransfer.from_address,
        InvestigationTransfer.to_address,
        InvestigationTransfer.token_contract
    ).filter_by(
        investigation_id=investigation_id,
        chain_id=chain_id
    ).all()
    return {(h[0], h[1], h[2], h[3]) for h in existing}


# ─── Token price backfill queries ────────────────────────────────────────────

def get_unique_token_contracts(session) -> List[Tuple]:
    """Get unique (token_contract, chain_code, min_ts, max_ts) from transfers."""
    return session.query(
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


# ─── Known address loaders ───────────────────────────────────────────────────

def load_known_addresses(session) -> Tuple[Dict, Dict, Dict]:
    """Load known mixer, bridge, exchange addresses from DB.
    Returns (known_mixers, known_bridges, known_exchanges) dicts.
    Each maps lowercase_address → ORM instance.
    """
    known_mixers = {}
    known_bridges = {}
    known_exchanges = {}

    try:
        for m in session.query(Mixer).filter_by(is_active=True).all():
            known_mixers[m.address.lower()] = m
    except Exception:
        pass

    try:
        for b in session.query(Bridge).filter_by(is_active=True).all():
            known_bridges[b.address.lower()] = b
    except Exception:
        pass

    try:
        for label in session.query(WalletLabel).filter(
            WalletLabel.label_type.in_(['exchange', 'cex']),
            WalletLabel.confidence >= 0.7
        ).all():
            known_exchanges[label.address.lower()] = label
    except Exception:
        pass

    return known_mixers, known_bridges, known_exchanges


# ─── Graph path queries ──────────────────────────────────────────────────────

def get_transfer_edges(session, investigation_id: int) -> List[Dict]:
    """Get edges for graph analysis: aggregated (from → to) with total value.
    Each edge = one unique (from, to, chain_id) with summed value and count.
    """
    edges = session.query(
        InvestigationTransfer.from_address,
        InvestigationTransfer.to_address,
        InvestigationTransfer.chain_id,
        func.sum(InvestigationTransfer.value).label('total_value'),
        func.count(InvestigationTransfer.id).label('tx_count'),
        func.min(InvestigationTransfer.timestamp).label('first_tx'),
        func.max(InvestigationTransfer.timestamp).label('last_tx'),
    ).filter_by(
        investigation_id=investigation_id
    ).group_by(
        InvestigationTransfer.from_address,
        InvestigationTransfer.to_address,
        InvestigationTransfer.chain_id
    ).all()

    return [
        {
            'from': e.from_address,
            'to': e.to_address,
            'chain_id': e.chain_id,
            'total_value': float(e.total_value or 0),
            'tx_count': e.tx_count,
            'first_tx': e.first_tx,
            'last_tx': e.last_tx,
        }
        for e in edges
    ]
