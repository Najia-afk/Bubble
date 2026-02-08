"""Check case-to-investigation mapping."""
import requests, json

BASE = "http://localhost:8080"

r = requests.get(f"{BASE}/api/cases")
cases = r.json()['cases']

print("=== CASE -> INVESTIGATION MAPPING ===")
for c in cases:
    print(f"{c['case_id']}: inv_id={c.get('investigation_id','NONE')} "
          f"attackers={c['attacker_wallet_count']} "
          f"exchange={c['exchange_wallet_count']} "
          f"victims={c['victim_wallet_count']} "
          f"bridge={c['bridge_wallet_count']} "
          f"mixer={c['mixer_wallet_count']} "
          f"tokens={c.get('investigation_token_count',0)}")

# Check CaseWallet roles vs InvestigationWallet roles for GANA
print("\n=== GANA (CASE-2026-005) CASE WALLETS ===")
r = requests.get(f"{BASE}/api/cases/CASE-2026-005")
d = r.json()
from collections import Counter
cw_roles = Counter(w.get('role','?') for w in d.get('addresses', d.get('wallets', [])))
print(f"CaseWallet roles: {dict(cw_roles)}")

# Check InvestigationWallet roles via GraphQL
print("\n=== INVESTIGATION WALLETS VIA GRAPHQL ===")
for inv_id in range(1, 9):
    gql = {
        "query": """query($invId: Int) {
            investigationWallets(investigationId: $invId) {
                address role
            }
        }""",
        "variables": {"invId": inv_id}
    }
    r = requests.post(f"{BASE}/graphql", json=gql)
    wallets = r.json().get('data', {}).get('investigationWallets', [])
    if wallets:
        roles = Counter(w['role'] for w in wallets)
        print(f"  inv_id={inv_id}: {len(wallets)} wallets, roles={dict(roles)}")
