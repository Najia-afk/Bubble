# Bubble ML Pipeline — Analysis Report
### Automated Wallet Classification System
**Generated:** 2026-02-07 | **Pipeline Version:** 1.0.0

---

## 1. Executive Summary

The Bubble ML pipeline successfully trained and evaluated **three supervised learning models** for blockchain wallet classification across 4 behavioral categories. All models achieved **98.95% test accuracy** with strong cross-validation performance. The **Random Forest** model was promoted to production based on the best cross-validation score (91.0%) with the lowest variance (±1.6%).

| Metric | Random Forest | Gradient Boosting | XGBoost |
|--------|:---:|:---:|:---:|
| Test Accuracy | 98.95% | 98.95% | 98.95% |
| F1 (weighted) | 98.99% | 98.99% | 98.99% |
| CV Mean (5-fold) | **91.00%** | 89.63% | 90.27% |
| CV Std | **±1.62%** | ±2.42% | ±2.27% |
| ROC-AUC | 99.94% | 99.99% | 99.97% |
| **Status** | **PRODUCTION** | Validated | Validated |

---

## 2. Data Pipeline

### 2.1 Investigation Coverage

| # | Case | Wallets | Transfers |
|---|------|------:|----------:|
| 1 | Multi-chain EVM Wallet Drain | 50 | 249 |
| 2 | Hypurr NFT Drain | 40 | 1,905 |
| 3 | Trust Wallet Extension Drain | 80 | 666 |
| 4 | Danny/Meech Genesis Theft | 3 | 35 |
| 5 | GANA Payment Exploit | 60 | 19,917 |
| 6 | Fake Hyperliquid App | 32 | 209,919 |
| 7 | Garden Finance Exploit | 80 | 206,814 |
| 8 | Private Key Compromise | 60 | 200,847 |
| **Total** | **8 Investigations** | **405** | **640,352** |

### 2.2 Feature Engineering

All features extracted via **GraphQL batch endpoint** → ORM-backed `InvestigationTransfer` aggregation:

| Feature | Description |
|---------|-------------|
| `tx_count` | Total transactions involving the wallet |
| `unique_counterparties` | Distinct addresses interacted with |
| `avg_tx_value` | Mean transaction value (log1p-transformed) |
| `max_tx_value` | Maximum single transaction value (log1p-transformed) |
| `in_out_ratio` | Ratio of incoming to outgoing transactions |
| `total_volume` | Sum of all transaction values (log1p-transformed) |
| `out_count` | Number of outgoing transactions |
| `in_count` | Number of incoming transactions |
| `unique_senders` | Distinct addresses sending to this wallet |
| `unique_receivers` | Distinct addresses receiving from this wallet |

**Preprocessing:** `np.log1p()` applied to value-based features to handle extreme skew, followed by `float32` clipping to prevent overflow.

---

## 3. Class Distribution

| Label | Count | Percentage | Description |
|-------|------:|-----------:|-------------|
| normal | 213 | 54.9% | Legitimate user wallets |
| bot | 138 | 35.6% | Automated/scripted wallets |
| exchange | 20 | 5.2% | Centralized exchange wallets |
| attacker | 17 | 4.4% | Malicious actor wallets |
| **Total** | **388** | 100% | |

### Class Imbalance Assessment

The dataset exhibits **moderate class imbalance**:
- The majority class (`normal`) represents 54.9% of samples
- Minority classes (`exchange`: 5.2%, `attacker`: 4.4%) have limited representation
- **SMOTE oversampling** was applied during training to mitigate imbalance
- The 381 usable samples (after feature extraction) across 4 classes provides adequate but not ideal training data

> **Risk:** With only 17 attacker and 20 exchange samples, per-class performance for minorities may be fragile. The high overall accuracy (98.95%) is partially inflated by the majority class performance.

---

## 4. Model Analysis

### 4.1 Random Forest ★ PRODUCTION

| Parameter | Value |
|-----------|-------|
| Algorithm | `RandomForestClassifier` (scikit-learn) |
| Test Accuracy | 98.95% |
| F1 Weighted | 98.99% |
| 5-Fold CV Mean | 91.00% ± 1.62% |
| ROC-AUC (OVR) | 99.94% |
| MLflow Run ID | `0df244afa24e4601b79037bd25a5f46d` |
| Pickle | `/tmp/bubble_models/random_forest_model.pkl` (873 KB) |

**Selected as production model because:**
- Highest cross-validation mean (91.0%) — most generalizable
- Lowest CV standard deviation (1.62%) — most stable across folds
- Naturally handles multi-class without modification
- Provides feature importance rankings out-of-box
- Robust to overfitting with ensemble averaging

### 4.2 Gradient Boosting

| Parameter | Value |
|-----------|-------|
| Algorithm | `GradientBoostingClassifier` (scikit-learn) |
| Test Accuracy | 98.95% |
| F1 Weighted | 98.99% |
| 5-Fold CV Mean | 89.63% ± 2.42% |
| ROC-AUC (OVR) | 99.99% |
| MLflow Run ID | `d34249cca17e47eca75257819ae0bbd0` |
| Pickle | `/tmp/bubble_models/gradient_boosting_model.pkl` (2.2 MB) |

**Notes:** Highest ROC-AUC (99.99%) but lowest CV score with highest variance, suggesting slight overfitting.

### 4.3 XGBoost

