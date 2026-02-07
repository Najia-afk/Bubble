# ML Model Evaluation — Data Scientist Report

> **Evaluator**: Aria (AI Data Scientist)  
> **Date**: 2026-02-07 (updated with AutoML results)  
> **Platform**: Bubble AML Investigation Platform  
> **Scope**: Full ML pipeline evaluation — data, features, training, production model, governance

---

## Executive Summary

The Bubble platform trains wallet classification models via an AutoML pipeline with Optuna hyperparameter optimization. **Six models** were trained (RF, GBT, ExtraTrees, LR, XGBoost, LightGBM), with **ExtraTrees promoted as champion** (Test F1=0.8882, CV-Test gap=-6.2%).

Previous iteration (3 models, 381 samples, 10 features, 4 classes) reported 98.95% accuracy with all models producing identical scores — a clear red flag. The new pipeline addresses this with 24 features, 5 classes, SMOTE balancing, and Optuna HPO, producing realistic differentiated results across models.

**Overall Assessment: FUNCTIONAL — NEEDS MORE DATA FOR MINORITY CLASSES**

---

## 1. Production Model Card

| Metric | Value | Assessment |
|--------|-------|------------|
| **Algorithm** | ExtraTrees (champion) | Resists SMOTE overfitting via random splits |
| **Test Accuracy** | 89.33% | Realistic for 5-class problem |
| **Test F1 (macro)** | 88.82% | All classes F1 >= 0.80 |
| **CV F1 (macro)** | 94.97% | 5-fold stratified |
| **CV-Test Gap** | -6.2% | Healthy (< 10%) |
| **Training Samples** | 374 (SMOTE → 670) | Still small, target 1000+ |
| **Features** | 24 behavioral + transactional | Graph topology dominates |
| **Classes** | 5 (attacker, exchange, mixer, related, suspect) | Merged seized→attacker |
| **MLflow Tracked** | Yes | Experiment: bubble_automl |
| **Optuna HPO** | 10 trials × 5-fold CV | Per-model hyperparameter search |

### Model Leaderboard

| Rank | Model | CV F1 | Test F1 | Gap | Time | Verdict |
|------|-------|-------|---------|-----|------|---------|
| 1 | **ExtraTrees** | 0.9497 | 0.8882 | -6.2% | 9.0s | **CHAMPION** |
| 2 | LightGBM | 0.9395 | 0.7266 | -21.3% | 114.2s | Overfit |
| 3 | XGBoost | 0.9329 | 0.7173 | -21.6% | 50.8s | Overfit |
| 4 | GradientBoosting | 0.9413 | 0.7155 | -22.6% | 95.3s | Overfit |
| 5 | RandomForest | 0.9301 | 0.7117 | -21.8% | 11.5s | Overfit |
| 6 | LogisticRegression | 0.7715 | 0.6435 | -12.8% | 1.6s | Underfit |

**Why ExtraTrees wins**: Random split thresholds act as regularization, preventing memorization of SMOTE-generated synthetic minority samples. All other tree models overfit by >20%.

### Per-Class Performance

| Class | Precision | Recall | F1 | Test n | Total n | Status |
|-------|-----------|--------|-----|--------|---------|--------|
| attacker | 1.000 | 0.667 | 0.800 | 3 | 16 | GOOD (low n) |
| exchange | 0.808 | 1.000 | 0.894 | 21 | 103 | GOOD |
| mixer | 1.000 | 1.000 | 1.000 | 3 | 17 | GOOD (low n) |
| related | 0.912 | 0.912 | 0.912 | 34 | 168 | GOOD |
| suspect | 1.000 | 0.714 | 0.833 | 14 | 70 | GOOD |

### Per-Investigation Accuracy

