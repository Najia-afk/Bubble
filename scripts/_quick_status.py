"""Quick status check writing to file."""
import requests, json
r = requests.get("http://localhost:8080/api/investigations", timeout=30).json()
with open("C:/git/Bubble/logs/status.txt", "w") as f:
    total = 0
    for inv in r.get("investigations", []):
        w = inv.get("wallet_count", 0)
        total += w
        f.write(f"#{inv['id']:>2}: {w:>4}w | {inv['name'][:50]}\n")
    f.write(f"\nTotal: {total} wallets\n")
    s = requests.get("http://localhost:8080/api/stats/dashboard", timeout=30).json()
    f.write(f"Transfers: {s.get('investigation_transfers', 0)}\n")
print("Done - see logs/status.txt")
