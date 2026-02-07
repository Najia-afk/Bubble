"""
Timeline Visualization API — Serves data for the vis.js timeline graph.

Endpoint: GET /api/investigations/<id>/timeline
Returns JSON suitable for vis.js Network or Timeline rendering.
"""
from typing import Dict, List
from collections import defaultdict
from datetime import datetime


def get_timeline_data(investigation_id: int, session) -> Dict:
    """
    Build timeline graph data for an investigation.
    
    Layout: X = timestamp (left=oldest, right=newest), Y = grouped by jump level.
    1000 wallets drained same 2 weeks → collapsed into one time bucket.
    
    Returns:
        {nodes: [...], edges: [...], groups: [...], stats: {...}}
    """
    from api.queries.investigation_queries import (
        get_investigation_wallets, get_transfer_edges, get_all_transfers_dataframe
    )
    from api.algorithms.path_analyzer import compute_jump_levels, build_adjacency

    wallets = get_investigation_wallets(session, investigation_id)
    edges = get_transfer_edges(session, investigation_id)

    if not wallets or not edges:
        return {'nodes': [], 'edges': [], 'groups': [], 'stats': {}}

    # Build address → wallet lookup
    wallet_map = {w.address.lower(): w for w in wallets}

    # Compute real jump levels (BFS from seeds)
    seed_addrs = [w.address for w in wallets if w.depth == 0]
    wallets_list = [{
        'address': w.address, 'role': w.role, 'depth': w.depth,
        'total_received': w.total_received, 'total_sent': w.total_sent
    } for w in wallets]
    jump_levels = compute_jump_levels(wallets_list, edges, seed_addrs)

    # Compute first-seen timestamp per address
    first_seen = {}
    for e in edges:
        ts = e.get('first_tx')
        if ts:
            for addr in [e['from'].lower(), e['to'].lower()]:
                if addr not in first_seen or ts < first_seen[addr]:
                    first_seen[addr] = ts

    # === BUILD VIS.JS NODES ===
    role_colors = {
        'attacker': '#d62728', 'theft_origin': '#d62728',
        'suspect': '#ff7f0e', 'victim': '#2ca02c',
        'exchange': '#1f77b4', 'mixer': '#9467bd',
        'bridge': '#8c564b', 'related': '#c7c7c7',
        'normal': '#bcbd22', 'unknown': '#e7e7e7',
    }
    role_shapes = {
        'attacker': 'triangle', 'theft_origin': 'triangle',
        'exchange': 'square', 'mixer': 'diamond',
        'bridge': 'hexagon', 'suspect': 'triangleDown',
        'victim': 'star',
    }

    nodes = []
    for w in wallets:
        addr = w.address.lower()
        level = jump_levels.get(addr, w.depth)
        ts = first_seen.get(addr)

        nodes.append({
            'id': addr,
            'label': f"{addr[:8]}...",
            'group': w.role or 'unknown',
            'level': level,
            'x': int(ts.timestamp() * 1000) if ts else 0,  # Milliseconds for vis.js
            'y': level * 150,  # Vertical spacing by jump level
            'color': role_colors.get(w.role, '#c7c7c7'),
            'shape': role_shapes.get(w.role, 'dot'),
            'size': max(8, min(30, (w.total_received or 0) / 100 + 8)),
            'title': (
                f"<b>{addr}</b><br>"
                f"Role: {w.role}<br>"
                f"Depth: {w.depth} | Jump level: {level}<br>"
                f"Received: {w.total_received or 0:.2f}<br>"
                f"Sent: {w.total_sent or 0:.2f}<br>"
                f"{'⚠️ FLAGGED' if w.is_flagged else ''}"
            ),
            'meta': {
                'address': w.address,
                'role': w.role,
                'depth': w.depth,
                'jump_level': level,
                'total_received': w.total_received or 0,
                'total_sent': w.total_sent or 0,
                'is_flagged': w.is_flagged,
                'first_seen': ts.isoformat() if ts else None,
            }
        })

    # === BUILD VIS.JS EDGES ===
    vis_edges = []
    for e in edges:
        vis_edges.append({
            'from': e['from'].lower(),
            'to': e['to'].lower(),
            'value': e.get('total_value', 0),
            'label': f"{e.get('total_value', 0):.2f}" if e.get('total_value', 0) > 1 else '',
            'title': (
                f"{e['from'][:8]}→{e['to'][:8]}<br>"
                f"Value: {e.get('total_value', 0):.4f}<br>"
                f"Txs: {e.get('tx_count', 0)}<br>"
                f"First: {e.get('first_tx', '')}<br>"
                f"Last: {e.get('last_tx', '')}"
            ),
            'width': max(0.5, min(5, (e.get('total_value', 0) or 0) / 1000)),
            'arrows': 'to',
            'color': {'opacity': 0.5},
        })

    # === BUILD GROUPS (for legend) ===
    role_counts = defaultdict(int)
    for w in wallets:
        role_counts[w.role or 'unknown'] += 1

    groups = [
        {
            'id': role,
            'label': f"{role} ({count})",
            'color': role_colors.get(role, '#c7c7c7'),
            'shape': role_shapes.get(role, 'dot'),
        }
        for role, count in sorted(role_counts.items(), key=lambda x: -x[1])
    ]

    # === STATS ===
    depth_dist = defaultdict(int)
    for w in wallets:
        depth_dist[jump_levels.get(w.address.lower(), w.depth)] += 1

    stats = {
        'total_nodes': len(nodes),
        'total_edges': len(vis_edges),
        'max_jump_level': max(jump_levels.values()) if jump_levels else 0,
        'depth_distribution': dict(depth_dist),
        'role_distribution': dict(role_counts),
    }

    return {
        'nodes': nodes,
        'edges': vis_edges,
        'groups': groups,
        'stats': stats,
    }