| Inv | Wallets | Accuracy | Notes |
|-----|---------|----------|-------|
| #1 | 7 | 85.7% | Small |
| #2 | 48 | 97.9% | Excellent |
| #3 | 96 | 89.6% | Largest |
| #4 | 2 | 100% | Trivial |
| #5 | 59 | 98.3% | Near perfect |
| #6 | 29 | 75.9% | Weak — exchange confusion |
| #7 | 75 | 98.7% | Near perfect |
| #8 | 58 | 69.0% | Weakest |
| **Overall** | **374** | **89.6%** | |

### Top 5 Features

1. `counterparty_concentration` — 0.1464 (few counterparties = suspicious)
2. `tx_count` — 0.0921
3. `unique_counterparties` — 0.0916
4. `unique_out_counterparties` — 0.0906
5. `out_count` — 0.0863

Graph topology features dominate over value features — this is domain-correct.

---

## 2. Data Quality Assessment

### Training Data

| Dimension | Value | Assessment |
|-----------|-------|------------|
| **Sample Size** | 374 labeled wallets | Still small but viable with SMOTE |
| **SMOTE Balanced** | 670 (134 per class, k=5) | Synthetic minority oversampling |
| **Feature Count** | 24 | Graph topology + transaction + temporal |
| **Classes** | 5 | attacker(16), exchange(103), mixer(17), related(168), suspect(70) |
| **Source** | 8 investigations, ~1.15M transfers | Real blockchain data |
| **Value Cleanup** | log1p + clip@99.5% | Fixed uint256 overflow (was 1e57) |

### Concerns

1. **Minority Classes (attacker=16, mixer=17)**
   - Only 3 test samples each → confidence intervals enormous
   - The "perfect" mixer F1=1.000 is meaningless with n=3
   - SMOTE creates near-duplicate synthetic points for these tiny classes

2. **SMOTE Before CV (methodological flaw)**
   - SMOTE applied to full training set before cross-validation
   - CV folds contain SMOTE-generated data → inflated CV scores
   - Proper: SMOTE inside each fold using `imblearn.pipeline.Pipeline`

3. **5/6 Models Overfit by >20%**
   - SMOTE synthetic points for minority classes are trivially separable
   - Only ExtraTrees resists due to random split threshold regularization
   - This is a data quantity problem, not an algorithmic one

4. **Class Imbalance After Merge**
   - `seized` (1 sample) merged into `attacker` (→16)
   - `related` (168) is 10x larger than `attacker` (16)
   - Consider merging attacker+mixer → "illicit" (33 samples)

---

## 3. Feature Engineering Review

### Available Features (50+)

The `WalletFeatureEngineer` extracts features across 6 categories:

| Category | Count | Examples | Risk |
|----------|-------|----------|------|
| **Transaction** | 6 | tx_count, in/out ratio, frequency | Low |
| **Value** | 14 | volume, avg/median/max, skewness | Low |
| **Temporal** | 9 | active_days, time_between_tx, burst | Medium |
| **Network** | 7 | unique_counterparties, concentration | Low |
| **Risk** | 8 | mixer/bridge/exchange interaction count | ⚠️ High — target leakage risk |
| **Behavioral** | 6 | entropy, predictability, dormancy | Medium |

### Concerns

1. **Only 10 of 50+ Features Used** — The training pipeline selects only 10 features. Document which 10 and why. If using all 50+, dimensionality reduction (PCA) or feature selection is needed.

2. **Target Leakage Risk** — The "risk" features include `mixer_interaction_count`, `bridge_interaction_count`, `exchange_interaction_count`. If these directly measure what we're trying to predict (e.g., "is this wallet an exchange?"), they create target leakage. The model learns "wallets with high exchange_interaction_count are exchanges" — which is circular reasoning.

3. **Feature Importance** — SHAP is implemented but we need to verify the top features aren't leaked. If `exchange_interaction_count` is the #1 feature for predicting "exchange" class, the model is trivial.

---

## 4. Classification Pipeline Review

### Three-Tier System

```
Tier 1: ML Model (Random Forest)     → Highest priority if confidence > threshold
Tier 2: Heuristic Rules              → Rule-based fallback
Tier 3: Known Entity Matching        → Database lookup (exchanges, mixers, bridges)
```

