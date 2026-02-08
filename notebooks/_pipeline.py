"""Full pipeline - minimal, no tqdm interference."""
import sys, os, time, warnings, traceback
warnings.filterwarnings('ignore')
os.environ['TQDM_DISABLE'] = '1'  # Disable tqdm globally
sys.path.insert(0, '/app')
os.chdir('/app/notebooks')

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix, accuracy_score, f1_score
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, ExtraTreesClassifier
from sklearn.linear_model import LogisticRegression

import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier
from imblearn.over_sampling import SMOTE

from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
print(f"DB: {loader._db_url}")
sys.stdout.flush()

# ═══ STEP 1: FEATURE EXTRACTION ═══
all_features = []
all_labels = []

for inv_id in range(1, 9):
    try:
        w = loader.get_wallets(inv_id)
        t = loader.get_transfers(inv_id)
        if w.empty or t.empty:
            print(f"  Inv #{inv_id}: EMPTY")
            sys.stdout.flush()
            continue

        t = t.copy()
        t['from_address'] = t['from_address'].str.lower()
        t['to_address'] = t['to_address'].str.lower()
        if len(t) > 50000:
            addrs = set(w['address'].str.lower())
            t = t[t['from_address'].isin(addrs) | t['to_address'].isin(addrs)]

        t0 = time.time()
        extractor = WalletFeatureExtractor(t)
        good = 0
        for _, wallet in w.iterrows():
            feats = extractor.extract_features_for_wallet(wallet['address'])
            if feats.get('tx_count', 0) >= 2:
                feats['_inv_id'] = inv_id
                all_features.append(feats)
                all_labels.append(wallet['role'])
                good += 1
        print(f"  Inv #{inv_id}: {good}/{len(w)} wallets ({time.time()-t0:.1f}s)")
        sys.stdout.flush()
    except Exception as e:
        print(f"  Inv #{inv_id}: ERROR - {e}")
        traceback.print_exc()
        sys.stdout.flush()

df_raw = pd.DataFrame(all_features)
labels_raw = pd.Series(all_labels)
FEATURE_COLS = [c for c in df_raw.columns if not c.startswith('_')]
print(f"\nExtracted: {len(df_raw)} samples, {len(FEATURE_COLS)} features")
print(f"Labels: {labels_raw.value_counts().to_dict()}")
sys.stdout.flush()

# ═══ STEP 2: CLEAN ═══
df = df_raw[FEATURE_COLS].copy().replace([np.inf, -np.inf], np.nan).fillna(0)
VALUE_FEATURES = ['avg_tx_value', 'median_tx_value', 'max_tx_value', 'min_tx_value',
                  'std_tx_value', 'total_volume', 'in_volume', 'out_volume',
                  'avg_in_value', 'avg_out_value']
for col in VALUE_FEATURES:
    if col in df.columns:
        p995 = df[col].quantile(0.995)
        df[col] = np.log1p(df[col].clip(upper=max(p995, 1)).abs())

if 'volume_ratio' in df.columns:
    df['volume_ratio'] = np.log1p(df['volume_ratio'].clip(upper=df['volume_ratio'].quantile(0.995)))

labels = labels_raw.replace({'seized': 'attacker'})
le = LabelEncoder()
y = le.fit_transform(labels)
class_names = list(le.classes_)
print(f"Classes: {class_names}, Distribution: {dict(zip(*np.unique(y, return_counts=True)))}")
print(f"Max value: {df.max().max():.2f}, NaN: {df.isna().sum().sum()}, Inf: {np.isinf(df.values).sum()}")
sys.stdout.flush()

# ═══ STEP 3: SPLIT + SMOTE + SCALE ═══
X_train, X_test, y_train, y_test = train_test_split(df, y, test_size=0.2, stratify=y, random_state=42)
min_k = pd.Series(y_train).value_counts().min()
k_smote = min(5, min_k - 1) if min_k > 1 else 1
smote = SMOTE(random_state=42, k_neighbors=k_smote)
X_res, y_res = smote.fit_resample(X_train, y_train)
print(f"Train={len(X_train)}, Test={len(X_test)}, SMOTE={len(X_res)} (k={k_smote})")
sys.stdout.flush()

scaler = StandardScaler()
X_s = scaler.fit_transform(X_res)
X_ts = scaler.transform(X_test)