| Parameter | Value |
|-----------|-------|
| Algorithm | `XGBClassifier` (xgboost) |
| Test Accuracy | 98.95% |
| F1 Weighted | 98.99% |
| 5-Fold CV Mean | 90.27% ± 2.27% |
| ROC-AUC (OVR) | 99.97% |
| MLflow Run ID | `cd9b0a89047a4f1488556d14e7f642f2` |
| Pickle | `/tmp/bubble_models/xgboost_model.pkl` (556 KB) |

**Notes:** Second-best CV performance. Most compact model (556 KB). Deprecation warning for `use_label_encoder` parameter (cosmetic, no impact).

### 4.4 Cross-Model Observations

1. **Identical test metrics** across all 3 models (98.95% accuracy, 98.99% F1) — the test split is likely too small and/or the decision boundary is clear for the test subset
2. **CV scores differentiate models** — RF (91.0%) > XGB (90.3%) > GB (89.6%), providing the true generalization signal
3. **~8-9% gap between test and CV** suggests moderate overfitting across all models
4. All models benefit from SMOTE; without it, minority classes would likely be underrepresented in predictions

---

## 5. Architecture Achievements

### 5.1 Zero Raw SQL Policy ✅

**100% of application queries** now flow through SQLAlchemy ORM or GraphQL:

| Layer | Mechanism |
|-------|-----------|
| Feature extraction | GraphQL batch endpoint → `wallet_features_schema.py` |
| Label retrieval | GraphQL → `wallet_labels_schema.py` |
| Table discovery | `sqlalchemy.inspect().get_table_names()` |
| Dynamic tables | `get_transfer_event_class(symbol, trigram)` ORM factory |
| Dashboard stats | ORM `func.count()` + `sa_inspect()` |

**Files rewritten:** 11 production files, 28+ `text()` calls eliminated, 15+ f-string SQL injection risks removed.

**Only exceptions:** Advisory locks in `app.py` (`pg_try_advisory_lock`) and admin DDL in `db_drop.py` — both have no ORM equivalent.

### 5.2 Infrastructure

| Component | Technology | Status |
|-----------|-----------|--------|
| Web | Flask 3.x + Gunicorn (4 workers) | ✅ Running |
| Database | PostgreSQL 15 | ✅ Running |
| Cache/Queue | Redis 7 | ✅ Running |
| Async Tasks | Celery 5.x | ✅ Running |
| Reverse Proxy | Nginx | ✅ Running |
| ML Tracking | MLflow 2.19 | ✅ Running (model registry API mismatch) |
| Docker | 6 containers on `bubble_network` | ✅ All healthy |

---

## 6. Known Issues & Limitations

| Issue | Severity | Impact | Mitigation |
|-------|----------|--------|------------|
| MLflow `log_model` returns 404 | Medium | Models not in MLflow registry | Pickle fallback to `/tmp/bubble_models/` + `log_artifact()` |
| SHAP computation fails | Low | No SHAP feature importance plots | Feature importance available from model `.feature_importances_` attribute |
| Small minority classes (17-20 samples) | High | Per-class recall may be unreliable | SMOTE applied; collect more labeled data |
| Test/CV gap (~8-9%) | Medium | Potential overfitting | More data + hyperparameter tuning needed |
| `WalletClassifier` uses separate KMeans model | Medium | Production inference disconnected from ML pipeline | Wire `WalletClassifier` to load from `ModelMetadata.is_production` |
| XGBoost `use_label_encoder` deprecation | Cosmetic | Warning in logs | Update XGBoost params in next iteration |

---

## 7. Recommendations

### Immediate (Next Sprint)
1. **Wire production model to classifier** — Update `WalletClassifier._load_or_init_models()` to load the `is_production=True` model from `ModelMetadata` + pickle path instead of separate KMeans files
2. **Add per-class metrics** — Log precision/recall/F1 per class (especially `attacker` and `exchange`) to understand minority class performance
3. **Persist models to volume** — Mount `/tmp/bubble_models/` as a Docker volume to survive container restarts

### Short-Term (2-4 Weeks)
4. **Expand training data** — Target 50+ samples per class minimum; current `attacker` (17) and `exchange` (20) classes are underrepresented
5. **Hyperparameter optimization** — Run `GridSearchCV` or `Optuna` for each model type to close the test/CV gap
6. **Fix MLflow model registry** — Upgrade MLflow or fix the API endpoint versioning to enable proper model stage management
7. **Add temporal features** — Include time-based features (transaction frequency, time between transactions, active hours) from `InvestigationTransfer.block_timestamp`

### Long-Term
8. **Graph-based features** — Leverage TigerGraph for PageRank, community detection, and hop-distance features
9. **Ensemble production model** — Combine RF + XGB predictions via soft voting for improved robustness
10. **Drift monitoring** — Implement the `ModelMetadata.drift_detected` / `drift_score` mechanism with regular re-evaluation against new labeled wallets

---

## 8. Model Registry

| ID | Model | Version | Accuracy | F1 | ROC-AUC | Status |
|----|-------|---------|:--------:|:--:|:-------:|--------|
| 1 | Random Forest | `0df244afa2` | 98.95% | 98.99% | 99.94% | **PRODUCTION** |
| 2 | Gradient Boosting | `d34249cca1` | 98.95% | 98.99% | 99.99% | Validated |
| 3 | XGBoost | `cd9b0a8904` | 98.95% | 98.99% | 99.97% | Validated |

**Training data:** 381 samples × 10 features × 4 classes | **SMOTE:** enabled | **Test split:** 20%

---

*Report generated by Bubble ML Pipeline v1.0.0*
