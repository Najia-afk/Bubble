"""Quick status check of all investigations."""
import requests
BASE = "http://localhost:8080/api"
r = requests.get(f"{BASE}/investigations", timeout=30).json()
total_w = 0
total_t = 0
for inv in r.get("investigations", []):
    wc = inv.get("wallet_count", 0)
    tc = inv.get("token_count", 0)
    total_w += wc
    print(f"  #{inv['id']:>2}: {wc:>4} wallets | {inv['name'][:55]}")
print(f"\n  Total: {total_w} wallets across {len(r.get('investigations', []))} investigations")

# Also check dashboard
s = requests.get(f"{BASE}/stats/dashboard", timeout=30).json()
print(f"  Transfers indexed: {s.get('investigation_transfers', 0)}")
