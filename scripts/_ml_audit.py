"""Data quality audit for ML training feasibility."""
import sys, os, time
sys.path.insert(0, 'c:/git/Bubble')

from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor
import pandas as pd
import numpy as np

loader = DataLoader()

print("=" * 70)
print("DATA QUALITY AUDIT FOR ML TRAINING")
print("=" * 70)

# 1. Audit each investigation
all_features = []
all_labels = []

for inv_id in range(1, 9):
    w = loader.get_wallets(inv_id)
    t = loader.get_transfers(inv_id)
    
    if w.empty or t.empty:
        print(f"\nInv #{inv_id}: EMPTY")
        continue
    
    # For huge investigations, sample down to keep audit fast
    if len(t) > 50000:
        print(f"\nInv #{inv_id}: {len(w)} wallets, {len(t):,} transfers (sampling for audit)")
        # Pre-lowercase addresses once
        t = t.copy()
        t['from_address'] = t['from_address'].str.lower()
        t['to_address'] = t['to_address'].str.lower()
        wallet_addrs = set(w['address'].str.lower())
        t_filtered = t[t['from_address'].isin(wallet_addrs) | t['to_address'].isin(wallet_addrs)]
        if len(t_filtered) > 50000:
            t_filtered = t_filtered.sample(50000, random_state=42)
        t = t_filtered
        print(f"  Filtered to {len(t):,} relevant transfers")
    else:
        print(f"\nInv #{inv_id}: {len(w)} wallets, {len(t):,} transfers")
        t = t.copy()
        t['from_address'] = t['from_address'].str.lower()
        t['to_address'] = t['to_address'].str.lower()
    print(f"  Roles: {w.role.value_counts().to_dict()}")
    
    # Value sanity check 
    print(f"  Value dtype: {t.value.dtype}")
    print(f"  Value > 1e30: {(t.value > 1e30).sum()} crazy values")
    print(f"  Value == 0: {(t.value == 0).sum()}")
    print(f"  Value NaN: {t.value.isna().sum()}")
    
    # Feature extraction timing
    t0 = time.time()
    extractor = WalletFeatureExtractor(t)
    
    good = 0
    bad = 0
    for _, wallet in w.iterrows():
        addr = wallet['address']
        role = wallet['role']
        try:
            feats = extractor.extract_features_for_wallet(addr)
            if feats.get('tx_count', 0) >= 2:
                feats['_inv_id'] = inv_id
                feats['_role'] = role
                all_features.append(feats)
                all_labels.append(role)
                good += 1
            else:
                bad += 1
        except Exception as e:
            bad += 1
    
    elapsed = time.time() - t0
    print(f"  Features extracted: {good} good, {bad} skipped ({elapsed:.1f}s)")

# 2. Overall ML readiness
print("\n" + "=" * 70)
print("ML READINESS ASSESSMENT")
print("=" * 70)

df = pd.DataFrame(all_features)
if df.empty:
    print("FATAL: No features extracted!")
    sys.exit(1)

print(f"\nTotal training samples: {len(df)}")
print(f"Feature columns: {len([c for c in df.columns if not c.startswith('_')])}")

# Label distribution
label_counts = pd.Series(all_labels).value_counts()
print(f"\nLabel distribution:")
for label, count in label_counts.items():
    pct = count / len(all_labels) * 100
    print(f"  {label}: {count} ({pct:.1f}%)")

# Feature quality
feature_cols = [c for c in df.columns if not c.startswith('_')]
print(f"\nFeature quality:")
for col in feature_cols:
    vals = df[col]
    inf_count = np.isinf(vals).sum() if vals.dtype in [np.float64, np.float32] else 0
    nan_count = vals.isna().sum()
    max_val = vals.max()
    min_val = vals.min()
    std_val = vals.std()
    
    issues = []
    if inf_count > 0: issues.append(f"{inf_count} inf")
    if nan_count > 0: issues.append(f"{nan_count} NaN")
    if max_val > 1e15: issues.append(f"MAX={max_val:.2e} TOO LARGE")
    
    flag = " *** PROBLEM" if issues else ""
    if issues:
        print(f"  {col}: min={min_val:.4f} max={max_val:.4e} std={std_val:.4e} {' | '.join(issues)}{flag}")

# Critical assessment
print(f"\n{'=' * 70}")
print("CRITICAL ASSESSMENT")
print("=" * 70)

n_samples = len(df)
n_classes = len(label_counts)
min_class = label_counts.min()
max_class = label_counts.max()

print(f"  Samples: {n_samples} (need 200+ for decent ML, 1000+ for production)")
print(f"  Classes: {n_classes}")
print(f"  Smallest class: {label_counts.idxmin()} = {min_class} samples")
print(f"  Largest class: {label_counts.idxmax()} = {max_class} samples")
print(f"  Imbalance ratio: {max_class/min_class:.1f}x")

if n_samples < 50:
    print("  VERDICT: INSUFFICIENT DATA - cannot train reliable models")
elif n_samples < 200:
    print("  VERDICT: MARGINAL - can try but expect overfitting")
elif n_samples < 500:
    print("  VERDICT: USABLE - SMOTE + careful CV needed")
else:
    print("  VERDICT: GOOD - sufficient for initial models")

if min_class < 5:
    print(f"  WARNING: {label_counts.idxmin()} has only {min_class} samples - consider merging classes")
if max_class / min_class > 10:
    print(f"  WARNING: {max_class/min_class:.0f}x imbalance - SMOTE critical")

# Save for later use
df.to_csv('c:/git/Bubble/notebooks/data/ml_features_audit.csv', index=False)
print(f"\n  Features saved to notebooks/data/ml_features_audit.csv")
