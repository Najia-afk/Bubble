"""Retry investigation 6 and wait for it."""
import requests, time
r = requests.post("http://localhost:8080/api/investigations/6/investigate", json={"max_depth": 2, "max_wallets": 40}, timeout=30)
print(f"Status: {r.status_code}")
print(r.json())
time.sleep(60)
r2 = requests.get("http://localhost:8080/api/investigations/6", timeout=30).json()
print(f"\nInvestigation 6: {r2.get('wallets', [{}]).__len__()} wallets, status={r2.get('status')}")
