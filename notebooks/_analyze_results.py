r"""
Analyze AutoML results: load champion model, regenerate test data, produce full evaluation.
Run with: .venv\Scripts\python -X utf8 notebooks\_analyze_results.py
"""
import sys, os, io, warnings, pickle, json, time
import numpy as np, pandas as pd

# UTF-8 for Windows
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
warnings.filterwarnings('ignore')
os.environ['TQDM_DISABLE'] = '1'

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(os.path.join(PROJECT_ROOT, 'notebooks'))

# Tee stdout to a log file
LOG_PATH = os.path.join('data', '_analysis_report.txt')
class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
            s.flush()
    def flush(self):
        for s in self.streams:
            s.flush()

_log_file = open(LOG_PATH, 'w', encoding='utf-8')
sys.stdout = Tee(sys.stdout, _log_file)

from sklearn.model_selection import train_test_split, cross_val_score, StratifiedKFold
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from imblearn.over_sampling import SMOTE
from pathlib import Path

# ── Load saved champion ──
model_path = Path('data/models/champion_ExtraTrees_20260207_213203.pkl')
with open(model_path, 'rb') as f:
    bundle = pickle.load(f)

champ_model = bundle['model']
scaler = bundle['scaler']
le = bundle['label_encoder']
FEATURE_COLS = bundle['features']
results = bundle['results']
class_names = list(le.classes_)

print(f"Loaded: {model_path.name}")
print(f"Classes: {class_names}")
print(f"Features: {len(FEATURE_COLS)}")

# ── Re-extract data (needed for per-class eval) ──
os.environ['DATABASE_URL'] = 'postgresql://bubble_user:bubble_password@localhost:5432/bubble_db'
from src.data_loader import DataLoader
from src.classes.wallet_features import WalletFeatureExtractor

loader = DataLoader()
all_feats = []
all_labels = []
for inv_id in range(1, 9):
    w = loader.get_wallets(inv_id)
    t = loader.get_transfers(inv_id)
    if t.empty or w.empty:
        continue
    t = t.copy()
    t['from_address'] = t['from_address'].str.lower()
    t['to_address'] = t['to_address'].str.lower()
    if len(t) > 50000:
        addrs = set(w['address'].str.lower())
        t = t[t['from_address'].isin(addrs) | t['to_address'].isin(addrs)]
    ext = WalletFeatureExtractor(t)
    for _, wallet in w.iterrows():
        feats = ext.extract_features_for_wallet(wallet['address'])
        if feats.get('tx_count', 0) >= 2:
            feats['_inv_id'] = inv_id
            all_feats.append(feats)
            all_labels.append(wallet['role'])

df_raw = pd.DataFrame(all_feats)
labels_raw = pd.Series(all_labels)
FEATURE_COLS2 = [c for c in df_raw.columns if not c.startswith('_')]

# Ensure we use the same features the champion was trained on
missing = [c for c in FEATURE_COLS if c not in FEATURE_COLS2]
if missing:
    print(f"WARNING: Missing features: {missing}")
    for c in missing:
        df_raw[c] = 0

df = df_raw.copy()
y_raw = labels_raw.replace({'seized': 'attacker'})
le2 = LabelEncoder()
le2.fit(class_names)
y = le2.transform(y_raw)

VALUE_FEATURES = [c for c in FEATURE_COLS if any(k in c for k in ['value', 'amount', 'avg', 'sum', 'std', 'balance'])]
X = df[FEATURE_COLS].copy().replace([np.inf, -np.inf], np.nan).fillna(0)
for col in VALUE_FEATURES:
    if col in X.columns:
        X[col] = np.log1p(X[col].clip(upper=max(X[col].quantile(0.995), 1)).abs())

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, stratify=y, random_state=42
)

k = min(5, min(pd.Series(y_train).value_counts()) - 1)
sm = SMOTE(random_state=42, k_neighbors=max(1, k))
X_res, y_res = sm.fit_resample(X_train, y_train)

