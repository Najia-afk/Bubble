# AutoML Pipeline — Complete Results Report

**Date**: 2026-02-07  
**Champion Model**: ExtraTrees  
**Pipeline**: `notebooks/_host_pipeline.py` → `notebooks/05_auto_ml.ipynb`  
**Data**: 8 investigations, 374 labeled wallets, 24 features, 5 classes

---

## 1. Data Summary

| Metric | Value |
|--------|-------|
| Investigations | 8 |
| Total transfers | ~1.15M |
| Labeled wallets | 374 (after min_tx_count=2 filter) |
| Features | 24 behavioral + transactional |
| Classes | attacker (16), exchange (103), mixer (17), related (168), suspect (70) |
| SMOTE balanced | 670 (134 per class, k=5) |
| Train/Test split | 299/75 (stratified, random_state=42) |

### Class Imbalance
The dataset is heavily imbalanced: `related` (45%) dominates while `attacker` (4%) and `mixer` (5%) are dangerously small. SMOTE upsamples minority classes but creates near-duplicate synthetic points when k=5 and n=12-13 train samples.

---

## 2. Model Leaderboard

| Rank | Model | CV F1 | Test F1 | Gap | Time | Verdict |
|------|-------|-------|---------|-----|------|---------|
| 1 | **ExtraTrees** | **0.9497** | **0.8882** | **-6.2%** | **9.0s** | **CHAMPION** |
| 2 | LightGBM | 0.9395 | 0.7266 | -21.3% | 114.2s | Overfit |
| 3 | XGBoost | 0.9329 | 0.7173 | -21.6% | 50.8s | Overfit |
| 4 | GradientBoosting | 0.9413 | 0.7155 | -22.6% | 95.3s | Overfit |
| 5 | RandomForest | 0.9301 | 0.7117 | -21.8% | 11.5s | Overfit |
| 6 | LogisticRegression | 0.7715 | 0.6435 | -12.8% | 1.6s | Underfit |

### Why ExtraTrees Wins
ExtraTrees (Extremely Randomized Trees) selects random split thresholds instead of computing optimal ones. This built-in randomness acts as a powerful regularizer that prevents the memorization of SMOTE-generated synthetic minority samples. All other tree-based models (RF, GBT, XGB, LGB) overfit by >20% because they find optimal splits that perfectly separate the near-duplicate SMOTE points.

---

## 3. Champion Evaluation (ExtraTrees)

### Classification Report
```
              precision    recall  f1-score   support
    attacker     1.0000    0.6667    0.8000         3
    exchange     0.8077    1.0000    0.8936        21
       mixer     1.0000    1.0000    1.0000         3
     related     0.9118    0.9118    0.9118        34
     suspect     1.0000    0.7143    0.8333        14
    accuracy                         0.8933        75
   macro avg     0.9439    0.8585    0.8877        75
weighted avg     0.9062    0.8933    0.8911        75
```

### Confusion Matrix
```
           attacker  exchange  mixer  related  suspect
attacker        2         0      0        1        0
exchange        0        21      0        0        0
   mixer        0         0      3        0        0
 related        0         3      0       31        0
 suspect        0         2      0        2       10
```

**Key observations:**
- `exchange`: Perfect recall (100%), all 21 correctly identified. 3 `related` misclassified as exchange → precision 80.8%
- `attacker`: 1 of 3 leaked to `related` → only 3 test samples, statistically unreliable
- `mixer`: Perfect on 3 test samples — too few to trust
- `suspect`: 4 misclassified (2→exchange, 2→related), recall=71.4%
- No class has F1 < 0.80 — all are at least "GOOD"

### Overfitting Analysis
- **CV F1**: 0.9443 ± 0.0181 (5-fold stratified)
- **Test F1**: 0.8877
- **Gap**: -5.7% — healthy generalization (< 10% threshold)

---

## 4. Feature Importance (Top 15)

| Rank | Feature | Importance |
|------|---------|-----------|
| 1 | counterparty_concentration | 0.1464 |
| 2 | tx_count | 0.0921 |
| 3 | unique_counterparties | 0.0916 |
| 4 | unique_out_counterparties | 0.0906 |
| 5 | out_count | 0.0863 |
| 6 | value_entropy | 0.0781 |
| 7 | unique_in_counterparties | 0.0720 |
| 8 | in_count | 0.0660 |
| 9 | avg_txs_per_day | 0.0557 |
| 10 | activity_span_days | 0.0453 |
| 11 | in_out_ratio | 0.0445 |
| 12 | round_number_ratio | 0.0284 |
| 13 | volume_ratio | 0.0222 |
| 14 | median_tx_value | 0.0177 |
| 15 | min_tx_value | 0.0132 |

