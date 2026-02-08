"""Audit wallet roles in both CaseWallet and InvestigationWallet, plus pricing."""
import requests, json
from collections import Counter

BASE = "http://localhost:8080"

# 1. Check CaseWallet roles for ALL cases
print("=== CASE WALLETS (from case_wallet table via REST) ===")
for case_id in ['CASE-2026-001','CASE-2026-002','CASE-2026-003','CASE-2026-004','CASE-2026-005','CASE-2026-006','CASE-2026-007','CASE-2026-008']:
    r = requests.get(f"{BASE}/api/cases/{case_id}")
    d = r.json()
    addrs = d.get('addresses', d.get('wallets', []))
    roles = Counter(w.get('role','?') for w in addrs)
    print(f"  {case_id}: {len(addrs)} wallets, roles={dict(roles)}")

# 2. Check InvestigationWallet roles via GraphQL
print("\n=== INVESTIGATION WALLETS (from investigation_wallet via GraphQL) ===")
for inv_id in range(1, 9):
    gql = {
        "query": """query($invId: Int) {
            investigationWallets(investigationId: $invId) { address role depth }
        }""",
        "variables": {"invId": inv_id}
    }
    r = requests.post(f"{BASE}/graphql", json=gql)
    wallets = r.json().get('data', {}).get('investigationWallets', [])
    roles = Counter(w['role'] for w in wallets)
    print(f"  inv_id={inv_id}: {len(wallets)} wallets, roles={dict(roles)}")

# 3. Check what role counts the cases API returns  
print("\n=== CASES API RESPONSE (role counts) ===")
r = requests.get(f"{BASE}/api/cases")
for c in r.json()['cases']:
    loss = c.get('total_stolen_usd') or 0
    inv_loss = c.get('investigation_reported_loss_usd')
    print(f"  {c['case_id']}: victims={c['victim_wallet_count']} attackers={c['attacker_wallet_count']} "
          f"exchanges={c['exchange_wallet_count']} bridges={c['bridge_wallet_count']} mixers={c['mixer_wallet_count']} "
          f"loss=${loss:,.0f} inv_loss={'$'+format(inv_loss,',.0f') if inv_loss else 'None'}")

# 4. Check the role-counting logic
print("\n=== ROLE CLASSIFICATION SETS ===")
victim_roles = {'victim', 'theft_origin'}
attacker_roles = {'attacker', 'hacker', 'scammer', 'exploiter', 'thief', 'suspect'}
exchange_roles = {'exchange', 'cex', 'dex'}
bridge_roles = {'bridge', 'cross_chain'}
mixer_roles = {'mixer', 'tornado', 'tumbler', 'privacy'}

# Show what roles exist in investigation_wallets
print("\nAll unique roles across ALL investigations:")
all_roles = set()
for inv_id in range(1, 9):
    gql = {
        "query": """query($invId: Int) {
            investigationWallets(investigationId: $invId) { role }
        }""",
        "variables": {"invId": inv_id}
    }
    r = requests.post(f"{BASE}/graphql", json=gql)
    for w in r.json().get('data', {}).get('investigationWallets', []):
        all_roles.add(w['role'])

for role in sorted(all_roles):
    in_victim = role in victim_roles
    in_attacker = role in attacker_roles
    in_exchange = role in exchange_roles
    in_bridge = role in bridge_roles
    in_mixer = role in mixer_roles
    unmapped = not (in_victim or in_attacker or in_exchange or in_bridge or in_mixer)
    cats = []
    if in_victim: cats.append('VICTIM')
    if in_attacker: cats.append('ATTACKER/SUSPECT')
    if in_exchange: cats.append('EXCHANGE')
    if in_bridge: cats.append('BRIDGE')
    if in_mixer: cats.append('MIXER')
    if unmapped: cats.append('UNMAPPED')
    print(f"  '{role}' -> {', '.join(cats)}")

# 5. Check token price data
print("\n=== TOKEN PRICE DATA ===")
r = requests.get(f"{BASE}/api/tokens/list")
print(f"Tokens endpoint: {r.json()}")

# Check investigation transfers for GANA to see what tokens are involved
print("\n=== GANA (inv 5) — transfer volume by token ===")
r = requests.get(f"{BASE}/api/investigations/5/graph?include_external=true")
g = r.json()
token_vol = Counter()
for e in g.get('edges', []):
    token_vol[e.get('token', 'unknown')] += e.get('value', 0)
for t, v in token_vol.most_common():
    print(f"  {t}: {v:,.2f}")
