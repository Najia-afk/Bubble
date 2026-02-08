"""Debug: process all wallets in Inv #2."""
import sys, time, traceback
sys.path.insert(0, '/app')

from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
w = loader.get_wallets(2)
t = loader.get_transfers(2)
print(f"Inv #2: {len(w)} wallets, {len(t)} transfers")

t = t.copy()
t['from_address'] = t['from_address'].str.lower()
t['to_address'] = t['to_address'].str.lower()
wallet_addrs = set(w['address'].str.lower())
t = t[t['from_address'].isin(wallet_addrs) | t['to_address'].isin(wallet_addrs)]
print(f"Filtered: {len(t)} transfers")
sys.stdout.flush()

extractor = WalletFeatureExtractor(t)

good = 0
for i, (_, wallet) in enumerate(w.iterrows()):
    addr = wallet['address']
    role = wallet['role']
    try:
        t0 = time.time()
        feats = extractor.extract_features_for_wallet(addr)
        tc = feats.get('tx_count', 0)
        elapsed = time.time() - t0
        if tc >= 2:
            good += 1
        print(f"  [{i+1}/50] {addr[:12]}... {role:10s} tx={tc:5d} ({elapsed:.2f}s)")
        sys.stdout.flush()
    except Exception as e:
        print(f"  [{i+1}/50] {addr[:12]}... ERROR: {e}")
        traceback.print_exc()
        sys.stdout.flush()

print(f"\nDone: {good}/50 wallets with >= 2 tx")
