#!/usr/bin/env python3
"""
AutoML Pipeline — Docker Execution Script
Designed to run inside bubble_web container.
"""
import os, sys, time, warnings, traceback
warnings.filterwarnings('ignore')

# Ensure project root is in path
sys.path.insert(0, '/app')
os.chdir('/app/notebooks')

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import (classification_report, confusion_matrix,
                             accuracy_score, f1_score)
from sklearn.ensemble import (RandomForestClassifier, GradientBoostingClassifier,
                              ExtraTreesClassifier)
from sklearn.linear_model import LogisticRegression

# Optional packages
try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
    HAS_OPTUNA = True
except ImportError:
    HAS_OPTUNA = False

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGB = True
except ImportError:
    HAS_LGB = False

try:
    from imblearn.over_sampling import SMOTE
    HAS_SMOTE = True
except ImportError:
    HAS_SMOTE = False

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

print(f"Optuna={HAS_OPTUNA} XGB={HAS_XGB} LGB={HAS_LGB} SMOTE={HAS_SMOTE} SHAP={HAS_SHAP}")
sys.stdout.flush()

from notebooks.src.data_loader import DataLoader
from notebooks.src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
print(f"DB: {loader._db_url}")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 1: FEATURE EXTRACTION
# ═══════════════════════════════════════════════════════════════
all_features = []
all_labels = []

for inv_id in range(1, 9):
    try:
        w = loader.get_wallets(inv_id)
        t = loader.get_transfers(inv_id)
        if w.empty or t.empty:
            print(f"  Inv #{inv_id}: EMPTY")
            continue

        n_wallets = len(w)
        n_transfers = len(t)

        t = t.copy()
        t['from_address'] = t['from_address'].str.lower()
        t['to_address'] = t['to_address'].str.lower()

        if n_transfers > 50000:
            wallet_addrs = set(w['address'].str.lower())
            t = t[t['from_address'].isin(wallet_addrs) | t['to_address'].isin(wallet_addrs)]

        t0 = time.time()
        extractor = WalletFeatureExtractor(t)

        good = 0
        for _, wallet in w.iterrows():
            addr = wallet['address']
            role = wallet['role']
            feats = extractor.extract_features_for_wallet(addr)
            if feats.get('tx_count', 0) >= 2:
                feats['_inv_id'] = inv_id
                all_features.append(feats)
                all_labels.append(role)
                good += 1

        elapsed = time.time() - t0
        print(f"  Inv #{inv_id}: {good}/{n_wallets} wallets from {n_transfers:,} tx ({elapsed:.1f}s)")
        sys.stdout.flush()
    except Exception as e:
        traceback.print_exc()
        print(f"  Inv #{inv_id}: ERROR - {e}")
        sys.stdout.flush()

df_raw = pd.DataFrame(all_features)
labels_raw = pd.Series(all_labels, name='role')
print(f"\nTotal: {len(df_raw)} samples, {len(df_raw.columns)} columns")
print(f"Labels: {labels_raw.value_counts().to_dict()}")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 2: DATA CLEANING
# ═══════════════════════════════════════════════════════════════
FEATURE_COLS = [c for c in df_raw.columns if not c.startswith('_')]
df = df_raw[FEATURE_COLS].copy()
df = df.replace([np.inf, -np.inf], np.nan).fillna(0)

VALUE_FEATURES = ['avg_tx_value', 'median_tx_value', 'max_tx_value', 'min_tx_value',
                  'std_tx_value', 'total_volume', 'in_volume', 'out_volume',
                  'avg_in_value', 'avg_out_value']

for col in VALUE_FEATURES:
    if col in df.columns:
        p995 = df[col].quantile(0.995)
        df[col] = df[col].clip(upper=max(p995, 1))
        df[col] = np.log1p(df[col].abs())

if 'volume_ratio' in df.columns:
    df['volume_ratio'] = np.log1p(df['volume_ratio'].clip(upper=df['volume_ratio'].quantile(0.995)))

labels = labels_raw.copy()
labels = labels.replace({'seized': 'attacker'})

label_encoder = LabelEncoder()
y = label_encoder.fit_transform(labels)
class_names = label_encoder.classes_.tolist()

print(f"\nAfter cleaning: {len(df)} samples, {len(FEATURE_COLS)} features, {len(class_names)} classes")
print(f"Classes: {class_names}")
print(f"Distribution: {dict(zip(*np.unique(y, return_counts=True)))}")
print(f"Max feature value: {df.max().max():.4f}")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 3: SPLIT + SMOTE + SCALE
# ═══════════════════════════════════════════════════════════════
X_train, X_test, y_train, y_test = train_test_split(
    df, y, test_size=0.2, stratify=y, random_state=42
)
print(f"\nSplit: Train={len(X_train)}, Test={len(X_test)}")
sys.stdout.flush()