# ═══ STEP 4: TRAIN MODELS WITH OPTUNA ═══
MODELS = {
    'RandomForest': (RandomForestClassifier, {
        'n_estimators': ('int', 50, 300),
        'max_depth': ('int', 3, 20),
        'min_samples_split': ('int', 2, 20),
    }),
    'GradientBoosting': (GradientBoostingClassifier, {
        'n_estimators': ('int', 50, 200),
        'max_depth': ('int', 2, 10),
        'learning_rate': ('float', 0.01, 0.3),
    }),
    'ExtraTrees': (ExtraTreesClassifier, {
        'n_estimators': ('int', 50, 300),
        'max_depth': ('int', 3, 20),
    }),
    'LogisticRegression': (LogisticRegression, {
        'C': ('float', 0.01, 100.0),
        'max_iter': ('int', 500, 2000),
    }),
    'XGBoost': (XGBClassifier, {
        'n_estimators': ('int', 50, 300),
        'max_depth': ('int', 2, 10),
        'learning_rate': ('float', 0.01, 0.3),
    }),
    'LightGBM': (LGBMClassifier, {
        'n_estimators': ('int', 50, 300),
        'max_depth': ('int', 2, 10),
        'learning_rate': ('float', 0.01, 0.3),
        'num_leaves': ('int', 10, 80),
        'verbose': ('fixed', -1),
    }),
}

N_TRIALS = 10  # Keep small for Docker execution speed
results = {}
trained_models = {}

for model_name, (ModelClass, param_space) in MODELS.items():
    print(f"\n--- {model_name} ---")
    sys.stdout.flush()
    t0 = time.time()

    try:
        def objective(trial, _mc=ModelClass, _ps=param_space):
            params = {}
            for pname, pdef in _ps.items():
                if pdef[0] == 'int':
                    params[pname] = trial.suggest_int(pname, pdef[1], pdef[2])
                elif pdef[0] == 'float':
                    params[pname] = trial.suggest_float(pname, pdef[1], pdef[2], log=True)
                elif pdef[0] == 'fixed':
                    params[pname] = pdef[1]
            try:
                model = _mc(**params, random_state=42)
            except TypeError:
                model = _mc(**params)
            return cross_val_score(model, X_s, y_res, cv=5, scoring='f1_macro').mean()

        study = optuna.create_study(direction='maximize', study_name=model_name)
        study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
        best_params = {}
        for pname, pdef in param_space.items():
            if pdef[0] == 'fixed':
                best_params[pname] = pdef[1]
            else:
                best_params[pname] = study.best_params[pname]
        cv_score = study.best_value
        print(f"  CV F1: {cv_score:.4f}")
        sys.stdout.flush()

        try:
            final = ModelClass(**best_params, random_state=42)
        except TypeError:
            final = ModelClass(**best_params)
        final.fit(X_s, y_res)

        y_pred = final.predict(X_ts)
        test_acc = accuracy_score(y_test, y_pred)
        test_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
        elapsed = time.time() - t0

        results[model_name] = {
            'cv_f1': round(cv_score, 4),
            'test_acc': round(test_acc, 4),
            'test_f1': round(test_f1, 4),
            'gap': round(test_f1 - cv_score, 4),
            'time': round(elapsed, 1),
        }
        trained_models[model_name] = final
        print(f"  Test Acc={test_acc:.4f} F1={test_f1:.4f} gap={test_f1-cv_score:+.4f} ({elapsed:.0f}s)")
        if abs(test_f1 - cv_score) > 0.10:
            print(f"  WARNING: gap > 10%")
        sys.stdout.flush()

    except Exception as e:
        traceback.print_exc()
        print(f"  FAILED: {e}")
        sys.stdout.flush()

# ═══ STEP 5: RESULTS ═══
ranking = sorted(results.items(), key=lambda x: x[1]['test_f1'], reverse=True)
print(f"\n{'='*60}")
print("LEADERBOARD:")
for i, (name, r) in enumerate(ranking):
    print(f"  {i+1}. {name:20s} F1={r['test_f1']:.4f} CV={r['cv_f1']:.4f} gap={r['gap']:+.4f}")
sys.stdout.flush()

if not ranking:
    print("ERROR: No models trained successfully")
    sys.exit(1)

champ_name = ranking[0][0]
champ_model = trained_models[champ_name]
print(f"\nCHAMPION: {champ_name}")

# Classification report
y_pred = champ_model.predict(X_ts)
present = sorted(set(y_test) | set(y_pred))
names = [class_names[l] for l in present]
print(classification_report(y_test, y_pred, target_names=names, zero_division=0))

# Per-class verdict
rd = classification_report(y_test, y_pred, target_names=names, zero_division=0, output_dict=True)
for cls in names:
    if cls in rd:
        f1v = rd[cls]['f1-score']
        v = "OK" if f1v >= 0.7 else "WEAK" if f1v >= 0.4 else "FAIL"
        print(f"  {cls:15s} F1={f1v:.3f} n={int(rd[cls]['support'])} {v}")

