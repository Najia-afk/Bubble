"""
Graph Tracing Algorithm — Pure fund-flow expansion logic.

Takes transfer aggregates and known addresses as input, 
returns new wallets to add. No DB access.

This is the CORE of the investigation: given a set of wallets and their
transfer summaries, compute which new wallets to track.
"""
from typing import Dict, List, Set, Tuple, Optional


# Roles that are "terminal" — don't expand beyond these
TERMINAL_ROLES = frozenset({'exchange', 'mixer', 'bridge'})

# Max counterparties before we consider a wallet "too busy" (exchange-like)
HIGH_COUNTERPARTY_THRESHOLD = 200


def determine_role(
    address: str,
    known_mixers: Set[str],
    known_bridges: Set[str],
    known_exchanges: Set[str],
    direction: str = 'outgoing'
) -> Tuple[str, bool]:
    """
    Determine the role and flag status for a discovered address.
    
    Args:
        address: Lowercase address to classify
        known_mixers: Set of known mixer addresses (lowercase)
        known_bridges: Set of known bridge addresses (lowercase)
        known_exchanges: Set of known exchange addresses (lowercase)
        direction: 'outgoing' or 'incoming' — context of how we found this address
        
    Returns:
        (role, is_flagged)
    """
    addr = address.lower()

    if addr in known_exchanges:
        return 'exchange', True
    if addr in known_mixers:
        return 'mixer', True
    if addr in known_bridges:
        return 'bridge', True

    # Incoming sender to a victim could be the attacker
    if direction == 'incoming':
        return 'suspect', False

    return 'related', False


def compute_expansion(
    frontier_wallets: List[Dict],
    outgoing_map: Dict[str, List[Dict]],
    incoming_map: Dict[str, List[Dict]],
    existing_addresses: Set[Tuple[str, int]],
    known_mixers: Set[str],
    known_bridges: Set[str],
    known_exchanges: Set[str],
    max_wallets: int = 100,
    trace_incoming_roles: Set[str] = None,
) -> List[Dict]:
    """
    Core graph expansion algorithm. Pure function.
    
    Args:
        frontier_wallets: List of dicts with {address, chain_id, depth, role}
        outgoing_map: {address: [{to_address, total_value, tx_count}, ...]}
        incoming_map: {address: [{from_address, total_value, tx_count}, ...]}
        existing_addresses: Set of (address, chain_id) already tracked
        known_mixers/bridges/exchanges: Sets of known addresses (lowercase)
        max_wallets: Max total wallets to track
        trace_incoming_roles: Wallet roles for which to trace incoming (default: victim, attacker, theft_origin)
        
    Returns:
        List of new wallet dicts: {address, chain_id, role, depth, parent_address, 
                                    total_received, total_sent, is_flagged, notes}
    """
    if trace_incoming_roles is None:
        trace_incoming_roles = {'victim', 'attacker', 'theft_origin'}

    new_wallets = []
    seen = set(existing_addresses)

    for wallet in frontier_wallets:
        if len(seen) >= max_wallets:
            break

        addr = wallet['address'].lower()
        chain_id = wallet['chain_id']
        depth = wallet['depth']

        # === TRACE OUTGOING ===
        for tx in outgoing_map.get(addr, []):
            if len(seen) >= max_wallets:
                break
            to_addr = tx['to_address'].lower()
            if (to_addr, chain_id) in seen:
                continue

            role, is_flagged = determine_role(
                to_addr, known_mixers, known_bridges, known_exchanges, 'outgoing'
            )
            new_wallets.append({
                'address': to_addr,
                'chain_id': chain_id,
                'role': role,
                'depth': depth + 1,
                'parent_address': addr,
                'total_received': tx.get('total_value', 0),
                'total_sent': 0,
                'is_flagged': is_flagged,
                'notes': f"Received from {addr[:10]}... ({tx.get('tx_count', 0)} txs)",
                'direction': 'outgoing',
            })
            seen.add((to_addr, chain_id))

        # === TRACE INCOMING (only for attacker/victim roles) ===
        if wallet['role'] in trace_incoming_roles and len(seen) < max_wallets:
            for tx in incoming_map.get(addr, []):
                if len(seen) >= max_wallets:
                    break
                from_addr = tx['from_address'].lower()
                if (from_addr, chain_id) in seen:
                    continue

                role, is_flagged = determine_role(
                    from_addr, known_mixers, known_bridges, known_exchanges, 'incoming'
                )
                new_wallets.append({
                    'address': from_addr,
                    'chain_id': chain_id,
                    'role': role,
                    'depth': depth + 1,
                    'parent_address': addr,
                    'total_received': 0,
                    'total_sent': tx.get('total_value', 0),
                    'is_flagged': is_flagged,
                    'notes': f"Sent to {addr[:10]}... ({tx.get('tx_count', 0)} txs)",
                    'direction': 'incoming',
                })
                seen.add((from_addr, chain_id))

    return new_wallets


def classify_expansion_hits(new_wallets: List[Dict]) -> Dict:
    """Summarize what entities were found during expansion."""
    exchange_hits = [w for w in new_wallets if w['role'] == 'exchange']
    mixer_hits = [w for w in new_wallets if w['role'] == 'mixer']
    bridge_hits = [w for w in new_wallets if w['role'] == 'bridge']
    suspect_hits = [w for w in new_wallets if w['role'] == 'suspect']

    return {
        'exchanges_found': len(exchange_hits),
        'mixers_found': len(mixer_hits),
        'bridges_found': len(bridge_hits),
        'suspects_found': len(suspect_hits),
        'exchange_hits': exchange_hits[:10],
        'mixer_hits': mixer_hits[:10],
        'bridge_hits': bridge_hits[:10],
    }