if HAS_SMOTE:
    min_class_count = pd.Series(y_train).value_counts().min()
    k = min(5, min_class_count - 1) if min_class_count > 1 else 1
    if k >= 1:
        smote = SMOTE(random_state=42, k_neighbors=k)
        X_train_res, y_train_res = smote.fit_resample(X_train, y_train)
        print(f"SMOTE (k={k}): {len(X_train_res)} samples")
        print(f"Balanced: {dict(zip(*np.unique(y_train_res, return_counts=True)))}")
    else:
        X_train_res, y_train_res = X_train.values, y_train
        print("SMOTE skipped - min class too small")
else:
    X_train_res, y_train_res = X_train.values, y_train
    print("SMOTE not available")
sys.stdout.flush()

scaler = StandardScaler()
X_train_scaled = scaler.fit_transform(X_train_res)
X_test_scaled = scaler.transform(X_test)

# ═══════════════════════════════════════════════════════════════
# STEP 4: MULTI-MODEL TRAINING WITH OPTUNA
# ═══════════════════════════════════════════════════════════════
MODELS = {
    'RandomForest': (RandomForestClassifier, {
        'n_estimators': ('int', 50, 500),
        'max_depth': ('int', 3, 30),
        'min_samples_split': ('int', 2, 20),
        'min_samples_leaf': ('int', 1, 10),
    }),
    'GradientBoosting': (GradientBoostingClassifier, {
        'n_estimators': ('int', 50, 400),
        'max_depth': ('int', 2, 15),
        'learning_rate': ('float', 0.01, 0.3),
        'subsample': ('float', 0.6, 1.0),
    }),
    'ExtraTrees': (ExtraTreesClassifier, {
        'n_estimators': ('int', 50, 500),
        'max_depth': ('int', 3, 30),
        'min_samples_split': ('int', 2, 20),
    }),
    'LogisticRegression': (LogisticRegression, {
        'C': ('float', 0.01, 100.0),
        'max_iter': ('int', 200, 2000),
    }),
}
if HAS_XGB:
    MODELS['XGBoost'] = (XGBClassifier, {
        'n_estimators': ('int', 50, 500),
        'max_depth': ('int', 2, 15),
        'learning_rate': ('float', 0.01, 0.3),
        'subsample': ('float', 0.6, 1.0),
    })
if HAS_LGB:
    MODELS['LightGBM'] = (LGBMClassifier, {
        'n_estimators': ('int', 50, 500),
        'max_depth': ('int', 2, 15),
        'learning_rate': ('float', 0.01, 0.3),
        'num_leaves': ('int', 10, 100),
        'verbose': ('fixed', -1),
    })

N_TRIALS = 30
CV_FOLDS = 5
results = {}
trained_models = {}

for model_name, (ModelClass, param_space) in MODELS.items():
    print(f"\n{'='*60}")
    print(f"Training: {model_name}")
    print(f"{'='*60}")
    sys.stdout.flush()
    t0 = time.time()

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
        scores = cross_val_score(model, X_train_scaled, y_train_res, cv=CV_FOLDS, scoring='f1_macro')
        return scores.mean()

    if HAS_OPTUNA:
        study = optuna.create_study(direction='maximize', study_name=model_name)
        study.optimize(objective, n_trials=N_TRIALS, show_progress_bar=False)
        best_params = {}
        for pname, pdef in param_space.items():
            if pdef[0] == 'fixed':
                best_params[pname] = pdef[1]
            else:
                best_params[pname] = study.best_params[pname]
        cv_score = study.best_value
        print(f"  Optuna CV F1-macro: {cv_score:.4f} ({N_TRIALS} trials)")
    else:
        best_params = {}
        for k, v in param_space.items():
            if v[0] == 'fixed':
                best_params[k] = v[1]
            elif v[0] == 'int':
                best_params[k] = (v[1]+v[2])//2
            else:
                best_params[k] = (v[1]+v[2])/2
        cv_score = 0.0

    try:
        best_params['random_state'] = 42
        final_model = ModelClass(**best_params)
    except TypeError:
        del best_params['random_state']
        final_model = ModelClass(**best_params)

    final_model.fit(X_train_scaled, y_train_res)

    y_pred = final_model.predict(X_test_scaled)
    test_acc = accuracy_score(y_test, y_pred)
    test_f1 = f1_score(y_test, y_pred, average='macro', zero_division=0)
    elapsed = time.time() - t0

    results[model_name] = {
        'cv_f1_macro': round(cv_score, 4),
        'test_accuracy': round(test_acc, 4),
        'test_f1_macro': round(test_f1, 4),
        'params': {k: v for k, v in best_params.items() if k != 'random_state'},
        'time_s': round(elapsed, 1),
        'gap': round(test_f1 - cv_score, 4),
    }
    trained_models[model_name] = final_model

    print(f"  Test Accuracy: {test_acc:.4f}")
    print(f"  Test F1-macro: {test_f1:.4f}")
    print(f"  CV->Test gap:  {test_f1 - cv_score:+.4f}")
    print(f"  Time: {elapsed:.1f}s")

    if abs(test_f1 - cv_score) > 0.10:
        print(f"  WARNING: CV-test gap > 10%")
    sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 5: RESULTS & CHAMPION
