"""Verify graph API returns role + depth per node."""
import requests, json

r = requests.get("http://localhost:8080/api/investigations/5/graph?include_external=true")
d = r.json()

nodes = d.get('nodes', [])
print(f"Nodes: {len(nodes)}, Edges: {len(d.get('edges', []))}")

# Check a few nodes for role/depth
from collections import Counter
roles = Counter(n.get('role', 'MISSING') for n in nodes)
print(f"\nNode roles: {dict(roles)}")

has_depth = sum(1 for n in nodes if 'depth' in n)
print(f"Nodes with depth: {has_depth}/{len(nodes)}")

# Show case wallets
case_nodes = [n for n in nodes if n.get('is_case_wallet')]
print(f"\nCase wallets ({len(case_nodes)}):")
for n in case_nodes[:5]:
    print(f"  {n['id'][:12]}... role={n.get('role')} depth={n.get('depth')}")