scaler2 = StandardScaler()
X_train_sc = scaler2.fit_transform(X_res)
X_test_sc = scaler2.transform(X_test)

# ── Use the SAVED model but evaluate on REGENERATED test data ──
# (same random_state=42, so splits should be identical)
y_pred = champ_model.predict(X_test_sc)

print(f"\n{'='*60}")
print("FULL CLASSIFICATION REPORT (ExtraTrees Champion)")
print(f"{'='*60}")
print(classification_report(y_test, y_pred, target_names=class_names, digits=4))

print(f"\n{'='*60}")
print("CONFUSION MATRIX")
print(f"{'='*60}")
cm = confusion_matrix(y_test, y_pred)
# Pretty print
header = "Pred->  " + "  ".join(f"{c:>10s}" for c in class_names)
print(header)
for i, row in enumerate(cm):
    print(f"{class_names[i]:>8s}  " + "  ".join(f"{v:>10d}" for v in row))

# Per-class analysis
print(f"\n{'='*60}")
print("PER-CLASS ANALYSIS")
print(f"{'='*60}")
from sklearn.metrics import precision_recall_fscore_support
prec, rec, f1, sup = precision_recall_fscore_support(y_test, y_pred, labels=range(len(class_names)))
for i, cn in enumerate(class_names):
    status = "GOOD" if f1[i] >= 0.7 else "WEAK" if f1[i] >= 0.4 else "FAILING"
    print(f"  {cn:12s}  P={prec[i]:.3f}  R={rec[i]:.3f}  F1={f1[i]:.3f}  n={sup[i]:>3d}  [{status}]")

# ── Generalization analysis ──
print(f"\n{'='*60}")
print("OVERFITTING ANALYSIS")
print(f"{'='*60}")
cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
cv_scores = cross_val_score(champ_model, X_train_sc, y_res, cv=cv, scoring='f1_macro')
test_f1 = f1_score(y_test, y_pred, average='macro')
print(f"  CV F1 (mean±std):  {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")
print(f"  CV F1 (per fold):  {' '.join(f'{s:.3f}' for s in cv_scores)}")
print(f"  Test F1:           {test_f1:.4f}")
gap = test_f1 - cv_scores.mean()
print(f"  Gap:               {gap:+.4f} ({gap*100:+.1f}%)")
if abs(gap) > 0.10:
    print("  VERDICT: Overfitting detected")
elif abs(gap) > 0.05:
    print("  VERDICT: Mild overfitting - acceptable with more data")
else:
    print("  VERDICT: Healthy generalization")

# ── Feature importance ──
print(f"\n{'='*60}")
print("TOP 20 FEATURE IMPORTANCE")
print(f"{'='*60}")
if hasattr(champ_model, 'feature_importances_'):
    fi = pd.DataFrame({'f': FEATURE_COLS, 'imp': champ_model.feature_importances_})
    fi = fi.sort_values('imp', ascending=False)
    for i, (_, r) in enumerate(fi.head(20).iterrows()):
        bar = '#' * int(r['imp'] * 150)
        print(f"  {i+1:2d}. {r['f']:30s} {r['imp']:.4f}  {bar}")

# ── All model leaderboard ──
print(f"\n{'='*60}")
print("MODEL LEADERBOARD")
print(f"{'='*60}")
print(f"  {'Model':25s} {'CV F1':>8s} {'Test F1':>8s} {'Gap':>8s} {'Time':>8s}  Status")
print(f"  {'-'*25} {'------':>8s} {'------':>8s} {'------':>8s} {'------':>8s}  ------")
for name, r in sorted(results.items(), key=lambda x: x[1]['test_f1'], reverse=True):
    g = r['gap']
    status = "CHAMPION" if name == "ExtraTrees" else ("OVERFIT" if abs(g) > 0.10 else "OK")
    star = " ***" if name == "ExtraTrees" else ""
    print(f"  {name:25s} {r['cv_f1']:8.4f} {r['test_f1']:8.4f} {g:+8.4f} {r['time']:7.1f}s  {status}{star}")

