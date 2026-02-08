"""Quick test: feature extraction on Inv #2 inside Docker."""
import sys, time, traceback
sys.path.insert(0, '/app')

from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
print(f"DB: {loader._db_url}")

w = loader.get_wallets(2)
t = loader.get_transfers(2)
print(f"Inv #2: {len(w)} wallets, {len(t)} transfers")

t = t.copy()
t['from_address'] = t['from_address'].str.lower()
t['to_address'] = t['to_address'].str.lower()

wallet_addrs = set(w['address'].str.lower())
t_filt = t[t['from_address'].isin(wallet_addrs) | t['to_address'].isin(wallet_addrs)]
print(f"Filtered to wallet-related: {len(t_filt)} transfers")

extractor = WalletFeatureExtractor(t_filt)

for i, (_, wallet) in enumerate(w.head(3).iterrows()):
    addr = wallet['address']
    role = wallet['role']
    t0 = time.time()
    try:
        feats = extractor.extract_features_for_wallet(addr)
        tc = feats.get('tx_count', 0)
        print(f"  Wallet {i}: addr={addr[:12]}... role={role} tx_count={tc} ({time.time()-t0:.2f}s)")
    except Exception as e:
        traceback.print_exc()
        print(f"  Wallet {i}: ERROR - {e}")

print("Done.")
