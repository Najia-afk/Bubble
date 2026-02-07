"""Quick assessment of extracted features."""
import pandas as pd
import numpy as np

df = pd.read_csv('c:/git/Bubble/notebooks/data/ml_features_audit.csv')
feat_cols = [c for c in df.columns if not c.startswith('_')]

print('=== ML READINESS ===')
print(f'Samples: {len(df)}, Features: {len(feat_cols)}')
print()

labels = df['_role'].value_counts()
for l, c in labels.items():
    pct = c / len(df) * 100
    print(f'  {l}: {c} ({pct:.1f}%)')

print()
print('=== FEATURE ISSUES ===')
for col in feat_cols:
    vals = df[col]
    mx = vals.max()
    issues = []
    if np.isinf(vals).any(): issues.append('INF')
    if vals.isna().any(): issues.append(f'{vals.isna().sum()} NaN')
    if mx > 1e12: issues.append(f'MAX={mx:.2e} TOO LARGE')
    if issues:
        print(f'  {col}: {" | ".join(issues)}')

print()
imb = labels.max() / labels.min()
print(f'=== CRITICAL ===')
print(f'Imbalance: {labels.max()}/{labels.min()} = {imb:.0f}x')
print(f'Smallest: "{labels.idxmin()}" = {labels.min()} samples')
print(f'< 10 samples: {(labels < 10).sum()} classes')

# Feature statistics
print()
print('=== FEATURE STATS (top 10 by variance) ===')
feat_df = df[feat_cols]
variances = feat_df.var().sort_values(ascending=False)
for feat in variances.head(10).index:
    v = feat_df[feat]
    print(f'  {feat}: mean={v.mean():.4f} std={v.std():.4f} min={v.min():.4f} max={v.max():.4f}')