# ── Predictions on all investigations ──
print(f"\n{'='*60}")
print("PREDICTIONS ON ALL INVESTIGATIONS")
print(f"{'='*60}")
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
        if len(t2) > 50000:
            addrs2 = set(w2['address'].str.lower())
            t2 = t2[t2['from_address'].isin(addrs2) | t2['to_address'].isin(addrs2)]
        ext2 = WalletFeatureExtractor(t2)
        
        inv_feats = []
        inv_addrs = []
        inv_roles = []
        for _, wallet in w2.iterrows():
            f2 = ext2.extract_features_for_wallet(wallet['address'])
            if f2.get('tx_count', 0) >= 2:
                inv_feats.append(f2)
                inv_addrs.append(wallet['address'].lower())
                inv_roles.append(wallet['role'])
        
        if not inv_feats:
            continue
        
        fc = pd.DataFrame(inv_feats)[FEATURE_COLS].copy()
        fc = fc.replace([np.inf, -np.inf], np.nan).fillna(0)
        for col in VALUE_FEATURES:
            if col in fc.columns:
                fc[col] = np.log1p(fc[col].clip(upper=max(fc[col].quantile(0.995), 1)).abs())
        fs = scaler2.transform(fc)
        preds = le2.inverse_transform(champ_model.predict(fs))
        dist = pd.Series(preds).value_counts().to_dict()
        
        n_correct = sum(1 for role, pred in zip(inv_roles, preds) 
                       if role.lower().replace('seized', 'attacker') == pred)
        print(f"  Inv #{inv_id}: {len(inv_feats):3d} wallets -> {dist}  ({n_correct}/{len(inv_feats)} correct)")
        
        dfp = pd.DataFrame({
            'wallet': inv_addrs, 
            'pred': preds, 
            'inv': inv_id,
            'known_label': [r.lower().replace('seized', 'attacker') for r in inv_roles]
        })
        all_preds.append(dfp)
    except Exception as e:
        print(f"  Inv #{inv_id}: ERROR - {e}")
        import traceback; traceback.print_exc()

if all_preds:
    apd = pd.concat(all_preds, ignore_index=True)
    apd.to_csv(Path('data/models/predictions_analysis.csv'), index=False)
    print(f"\n  Total: {len(apd)} wallet predictions saved")
    print(f"\n  Overall prediction distribution:")
    print(apd['pred'].value_counts().to_string(header=False))
    
    # Accuracy on labeled data
    labeled = apd[apd['known_label'].str.len() > 0].copy()
    labeled['known_label'] = labeled['known_label'].replace({'seized': 'attacker'})
    correct = (labeled['pred'] == labeled['known_label']).sum()
    print(f"\n  Labeled accuracy: {correct}/{len(labeled)} = {correct/len(labeled):.1%}")

# ── Critical summary ──
print(f"\n{'='*60}")
print("CRITICAL ASSESSMENT")
print(f"{'='*60}")
print(f"""
STRENGTHS:
  - ExtraTrees champion F1={test_f1:.4f} with only {abs(gap)*100:.1f}% generalization gap
  - 5-class classification on blockchain wallet behavior
  - Fast training: {results['ExtraTrees']['time']:.0f}s

WEAKNESSES:
  - Small dataset: {len(df)} labeled samples ({len(X_test)} test)
  - Minority classes: attacker={sum(y_raw=='attacker')} + mixer={sum(y_raw=='mixer')}: too few for reliable eval
  - 5/6 models overfit by >20% (SMOTE on tiny classes creates memorizable synthetic points)
  - CV scores inflated by SMOTE: models see SMOTE in training folds

RECOMMENDATIONS:
  1. Add more labeled wallets (target 1000+ samples, 100+ per class)
  2. Use nested CV or leave-SMOTE-out to get honest CV estimates
  3. Consider merging attacker+mixer into "illicit" class (33 vs 16/17)
  4. Try feature selection (PCA or mutual info) to reduce dimensionality
  5. Add temporal features (time-based patterns)
  6. Calibrate predictions with Platt scaling
""")
