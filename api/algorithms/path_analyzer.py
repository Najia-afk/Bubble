"""
Path Analysis Algorithm — Analyze fund flow paths through a graph.

Pure functions. Input: edges + wallet metadata. Output: path statistics.
Used by both Celery tasks AND Jupyter notebooks.
"""
from typing import Dict, List, Set, Tuple, Optional
from collections import defaultdict, deque
from datetime import datetime, timedelta


def build_adjacency(edges: List[Dict]) -> Tuple[Dict, Dict]:
    """
    Build forward and reverse adjacency lists from transfer edges.
    
    Args:
        edges: List of {from, to, chain_id, total_value, tx_count, first_tx, last_tx}
        
    Returns:
        (forward_adj, reverse_adj) where each is {address: [{neighbor, value, count, first_tx, last_tx}, ...]}
    """
    forward = defaultdict(list)
    reverse = defaultdict(list)

    for e in edges:
        forward[e['from'].lower()].append({
            'neighbor': e['to'].lower(),
            'value': e.get('total_value', 0),
            'count': e.get('tx_count', 0),
            'first_tx': e.get('first_tx'),
            'last_tx': e.get('last_tx'),
            'chain_id': e.get('chain_id'),
        })
        reverse[e['to'].lower()].append({
            'neighbor': e['from'].lower(),
            'value': e.get('total_value', 0),
            'count': e.get('count', e.get('tx_count', 0)),
            'first_tx': e.get('first_tx'),
            'last_tx': e.get('last_tx'),
            'chain_id': e.get('chain_id'),
        })

    return dict(forward), dict(reverse)


def find_shortest_paths(
    forward_adj: Dict,
    source: str,
    max_depth: int = 10
) -> Dict[str, List[str]]:
    """
    BFS from source, returning shortest path (list of addresses) to each reachable node.
    
    Args:
        forward_adj: Forward adjacency list {addr: [{neighbor, ...}, ...]}
        source: Starting address (lowercase)
        max_depth: Max hops
        
    Returns:
        {target_address: [source, hop1, hop2, ..., target_address]}
    """
    paths = {source.lower(): [source.lower()]}
    visited = {source.lower()}
    queue = deque([(source.lower(), 0)])

    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for neighbor_data in forward_adj.get(current, []):
            neighbor = neighbor_data['neighbor']
            if neighbor not in visited:
                visited.add(neighbor)
                paths[neighbor] = paths[current] + [neighbor]
                queue.append((neighbor, depth + 1))

    return paths


def find_all_paths(
    forward_adj: Dict,
    source: str,
    target: str,
    max_depth: int = 6
) -> List[List[str]]:
    """
    Find ALL paths from source to target (DFS, bounded by max_depth).
    Warning: exponential in worst case. Use only for small graphs.
    """
    all_paths = []

    def dfs(current, path, visited):
        if len(path) > max_depth + 1:
            return
        if current == target.lower():
            all_paths.append(list(path))
            return
        for neighbor_data in forward_adj.get(current, []):
            neighbor = neighbor_data['neighbor']
            if neighbor not in visited:
                visited.add(neighbor)
                path.append(neighbor)
                dfs(neighbor, path, visited)
                path.pop()
                visited.remove(neighbor)

    src = source.lower()
    dfs(src, [src], {src})
    return all_paths


def compute_path_stats(
    wallets: List[Dict],
    edges: List[Dict],
    attacker_addresses: List[str]
) -> Dict:
    """
    Compute path analysis statistics for an investigation.
    
    Args:
        wallets: List of wallet dicts with {address, role, depth, ...}
        edges: List of edge dicts from get_transfer_edges
        attacker_addresses: List of known attacker addresses
        
    Returns:
        {max_depth, avg_depth, total_edges, terminal_wallets, 
         depth_distribution, role_by_depth, value_by_depth}
    """
    forward_adj, reverse_adj = build_adjacency(edges)

    # Depth distribution
    depth_dist = defaultdict(int)
    role_by_depth = defaultdict(lambda: defaultdict(int))
    value_by_depth = defaultdict(float)

    for w in wallets:
        d = w.get('depth', 0)
        depth_dist[d] += 1
        role_by_depth[d][w.get('role', 'unknown')] += 1
        value_by_depth[d] += (w.get('total_received', 0) or 0) + (w.get('total_sent', 0) or 0)

    # Terminal wallets (those with no outgoing edges in our data)
    wallet_addrs = {w['address'].lower() for w in wallets}
    terminal = [
        w['address'] for w in wallets
        if w['address'].lower() not in forward_adj or
        all(n['neighbor'] not in wallet_addrs for n in forward_adj.get(w['address'].lower(), []))
    ]

    # Shortest paths from each attacker
    path_lengths = {}
    for attacker in attacker_addresses:
        paths = find_shortest_paths(forward_adj, attacker.lower(), max_depth=10)
        for addr, path in paths.items():
            if addr not in path_lengths or len(path) < path_lengths[addr]:
                path_lengths[addr] = len(path) - 1  # Hops, not nodes

    return {
        'max_depth': max(depth_dist.keys()) if depth_dist else 0,
        'avg_depth': sum(d * c for d, c in depth_dist.items()) / max(sum(depth_dist.values()), 1),
        'total_edges': len(edges),
        'total_wallets': len(wallets),
        'terminal_wallets': len(terminal),
        'depth_distribution': dict(depth_dist),
        'role_by_depth': {d: dict(roles) for d, roles in role_by_depth.items()},
        'value_by_depth': dict(value_by_depth),
        'path_lengths': path_lengths,
    }


def compute_jump_levels(
    wallets: List[Dict],
    edges: List[Dict],
    seed_addresses: List[str]
) -> Dict[str, int]:
    """
    Compute actual jump level (BFS distance from any seed) for each wallet.
    Different from 'depth' which is the discovery order.
    
    Returns: {address: jump_level}
    """
    forward_adj, _ = build_adjacency(edges)
    
    # BFS from all seeds simultaneously
    levels = {}
    queue = deque()
    for seed in seed_addresses:
        s = seed.lower()
        levels[s] = 0
        queue.append((s, 0))
    
    while queue:
        current, level = queue.popleft()
        for neighbor_data in forward_adj.get(current, []):
            neighbor = neighbor_data['neighbor']
            if neighbor not in levels:
                levels[neighbor] = level + 1
                queue.append((neighbor, level + 1))
    
    return levels