# ═══════════════════════════════════════════════════════════════
ranking = sorted(results.items(), key=lambda x: x[1]['test_f1_macro'], reverse=True)
print(f"\n{'='*60}")
print("LEADERBOARD (by Test F1-macro):")
print(f"{'='*60}")
for i, (name, r) in enumerate(ranking):
    flag = " OVERFIT!" if r['gap'] > 0.10 else ""
    print(f"  {i+1}. {name:20s} F1={r['test_f1_macro']:.4f}  CV={r['cv_f1_macro']:.4f}  gap={r['gap']:+.4f}{flag}")

champion_name = ranking[0][0]
champion_model = trained_models[champion_name]
print(f"\nCHAMPION: {champion_name} (F1-macro={results[champion_name]['test_f1_macro']:.4f})")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 6: CHAMPION DEEP DIVE
# ═══════════════════════════════════════════════════════════════
y_pred_champ = champion_model.predict(X_test_scaled)
present_labels = sorted(set(y_test) | set(y_pred_champ))
label_names = [class_names[l] for l in present_labels]

print(f"\n{'='*60}")
print(f"CLASSIFICATION REPORT — {champion_name}")
print(f"{'='*60}")
print(classification_report(y_test, y_pred_champ, target_names=label_names, zero_division=0))

# Per-class analysis
report_dict = classification_report(y_test, y_pred_champ, target_names=label_names,
                                     zero_division=0, output_dict=True)
print("Per-class verdict:")
for cls in label_names:
    if cls in report_dict:
        r = report_dict[cls]
        f1_val = r['f1-score']
        verdict = "OK" if f1_val >= 0.7 else "WEAK" if f1_val >= 0.4 else "FAILING"
        print(f"  {cls:15s} F1={f1_val:.3f} P={r['precision']:.3f} R={r['recall']:.3f} n={int(r['support']):3d} {verdict}")

# Confusion matrix
cm = confusion_matrix(y_test, y_pred_champ, labels=present_labels)
print(f"\nConfusion Matrix:")
cm_df = pd.DataFrame(cm, index=label_names, columns=label_names)
print(cm_df.to_string())

# Feature importance
if hasattr(champion_model, 'feature_importances_'):
    fi_df = pd.DataFrame({'feature': FEATURE_COLS, 'importance': champion_model.feature_importances_})
    fi_df = fi_df.sort_values('importance', ascending=False).head(15)
    print(f"\nTop 15 Features:")
    for _, row in fi_df.iterrows():
        bar = '#' * int(row['importance'] * 100)
        print(f"  {row['feature']:30s} {row['importance']:.4f} {bar}")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 7: SAVE MODEL + MLFLOW
# ═══════════════════════════════════════════════════════════════
import pickle
from pathlib import Path
from datetime import datetime

model_dir = Path('data/models')
model_dir.mkdir(parents=True, exist_ok=True)
timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
model_path = model_dir / f'champion_{champion_name}_{timestamp}.pkl'
with open(model_path, 'wb') as f:
    pickle.dump({
        'model': champion_model,
        'scaler': scaler,
        'label_encoder': label_encoder,
        'feature_cols': FEATURE_COLS,
        'results': results[champion_name],
        'all_results': results,
    }, f)
print(f"\nModel saved: {model_path}")