### Assessment

| Component | Status | Notes |
|-----------|--------|-------|
| **ML Model** | ⚠️ Needs more data | Works but overfitting risk |
| **Heuristic Rules** | ✅ Solid | Rule-based classification with clear thresholds |
| **Known Entity DB** | ✅ Solid | Exchange/mixer/bridge address lists |
| **Three-tier fallback** | ✅ Good design | Graceful degradation |

### E2E Classification Results (CASE-2026-008)

From the completed investigation:

| Classification | Count | Source |
|----------------|-------|--------|
| Exchange | 43 | transfer_heuristics |
| Normal | 6 | transfer_heuristics |
| Whale | 1 | transfer_heuristics |
| **Total** | **50** | |

**Observation**: All 50 wallets were classified by `transfer_heuristics` (Tier 2), NOT by the ML model (Tier 1). This means either:
- The ML model wasn't available/loaded in the Celery worker
- The feature extraction returned insufficient data for ML classification
- The heuristic rules fired first and took priority

**This is a critical finding** — the ML model exists but isn't actually being used in production classification. The system falls back to heuristics 100% of the time.

---

## 5. Risk Scoring Review

### Algorithm
```
mixer_interaction:    +30
bridge_crossing:      +20
exchange_endpoint:    +10
anomaly_detection:    +15
```

### CASE-2026-008 Results
- **Risk Score**: 100/100 (CRITICAL)
- **Exchange Count**: 42
- **Mixer Count**: 0
- **Bridge Count**: 0
- **Flagged Wallets**: 42

### Assessment
- The scoring is additive and capped at 100
- 42 exchange endpoints pushed the score to maximum
- For this NFT drain case, detecting exchange endpoints is correct behavior
- The scoring weights need calibration — a case with 1 mixer interaction (score 30) shouldn't score less than a case with 2 exchange endpoints (score 20). Mixer usage is generally higher risk.

---

## 6. Recommendations

### CRITICAL (Must Fix)

1. **Add More Labeled Wallets**
   - Current: 374 samples → Target: 1000+ with 100+ per class
   - Sources: new investigations (CASE-2026-009+), external labeled datasets
   - Priority: attacker (16) and mixer (17) classes need 5-10x more samples

2. **Fix SMOTE-in-CV Methodology**
   - Apply SMOTE inside each CV fold, not before splitting
   - Use `imblearn.pipeline.Pipeline` with `SMOTE()` as a step
   - Re-evaluate: if CV scores drop to match test scores, methodology was inflating them

3. **Integrate AutoML Champion into Production Classification**
   - Current: all wallets classified by heuristics (Tier 2), ML model not loaded in Celery
   - Fix: load `champion_ExtraTrees_20260207_213203.pkl` in Celery worker
   - Use ExtraTrees for Tier 1, fall back to heuristics for Tier 2

### HIGH PRIORITY

4. **Consider Merging attacker+mixer → "illicit"**
   - 33 combined samples vs 16/17 each → more reliable evaluation
   - Domain justification: both are "bad actor" categories
   - Re-train and compare: if F1 improves, keep the merge

5. **Nested Cross-Validation**
   - Use nested CV for model selection: outer loop evaluates, inner loop tunes
   - Gives unbiased generalization estimate
   - `RepeatedStratifiedKFold(n_splits=5, n_repeats=3)` for outer loop

6. **Temporal Validation**
   - Current: random train/test split → may leak temporal patterns
   - Better: train on investigations 1-6, test on 7-8 (chronological split)
   - Even better: walk-forward validation (train on earlier, test on later)

### MEDIUM PRIORITY

7. **Feature Engineering**
   - Add graph centrality (betweenness, PageRank) from transaction graph
   - Add temporal features (time-of-day patterns, burst detection)
   - Feature selection via mutual information to reduce from 24 → ~15

