"""Step 2: Trigger sync_and_expand for all investigations, then poll progress."""
import requests
import time

BASE = "http://localhost:8080/api"

DEPTH_CONFIG = {
    "CASE-2026-001": (3, 100),
    "CASE-2026-002": (2, 80),
    "CASE-2026-003": (3, 60),
    "CASE-2026-004": (2, 50),
    "CASE-2026-005": (3, 60),
    "CASE-2026-006": (2, 40),
    "CASE-2026-007": (3, 80),
    "CASE-2026-008": (2, 40),
}

def api(method, path, data=None):
    url = f"{BASE}{path}"
    r = requests.post(url, json=data or {}, timeout=60) if method == "POST" else requests.get(url, timeout=30)
    return r.status_code, r.json()


# Get all investigations
_, invs = api("GET", "/investigations")
investigations = invs.get("investigations", [])

print(f"Triggering sync_and_expand for {len(investigations)} investigations...")

for inv in investigations:
    inv_id = inv["id"]
    name = inv["name"]
    
    # Find config
    depth, max_w = 2, 50
    for cid, (d, w) in DEPTH_CONFIG.items():
        if cid in name:
            depth, max_w = d, w
            break
    
    # Skip investigation 1 — already has 50 wallets from prior work
    if inv_id == 1 and inv.get("wallet_count", 0) >= 50:
        print(f"  #{inv_id}: {name[:50]} — already has {inv['wallet_count']} wallets, skipping")
        continue

    status, result = api("POST", f"/investigations/{inv_id}/investigate", {
        "max_depth": depth,
        "max_wallets": max_w,
    })
    
    if status == 202:
        print(f"  #{inv_id}: submitted (depth={depth}, max={max_w}) task={result.get('task_id', '?')[:12]}")
    else:
        print(f"  #{inv_id}: FAILED: {result}")

print(f"\nPolling progress every 30s for 10 minutes...")
print("(Etherscan API: 5 calls/sec free tier — large investigations take time)\n")

for cycle in range(20):
    time.sleep(30)
    elapsed = (cycle + 1) * 30
    _, invs_chk = api("GET", "/investigations")
    lines = []
    total_w = 0
    for inv in invs_chk.get("investigations", []):
        wc = inv.get("wallet_count", 0)
        total_w += wc
        lines.append(f"#{inv['id']}={wc}w")
    
    print(f"  [{elapsed:>3}s] total={total_w} wallets | {' '.join(lines)}")
    
    # Early exit if all investigations have wallets and growth stalled
    if cycle > 6 and total_w > 100:
        prev_total = total_w  # Simple stall detection
        time.sleep(30)
        _, invs_chk2 = api("GET", "/investigations")
        new_total = sum(i.get("wallet_count", 0) for i in invs_chk2.get("investigations", []))
        if new_total == total_w:
            print(f"\n  Growth stalled at {total_w} wallets — continuing to next step.")
            break

print("\nFinal state:")
_, final = api("GET", "/investigations")
for inv in final.get("investigations", []):
    print(f"  #{inv['id']}: {inv['name'][:50]} — {inv.get('wallet_count', 0)} wallets")
