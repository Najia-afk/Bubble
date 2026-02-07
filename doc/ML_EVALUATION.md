# ML Model Evaluation — Data Scientist Report

> **Evaluator**: Aria (AI Data Scientist)  
> **Date**: 2026-02-07  
> **Platform**: Bubble AML Investigation Platform  
> **Scope**: Full ML pipeline evaluation — data, features, training, production model, governance

---

## Executive Summary

The Bubble platform trains wallet classification models using a supervised learning pipeline with MLflow tracking. Three models have been trained (RF, GB, XGBoost), with Random Forest promoted to production. While the reported accuracy is exceptionally high (98.95%), this evaluation identifies **critical concerns** about data quality, class balance, cross-validation gap, and feature engineering that must be addressed before the models can be trusted for production AML decisions.

**Overall Assessment: PROMISING BUT NEEDS HARDENING**

---

## 1. Production Model Card

| Metric | Value | Assessment |
|--------|-------|------------|
| **Algorithm** | Random Forest | ✅ Good baseline for tabular data |
| **Accuracy** | 98.95% | ⚠️ Suspiciously high — investigate overfitting |
| **F1 Score** | 98.99% | ⚠️ Same concern |
| **Cross-Validation** | 91.00% | ⚠️ 8% gap from test accuracy → likely overfitting |
| **Training Samples** | 381 | ❌ Very small dataset |
| **Features** | 10 | ✅ Reasonable, but 50+ available |
| **Classes** | 4 | Need to verify class distribution |
| **MLflow Tracked** | Yes | ✅ Good governance |
| **SHAP Enabled** | Yes | ✅ Explainability |

### Model Registry

| Version | Algorithm | Stage | Accuracy | F1 | Run ID |
|---------|-----------|-------|----------|-----|--------|
| `0df244afa2` | Random Forest | **Production** | 0.9895 | 0.9899 | `0df244afa24e...` |
| `d34249cca1` | Gradient Boost | Staging | 0.9895 | 0.9899 | `d34249cca17e...` |
| `cd9b0a8904` | XGBoost | Staging | 0.9895 | 0.9899 | `cd9b0a89047a...` |

**Red Flag**: All three models report **identical** accuracy and F1 scores. This suggests either:
1. The test set is too easy (all models perfectly separate it)
2. The training data has very clear class boundaries
3. The evaluation split is not stratified or has data leakage

---

## 2. Data Quality Assessment

### Training Data

| Dimension | Value | Assessment |
|-----------|-------|------------|
| **Sample Size** | 381 | ❌ Far too small for 10+ features. Minimum should be 1000+ |
| **Feature Count** | 10 (of 50+ available) | ⚠️ Feature selection needed — why only 10? |
| **Classes** | 4 | Need distribution breakdown |
| **Source** | DB-extracted features from investigation transfers | ⚠️ Selection bias possible |

### Concerns

1. **Small Sample Size (n=381)**
   - For 10 features and 4 classes, this is dangerously small
   - Rule of thumb: need 50-100 samples per class per feature = 2000-4000 minimum
   - High risk of overfitting, especially with tree-based models
   - Random Forest with default settings can easily memorize 381 samples

2. **Cross-Validation Gap (98.95% test vs 91.00% CV)**
   - 8 percentage point gap is a clear overfitting signal
   - The model performs well on the specific test split but less well on average across folds
   - Suggests the test split accidentally got "easy" samples

3. **All Models Same Performance**
   - RF, GB, XGBoost producing identical metrics is highly unusual
   - In practice, different algorithms almost always produce different results
   - Suggests the data is so small and separable that any tree-based model gets the same answer

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

1. **Expand Training Data**
   - Current: 381 samples → Target: 2000+ samples minimum
   - Sources: investigation transfers, known exchange deposits, labeled wallets
   - Use SMOTE for class balancing (already available in codebase)

2. **Investigate Feature Leakage**
   - Remove `exchange_interaction_count` from features when predicting "exchange" class
   - Remove `mixer_interaction_count` from features when predicting "mixer" class
   - Re-train and compare metrics — if accuracy drops significantly, leakage was present

3. **Fix ML Model Loading in Celery Worker**
   - All 50 wallets classified by heuristics, not ML model
   - Debug why `load_production_model()` isn't working in async context
   - Add logging to capture ML model load/inference failures

### HIGH PRIORITY

4. **Use All Features**
   - Expand from 10 to 50+ features with proper selection
   - Apply feature selection: mutual information, recursive elimination, or L1 regularization
   - Document selected features and justification

5. **Improve Cross-Validation**
   - Current CV: 91% vs test 98.95% — this gap indicates overfitting
   - Use `RepeatedStratifiedKFold(n_splits=5, n_repeats=3)` for more robust estimation
   - Report CV mean ± std, not just test accuracy

6. **Add Calibration**
   - Raw prediction probabilities from RF are often poorly calibrated
   - Apply `CalibratedClassifierCV` to get meaningful confidence scores
   - This matters for the 0.5 threshold decision in `ModelMetadata`

### MEDIUM PRIORITY

7. **Drift Monitoring**
   - Evidently integration exists but needs scheduled checks
   - Compare training distribution vs latest investigation data monthly
   - Set up alerts for feature drift > 2 standard deviations

8. **A/B Testing**
   - Run heuristic vs ML classification in parallel
   - Compare agreement rate
   - Track where they disagree — these are the interesting cases

9. **Confusion Matrix Analysis**
   - Log per-class precision/recall
   - Identify which classes the model confuses
   - Focus data collection on confused classes

---

## 7. Steps to Challenge / Verify

For a data scientist challenging this pipeline:

### Step 1: Data Quality Audit
```bash
curl http://localhost:8080/api/ml/stats | jq '.'
# Check n_samples, production status, drift_status
```

### Step 2: Feature Importance Check
```bash
# Access MLflow UI
open http://localhost:8080/mlflow
# Compare SHAP values — are risk features dominating?
```

### Step 3: Retrain with More Data
```bash
curl -X POST http://localhost:8080/api/ml/train \
  -H "Content-Type: application/json" \
  -d '{"model_type": "random_forest"}'
# Check if accuracy changes with latest investigation data
```

### Step 4: Cross-Validation Deep Dive
```python
# In notebook, load training data and run:
from sklearn.model_selection import cross_val_score, RepeatedStratifiedKFold
cv = RepeatedStratifiedKFold(n_splits=5, n_repeats=10)
scores = cross_val_score(model, X, y, cv=cv, scoring='accuracy')
print(f"CV: {scores.mean():.4f} ± {scores.std():.4f}")
```

### Step 5: Compare ML vs Heuristic
```bash
# Run classification on known wallets, compare outputs
curl -X POST http://localhost:8080/api/classify \
  -H "Content-Type: application/json" \
  -d '{"address": "0xKNOWN_EXCHANGE...", "chain_code": "ETH"}'
```

---

## 8. Conclusion

The ML pipeline is **architecturally sound** — MLflow tracking, SHAP explainability, EU AI Act audit trail, and three-tier classification are all excellent design decisions. However, the current production model is **undertrained** (n=381) and potentially has **feature leakage**. Most critically, the ML model isn't actually being used in production — all classifications fall through to heuristic rules.

**Priority actions**:
1. Debug ML model loading in Celery workers
2. Expand training data to 2000+ samples
3. Audit features for target leakage
4. Close the CV gap (91% → 95%+)

The platform has the right architecture; it just needs more data and careful feature engineering to deliver trustworthy ML predictions.