# Confusion matrix
cm = confusion_matrix(y_test, y_pred, labels=present)
print(f"\nConfusion Matrix:")
print(pd.DataFrame(cm, index=names, columns=names).to_string())

# Feature importance
if hasattr(champ_model, 'feature_importances_'):
    fi = pd.DataFrame({'f': FEATURE_COLS, 'imp': champ_model.feature_importances_})
    fi = fi.sort_values('imp', ascending=False).head(15)
    print(f"\nTop 15 Features:")
    for _, r in fi.iterrows():
        print(f"  {r['f']:30s} {r['imp']:.4f}")

# ═══ STEP 6: SAVE ═══
import pickle, json
from pathlib import Path
from datetime import datetime

model_dir = Path('data/models')
model_dir.mkdir(parents=True, exist_ok=True)
ts = datetime.now().strftime('%Y%m%d_%H%M%S')

with open(model_dir / f'champion_{champ_name}_{ts}.pkl', 'wb') as f:
    pickle.dump({'model': champ_model, 'scaler': scaler, 'label_encoder': le,
                 'features': FEATURE_COLS, 'results': results}, f)
print(f"\nModel saved: data/models/champion_{champ_name}_{ts}.pkl")

with open(model_dir / f'results_{ts}.json', 'w') as f:
    json.dump(results, f, indent=2)

# MLflow
try:
    import mlflow
    mlflow_uri = os.environ.get('MLFLOW_TRACKING_URI', 'http://mlflow:5005')
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment("bubble_automl")
    with mlflow.start_run(run_name=f"automl_{champ_name}_{ts}"):
        mlflow.log_params(results[champ_name])
        mlflow.sklearn.log_model(champ_model, "model")
    print(f"MLflow logged ({mlflow_uri})")
except Exception as e:
    print(f"MLflow failed: {e}")

# ═══ STEP 7: PREDICT ALL INVESTIGATIONS ═══
print(f"\nPREDICTIONS:")
all_preds = []
for inv_id in range(1, 9):
    try:
        w2 = loader.get_wallets(inv_id)
        t2 = loader.get_transfers(inv_id)
        if t2.empty or w2.empty:
            continue
        t2 = t2.copy()
        t2['from_address'] = t2['from_address'].str.lower()
        t2['to_address'] = t2['to_address'].str.lower()
        ext = WalletFeatureExtractor(t2)
        feats = ext.extract_all_features(min_tx_count=2)
        if feats.empty:
            continue
        fc = feats[FEATURE_COLS].copy().replace([np.inf, -np.inf], np.nan).fillna(0)
        for col in VALUE_FEATURES:
            if col in fc.columns:
                fc[col] = np.log1p(fc[col].clip(upper=max(fc[col].quantile(0.995), 1)).abs())
        fs = scaler.transform(fc)
        preds = le.inverse_transform(champ_model.predict(fs))
        dist = pd.Series(preds).value_counts().to_dict()
        print(f"  Inv #{inv_id}: {len(feats)} wallets -> {dist}")
        dfp = pd.DataFrame({'wallet': feats.index, 'pred': preds, 'inv': inv_id})
        all_preds.append(dfp)
    except Exception as e:
        print(f"  Inv #{inv_id}: {e}")
    sys.stdout.flush()

if all_preds:
    apd = pd.concat(all_preds, ignore_index=True)
    apd.to_csv(model_dir / f'predictions_{ts}.csv', index=False)
    print(f"\n{len(apd)} predictions saved")
    print(apd['pred'].value_counts().to_string())

# ═══ FINAL SUMMARY ═══
print(f"\n{'='*60}")
print("AUTOML COMPLETE")
print(f"{'='*60}")
print(f"  Samples: {len(df)} raw, {len(X_res)} SMOTE, {len(X_test)} test")
print(f"  Features: {len(FEATURE_COLS)}")
print(f"  Classes: {class_names}")
print(f"  Models: {len(results)}")
print(f"  Champion: {champ_name}")
print(f"  F1 (test): {results[champ_name]['test_f1']:.4f}")
print(f"  F1 (CV):   {results[champ_name]['cv_f1']:.4f}")
print(f"  Gap:       {results[champ_name]['gap']:+.4f}")
gap = abs(results[champ_name]['gap'])
if gap > 0.10:
    print("  VERDICT: OVERFITTING")
elif results[champ_name]['test_f1'] < 0.5:
    print("  VERDICT: UNDERFITTING")
else:
    print("  VERDICT: HEALTHY")
sys.stdout.flush()