**Interpretation:** The model relies heavily on **graph topology features** (counterparty concentration, unique counterparties) over **value features** (median_tx_value, min_tx_value). This makes sense: exchange wallets have many counterparties, while suspect/mixer wallets concentrate flows through few addresses.

---

## 5. Per-Investigation Predictions

| Investigation | Wallets | Accuracy | Distribution |
|--------------|---------|----------|-------------|
| Inv #1 | 7 | 85.7% | related=6, attacker=1 |
| Inv #2 | 48 | 97.9% | exchange=42, related=4, attacker=1, suspect=1 |
| Inv #3 | 96 | 89.6% | suspect=40, exchange=20, mixer=14, related=12, attacker=10 |
| Inv #4 | 2 | 100.0% | attacker=1, related=1 |
| Inv #5 | 59 | 98.3% | related=57, exchange=2 |
| Inv #6 | 29 | 75.9% | exchange=21, suspect=5, related=3 |
| Inv #7 | 75 | 98.7% | related=52, exchange=21, suspect=1, mixer=1 |
| Inv #8 | 58 | 69.0% | related=37, exchange=16, suspect=4, mixer=1 |
| **Overall** | **374** | **89.6%** | |

**Weak investigations:**
- **Inv #6 (75.9%)**: 7 wallets misclassified — exchange/suspect confusion
- **Inv #8 (69.0%)**: 18 wallets misclassified — model struggles with this case's wallet behavior patterns, likely different from training distribution

---

## 6. Critical Assessment

### Strengths
- ExtraTrees generalizes well (5.7% gap) despite SMOTE on tiny classes
- All 5 classes achieve F1 ≥ 0.80 — no complete failure mode
- Feature set is domain-meaningful (graph topology > transaction values)
- Fast training (9s) and inference — suitable for real-time scoring
- 89.6% overall accuracy across all 8 investigations

### Weaknesses
1. **Tiny minority classes**: attacker=16, mixer=17 → only 3 test samples each → confidence intervals are huge. The "perfect" mixer F1=1.000 is statistically meaningless with n=3.
2. **SMOTE before split**: SMOTE is applied to the full training set before cross-validation, which inflates CV scores. Proper methodology requires SMOTE inside each fold (nested resampling).
3. **5/6 models severely overfit (>20% gap)**: The SMOTE-generated synthetic points for minority classes are trivially separable by boosted/bagged tree models. Only ExtraTrees' random split threshold resists this.
4. **No temporal validation**: Random train/test split may leak temporal patterns. A proper evaluation would split by investigation creation date.
5. **Inv #8 accuracy (69%)**: The model struggles with at least one investigation, suggesting distribution shift or novel wallet behavior patterns not seen in training.

### Data Quality Issues (from prior audit)
- Value features had uint256 overflow (max ~1e57) — mitigated with log1p + clip at 99.5th percentile
- Mixed ERC20 token decimals (18 vs 6 vs 8) inflate transaction value features
- 61 wallets filtered out (< 2 transactions) — may miss important cold wallets

---

## 7. Recommendations

### Immediate (next sprint)
1. **Add more labeled wallets** — target 1000+ samples with 100+ per class for reliable minority evaluation
2. **Fix SMOTE-in-CV** — use `imblearn.pipeline.Pipeline` to apply SMOTE inside each CV fold
3. **Merge attacker+mixer → "illicit"** — gives 33 samples as one class instead of 16/17 each
4. **Review Inv #8** — manually inspect the 18 misclassified wallets to understand failure mode

### Medium-term
5. **Feature engineering** — add graph centrality (betweenness, PageRank), clustering coefficient, temporal features
6. **Temporal validation** — split by investigation date (e.g., train on Inv 1-6, test on 7-8)
7. **Calibration** — apply Platt scaling or isotonic regression for probability estimates
8. **Production endpoint** — write wallet_score/classification to DB via API

### Long-term
9. **Active learning** — use model uncertainty to flag wallets needing human review
10. **Ensemble** — combine ExtraTrees with LogisticRegression for diversity
11. **Graph neural networks** — leverage the transaction graph structure directly

---

## 8. Files Produced

| File | Description |
|------|-------------|
| `data/models/champion_ExtraTrees_20260207_213203.pkl` | Pickled model + scaler + encoder |
| `data/models/results_20260207_213203.json` | All 6 model metrics |
| `data/models/predictions_analysis.csv` | 374 wallet predictions with known labels |
| `_host_pipeline.py` | Standalone pipeline script |
| `_analyze_results.py` | Detailed evaluation script |