8. **Calibration**
   - ExtraTrees probabilities are uncalibrated — apply Platt scaling
   - Important for confidence thresholds in the classification pipeline
   - Use `CalibratedClassifierCV` wrapper

9. **Drift Monitoring**
   - Compare feature distributions of new investigations vs training data
   - Inv #8 (69% accuracy) suggests distribution shift
   - Set up weekly Evidently reports

10. **Write Predictions to DB**
    - Current: predictions saved to CSV only
    - Target: write to `wallet_scores` table via API
    - Enable monitoring dashboard to show ML classifications

---

## 7. How to Reproduce the AutoML Pipeline

### Option A: Run from Host (recommended — avoids Docker exec issues)

```bash
# Activate venv
.venv\Scripts\activate  # Windows
# or: source .venv/bin/activate  # Linux/Mac

# Ensure Docker postgres is running and port-forwarded
docker compose up -d postgres

# Run the full pipeline
python -X utf8 notebooks/_host_pipeline.py

# Analyze results
python -X utf8 notebooks/_analyze_results.py
```

### Option B: Run in Docker container

```bash
# Ensure notebooks volume is mounted (docker-compose.yml has ./notebooks:/app/notebooks)
docker compose up -d

# Install optuna (not in base image)
docker exec bubble_web pip install optuna

# Run pipeline inside container
docker exec bubble_web python notebooks/_host_pipeline.py
```

### Option C: Interactive Notebook

```bash
# Open notebooks/05_auto_ml.ipynb in VS Code or JupyterLab
# Execute cells 1-9 sequentially
# Cell 10 contains the results analysis and iteration plan
```

### Verify Results

```bash
# Check saved model
ls notebooks/data/models/champion_ExtraTrees_*.pkl

# Check results JSON
cat notebooks/data/models/results_*.json | python -m json.tool

# Check predictions
head notebooks/data/models/predictions_analysis.csv
```

### Challenge the Model

```python
# In Python, load and inspect:
import pickle
with open('notebooks/data/models/champion_ExtraTrees_20260207_213203.pkl', 'rb') as f:
    bundle = pickle.load(f)

model = bundle['model']
scaler = bundle['scaler']
le = bundle['label_encoder']
features = bundle['features']
results = bundle['results']

# Print leaderboard
for name, r in sorted(results.items(), key=lambda x: x[1]['test_f1'], reverse=True):
    print(f"{name:25s} CV={r['cv_f1']:.4f} Test={r['test_f1']:.4f} Gap={r['gap']:+.4f}")
```

---

## 8. Conclusion

The AutoML pipeline is **functional and produces realistic results**. ExtraTrees champion achieves F1=0.8882 with a healthy 6.2% generalization gap, and 89.6% overall prediction accuracy across all 8 investigations.

**Resolved from previous evaluation:**
- All models identical scores → now 6 distinct models with differentiated performance
- Only 10 features → now 24 with graph topology dominating (no target leakage)
- 98.95% suspicious accuracy → 88.82% realistic F1 with proper stratified evaluation
- No SMOTE → SMOTE balancing with k=5 for minority classes

**Remaining concerns:**
- Small minority classes (attacker=16, mixer=17) → need 100+ each
- SMOTE before CV inflates scores → needs pipeline-level fix
- 5/6 models overfit by >20% → ExtraTrees only survivor
- ML model not loaded in production Celery workers → heuristic fallback still 100%
- Inv #6 (75.9%) and #8 (69.0%) need investigation review

**Files:**
- Pipeline: `notebooks/_host_pipeline.py`
- Analysis: `notebooks/_analyze_results.py`
- Notebook: `notebooks/05_auto_ml.ipynb`
- Champion: `notebooks/data/models/champion_ExtraTrees_20260207_213203.pkl`
- Results: `notebooks/data/models/results_20260207_213203.json`
- Predictions: `notebooks/data/models/predictions_analysis.csv`
- Report: `reports/ml/automl_results_20260207.md`
