"""Step 1: Create investigations for all cases."""
import requests

BASE = "http://localhost:8080/api"

def api(method, path, data=None):
    url = f"{BASE}{path}"
    r = requests.post(url, json=data or {}, timeout=60) if method == "POST" else requests.get(url, timeout=30)
    return r.status_code, r.json()

CONFIGS = {
    "CASE-2026-002": {"name": "[CASE-2026-002] Trust Wallet Extension Drain", "chain": "ETH", "loss": 500000},
    "CASE-2026-003": {"name": "[CASE-2026-003] Private Key Compromise", "chain": "ETH", "loss": 1100000},
    "CASE-2026-004": {"name": "[CASE-2026-004] Danny/Meech Genesis Theft", "chain": "ETH", "loss": 18580000},
    "CASE-2026-005": {"name": "[CASE-2026-005] GANA Payment Exploit", "chain": "BSC", "loss": 3100000},
    "CASE-2026-006": {"name": "[CASE-2026-006] Fake Hyperliquid App", "chain": "ETH", "loss": 200000},
    "CASE-2026-007": {"name": "[CASE-2026-007] Garden Finance Exploit", "chain": "ETH", "loss": 10800000},
    "CASE-2026-008": {"name": "[CASE-2026-008] Hypurr NFT Drain", "chain": "ETH", "loss": 400000},
}

_, cases_resp = api("GET", "/cases")
cases = cases_resp.get("cases", [])

for case in cases:
    cid = case["case_id"]
    if case.get("investigation_id"):
        print(f"  {cid}: already has investigation #{case['investigation_id']}")
        continue
    if cid not in CONFIGS:
        continue
    cfg = CONFIGS[cid]
    _, detail = api("GET", f"/cases/{cid}")
    theft_addrs = detail.get("theft_addresses", [])

    status, result = api("POST", "/investigations", {
        "name": cfg["name"],
        "description": detail.get("summary", ""),
        "reported_loss_usd": cfg["loss"],
        "created_by": "pipeline",
        "default_chain": cfg["chain"],
    })
    if status not in (200, 201):
        print(f"  {cid}: FAILED: {result}")
        continue
    inv_id = result["id"]
    print(f"  {cid}: created investigation #{inv_id}")

    for w in theft_addrs:
        chain = w.get("chains", [cfg["chain"]])[0] if w.get("chains") else cfg["chain"]
        ws, wr = api("POST", f"/investigations/{inv_id}/wallets", {
            "address": w["address"], "chain": chain, "role": w.get("role", "attacker"), "depth": 0,
        })
        icon = "+" if ws in (200, 201) else "~" if ws == 409 else "!"
        print(f"    {icon} {w['address'][:20]}... [{w.get('role', 'attacker')}]")

print("\nAll investigations:")
_, invs = api("GET", "/investigations")
for inv in invs.get("investigations", []):
    print(f"  #{inv['id']}: {inv['name']} ({inv.get('wallet_count', 0)} wallets)")