try:
    import mlflow
    mlflow_uri = os.environ.get('MLFLOW_TRACKING_URI', 'http://mlflow:5005')
    mlflow.set_tracking_uri(mlflow_uri)
    mlflow.set_experiment("bubble_automl")
    with mlflow.start_run(run_name=f"automl_{champion_name}_{timestamp}"):
        mlflow.log_params(results[champion_name]['params'])
        mlflow.log_metrics({
            'test_f1_macro': results[champion_name]['test_f1_macro'],
            'test_accuracy': results[champion_name]['test_accuracy'],
            'cv_f1_macro': results[champion_name]['cv_f1_macro'],
            'cv_test_gap': results[champion_name]['gap'],
            'n_samples': len(df),
            'n_features': len(FEATURE_COLS),
            'n_classes': len(class_names),
        })
        mlflow.sklearn.log_model(champion_model, "model")
    print(f"Logged to MLflow ({mlflow_uri})")
except Exception as e:
    print(f"MLflow failed (non-critical): {e}")
sys.stdout.flush()

# ═══════════════════════════════════════════════════════════════
# STEP 8: PREDICTIONS ON ALL INVESTIGATIONS
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print("PREDICTIONS ACROSS ALL INVESTIGATIONS")
print(f"{'='*60}")

all_predictions = []
for inv_id in range(1, 9):
    try:
        wallets = loader.get_wallets(inv_id)
        transfers = loader.get_transfers(inv_id)
        if transfers.empty or wallets.empty:
            continue
        transfers = transfers.copy()
        transfers['from_address'] = transfers['from_address'].str.lower()
        transfers['to_address'] = transfers['to_address'].str.lower()

        extractor = WalletFeatureExtractor(transfers)
        feats = extractor.extract_all_features(min_tx_count=2)
        if feats.empty:
            continue
        feats_clean = feats[FEATURE_COLS].copy().replace([np.inf, -np.inf], np.nan).fillna(0)
        for col in VALUE_FEATURES:
            if col in feats_clean.columns:
                p995 = feats_clean[col].quantile(0.995)
                feats_clean[col] = np.log1p(feats_clean[col].clip(upper=max(p995, 1)).abs())
        feats_scaled = scaler.transform(feats_clean)
        preds = champion_model.predict(feats_scaled)
        pred_labels = label_encoder.inverse_transform(preds)
        inv_pred = pd.DataFrame({'wallet': feats.index, 'prediction': pred_labels, 'inv_id': inv_id})
        all_predictions.append(inv_pred)
        dist = pd.Series(pred_labels).value_counts().to_dict()
        print(f"  Inv #{inv_id}: {len(feats)} wallets -> {dist}")
    except Exception as e:
        print(f"  Inv #{inv_id}: ERROR - {e}")
    sys.stdout.flush()

if all_predictions:
    all_pred_df = pd.concat(all_predictions, ignore_index=True)
    pred_path = model_dir / f'predictions_{timestamp}.csv'
    all_pred_df.to_csv(pred_path, index=False)
    print(f"\n{len(all_pred_df)} total predictions saved to {pred_path}")
    print(f"\nOverall distribution:")
    print(all_pred_df['prediction'].value_counts().to_string())

# ═══════════════════════════════════════════════════════════════
# FINAL SUMMARY
# ═══════════════════════════════════════════════════════════════
print(f"\n{'='*60}")
print("AUTOML PIPELINE COMPLETE")
print(f"{'='*60}")
print(f"  Training samples:  {len(X_train_res)} (after SMOTE)")
print(f"  Test samples:      {len(X_test)}")
print(f"  Features:          {len(FEATURE_COLS)}")
print(f"  Classes:           {class_names}")
print(f"  Models trained:    {len(results)}")
print(f"  Champion:          {champion_name}")
print(f"  F1-macro (test):   {results[champion_name]['test_f1_macro']:.4f}")
print(f"  F1-macro (CV):     {results[champion_name]['cv_f1_macro']:.4f}")
print(f"  CV->Test gap:      {results[champion_name]['gap']:+.4f}")
gap = abs(results[champion_name]['gap'])
if gap > 0.10:
    print(f"  VERDICT: OVERFITTING (gap={gap:.1%}) — needs more data or regularization")
elif results[champion_name]['test_f1_macro'] < 0.5:
    print(f"  VERDICT: UNDERFITTING — features insufficient or classes too ambiguous")
else:
    print(f"  VERDICT: HEALTHY — model generalizes within tolerance")

# Save full results as JSON
import json
results_path = model_dir / f'results_{timestamp}.json'
with open(results_path, 'w') as f:
    json.dump(results, f, indent=2, default=str)
print(f"\n  Full results: {results_path}")
print(f"  Model: {model_path}")
sys.stdout.flush()
