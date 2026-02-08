"""Check investigation 5 (GANA) numbers via the GraphQL + REST APIs — no raw SQL."""
import requests
import json
from collections import Counter

BASE = "http://localhost:8080"

# 1. Investigation metadata via REST
print("=== INVESTIGATION 5 METADATA ===")
r = requests.get(f"{BASE}/api/investigations/5")
d = r.json()
wallets = d.get('wallets', [])
print(f"Status: {d.get('status')}")
print(f"Case: {d.get('case_number', '?')} - {d.get('case_title', d.get('title', '?'))}")
print(f"Wallets registered: {len(wallets)}")

types = Counter(w.get('wallet_type', w.get('role', '?')) for w in wallets)
for k, v in types.items():
    print(f"  {k}: {v}")

# 2. Graph API — same endpoint the UI calls
print("\n=== GRAPH API (include_external=true) ===")
r = requests.get(f"{BASE}/api/investigations/5/graph?include_external=true")
g = r.json()
stats = g.get('stats', {})
nodes = g.get('nodes', [])
edges = g.get('edges', [])
print(f"Nodes: {len(nodes):,}")
print(f"Edges: {len(edges):,}")
print(f"Stats from API: {json.dumps(stats, indent=2)}")

# 3. Volume calculation
total_volume = sum(e.get('value', 0) for e in edges)
print(f"\nTotal volume (sum of edge values): {total_volume:,.2f}")
print(f"  Displayed as B: {total_volume / 1e9:.2f}B")

# 4. Check value distribution
values = sorted([e.get('value', 0) for e in edges], reverse=True)
print(f"\nTop 10 largest transfer values:")
for v in values[:10]:
    print(f"  {v:,.2f}")

print(f"\nSmallest 5 non-zero values:")
nonzero = [v for v in values if v > 0]
for v in nonzero[-5:]:
    print(f"  {v:.10f}")

zero_count = sum(1 for v in values if v == 0)
print(f"\nZero-value transfers: {zero_count:,}")

# 5. Check if values look like raw wei (not normalised)
huge = [v for v in values if v > 1e12]
print(f"\nValues > 1 trillion: {len(huge):,}")
if huge:
    print("  WARNING: These look like raw wei values, not normalised!")
    for v in huge[:5]:
        print(f"    raw={v:.4e}  if_wei_to_ETH={v/1e18:.4f}")

# 6. Token distribution in edges
tokens = Counter(e.get('token', 'unknown') for e in edges)
print(f"\nToken distribution in edges:")
for k, v in tokens.most_common(10):
    print(f"  {k}: {v:,} edges")

# 7. GraphQL — wallet features for a sample wallet
print("\n=== GRAPHQL - WALLET FEATURES ===")
if wallets:
    sample = wallets[0].get('address', '')
    gql_query = {
        "query": """
        query($addr: String!, $invId: Int) {
            walletFeatures(address: $addr, investigationId: $invId) {
                address txCount uniqueCounterparties avgTxValue maxTxValue
                inOutRatio totalVolume outCount inCount
            }
        }
        """,
        "variables": {"addr": sample, "invId": 5}
    }
    r = requests.post(f"{BASE}/graphql", json=gql_query)
    print(f"Sample wallet: {sample[:10]}...")
    print(json.dumps(r.json(), indent=2))

# 8. GraphQL — investigation wallets
print("\n=== GRAPHQL - INVESTIGATION WALLETS ===")
gql_query = {
    "query": """
    query($invId: Int) {
        investigationWallets(investigationId: $invId) {
            address role depth totalReceived totalSent isFlagged
        }
    }
    """,
    "variables": {"invId": 5}
}
r = requests.post(f"{BASE}/graphql", json=gql_query)
iw_data = r.json()
iw_wallets = iw_data.get('data', {}).get('investigationWallets', [])
print(f"Investigation wallets from GraphQL: {len(iw_wallets)}")
roles = Counter(w.get('role', '?') for w in iw_wallets)
for k, v in roles.items():
    print(f"  {k}: {v}")

print("\n=== SUMMARY ===")
print(f"Case wallets: {len(wallets)}")
print(f"Graph nodes: {len(nodes):,}")
print(f"Graph edges: {len(edges):,}")
print(f"Volume: {total_volume:,.2f}")
print(f"Values > 1T (possible raw wei): {len(huge):,}")
