"""Debug: test training loop with real data."""
import sys, time, traceback, os
sys.path.insert(0, '/app')
os.chdir('/app/notebooks')

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.ensemble import RandomForestClassifier
from imblearn.over_sampling import SMOTE
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("Loading cached features...")
# Load pre-extracted features if available, else extract
from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
all_features = []
all_labels = []

for inv_id in [1, 2, 3, 4, 5, 6, 7, 8]:
    try:
        w = loader.get_wallets(inv_id)
        t = loader.get_transfers(inv_id)
        if w.empty or t.empty:
            continue
        t = t.copy()
        t['from_address'] = t['from_address'].str.lower()
        t['to_address'] = t['to_address'].str.lower()
        if len(t) > 50000:
            addrs = set(w['address'].str.lower())
            t = t[t['from_address'].isin(addrs) | t['to_address'].isin(addrs)]
        extractor = WalletFeatureExtractor(t)
        for _, wallet in w.iterrows():
            feats = extractor.extract_features_for_wallet(wallet['address'])
            if feats.get('tx_count', 0) >= 2:
                feats['_inv_id'] = inv_id
                all_features.append(feats)
                all_labels.append(wallet['role'])
        print(f"  Inv #{inv_id}: done")
    except Exception as e:
        print(f"  Inv #{inv_id}: {e}")
        traceback.print_exc()

df_raw = pd.DataFrame(all_features)
labels_raw = pd.Series(all_labels)
FEATURE_COLS = [c for c in df_raw.columns if not c.startswith('_')]
df = df_raw[FEATURE_COLS].copy().replace([np.inf, -np.inf], np.nan).fillna(0)

VALUE_FEATURES = ['avg_tx_value', 'median_tx_value', 'max_tx_value', 'min_tx_value',
                  'std_tx_value', 'total_volume', 'in_volume', 'out_volume',
                  'avg_in_value', 'avg_out_value']

for col in VALUE_FEATURES:
    if col in df.columns:
        p995 = df[col].quantile(0.995)
        df[col] = df[col].clip(upper=max(p995, 1))
        df[col] = np.log1p(df[col].abs())

labels = labels_raw.replace({'seized': 'attacker'})
le = LabelEncoder()
y = le.fit_transform(labels)

print(f"Data: {len(df)} samples, {len(FEATURE_COLS)} features, {len(le.classes_)} classes")
print(f"Classes: {list(le.classes_)}")
print(f"Max value: {df.max().max():.4f}")

# Check for NaN/inf
nan_count = df.isna().sum().sum()
inf_count = np.isinf(df.values).sum()
print(f"NaN: {nan_count}, Inf: {inf_count}")

X_train, X_test, y_train, y_test = train_test_split(df, y, test_size=0.2, stratify=y, random_state=42)
print(f"Split: {len(X_train)} train, {len(X_test)} test")

smote = SMOTE(random_state=42, k_neighbors=5)
X_res, y_res = smote.fit_resample(X_train, y_train)
print(f"SMOTE: {len(X_res)} samples")

scaler = StandardScaler()
X_s = scaler.fit_transform(X_res)
X_ts = scaler.transform(X_test)

print(f"Scaled train shape: {X_s.shape}, type: {type(X_s)}")
print(f"Any NaN in scaled: {np.isnan(X_s).any()}")
print(f"Any Inf in scaled: {np.isinf(X_s).any()}")

# Now try the Optuna loop
print("\n--- Testing RandomForest with Optuna ---")
sys.stdout.flush()

try:
    def objective(trial):
        n = trial.suggest_int('n_estimators', 50, 500)
        d = trial.suggest_int('max_depth', 3, 30)
        model = RandomForestClassifier(n_estimators=n, max_depth=d, random_state=42)
        scores = cross_val_score(model, X_s, y_res, cv=5, scoring='f1_macro')
        return scores.mean()

    study = optuna.create_study(direction='maximize', study_name='RF_test')
    study.optimize(objective, n_trials=5, show_progress_bar=False)
    print(f"RF Optuna best: {study.best_value:.4f}")
    print(f"RF Optuna params: {study.best_params}")
except Exception as e:
    traceback.print_exc()
    print(f"RF FAILED: {e}")

sys.stdout.flush()
print("\nDone.")
