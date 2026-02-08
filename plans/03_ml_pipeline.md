# Plan 03 — ML Pipeline Hardening

> **Agent Role:** ML Agent
> **Priority:** P1 (High)
> **Est. Effort:** 2-3 sessions
> **Dependencies:** None — can start immediately

## Context

The ML pipeline has a production ExtraTrees model (F1=0.8882) trained on 374 samples. However, `WalletClassifier` is disconnected from this model — it uses a separate KMeans approach. Models are saved to `/tmp/` and lost on container restart. MLflow `log_model` returns 404. SHAP computation fails. The `feature_engineer.py` has a placeholder feature. Silent `pass` exception handlers in `ml_trainer.py` swallow errors.

## Objectives

### 1. Wire WalletClassifier to Production Model
- [ ] In `api/services/wallet_classifier.py`, replace standalone KMeans with:
  1. Load production model from `ModelMetadata` table (query `is_production=True`)
  2. Use `feature_engineer.extract_features()` to get features
  3. Run prediction through loaded model
  4. Fall back to heuristic rules only if no production model exists
- [ ] Ensure `classify_investigation_wallets()` (in `investigation_skill.py`) uses this updated classifier
- [ ] Add model caching — don't reload from disk on every classify call

### 2. Fix Model Persistence
- [ ] Change model save path from `/tmp/bubble_models/` to `/app/models/` (inside container)
- [ ] Add `models_data` volume in `docker-compose.yml`:
  ```yaml
  volumes:
    - models_data:/app/models
  ```
- [ ] Update `ml_trainer.py` to save to `/app/models/` (or `MODELS_DIR` env var)
- [ ] Update `wallet_classifier.py` to load from the same path
- [ ] Fix MLflow `log_model` 404 — investigate and fix the MLflow backend store URI
- [ ] Add model version tracking: save with timestamp, keep last 3 versions

### 3. Fix Silent Error Handling
- [ ] In `api/services/ml_trainer.py` lines ~460 and ~776: replace bare `pass` handlers with:
  ```python
  except Exception as e:
      logger.error(f"Training step failed: {e}", exc_info=True)
      raise
  ```
- [ ] Audit all `except Exception: pass` patterns across the ML codebase
- [ ] Add proper error propagation so Celery tasks report failures

### 4. Improve Feature Engineering
- [ ] Implement `new_wallet_interaction_ratio` in `api/services/feature_engineer.py` line ~404
  - Count unique counterparties / total transactions for the wallet
- [ ] Add temporal features (currently missing):
  - `avg_time_between_tx` — mean seconds between consecutive transfers
  - `active_hours_diversity` — Shannon entropy of activity hours (0-23)
  - `weekend_tx_ratio` — fraction of transfers on Saturday/Sunday
- [ ] Add value distribution features:
  - `value_gini_coefficient` — concentration of transfer values
  - `max_single_tx_ratio` — largest transfer / total volume

### 5. Data Augmentation Strategy
- [ ] Current training set: 374 samples (17 attackers, 20 exchanges — dangerously low)
- [ ] Implement SMOTE oversampling for minority classes in `ml_trainer.py`
  - Add `imbalanced-learn` to requirements.txt
  - Apply SMOTE after train-test split but before training
- [ ] Add option to pull labeled wallets from external sources (e.g., Etherscan labels API)
- [ ] Track class distribution in MLflow metrics

### 6. Model Monitoring
- [ ] Implement drift detection using `ModelMetadata.drift_score` field (exists but unused)
- [ ] After each classification batch, compute:
  - Prediction distribution shift (compare to training distribution)
  - Feature mean shift (compare current feature means to training means)
- [ ] Log drift metrics to MLflow
- [ ] Add alert if drift > threshold (store in `WalletMonitorAlert`)

### 7. Fix SHAP Explainability
- [ ] Debug SHAP computation failure in notebook/training pipeline
- [ ] Ensure `shap.TreeExplainer` is used for ExtraTrees (not `KernelExplainer`)
- [ ] Store top-5 SHAP values per prediction in `AuditLog.shap_values`
- [ ] Add SHAP summary plot generation to training pipeline (save as MLflow artifact)

## Constraints

- Do NOT retrain the model in this plan — only fix the plumbing
- Keep the ExtraTrees champion as default; new models must beat F1=0.8882
- All model loading must be lazy (don't load at import time)
- SHAP computation should be opt-in (slow) — add `--shap` flag to training

## Success Criteria

- [ ] `WalletClassifier.classify()` uses the production ExtraTrees model
- [ ] `docker compose restart web` still has access to saved models (volume persistence)
- [ ] No `except: pass` patterns in ML code
- [ ] `new_wallet_interaction_ratio` returns actual values (not 0)
- [ ] MLflow experiment page shows model artifacts
- [ ] Drift score is computed and logged after classification batches
- [ ] SHAP values appear in `AuditLog` entries

## Key Files

| File | Action |
|------|--------|
| `api/services/wallet_classifier.py` | Major rewrite — wire to production model |
| `api/services/ml_trainer.py` | Fix — error handling, save path, SMOTE |
| `api/services/feature_engineer.py` | Fix — implement placeholder + new features |
| `api/services/investigation_skill.py` | Verify — classifier integration |
| `api/application/ml_models.py` | Check — ModelMetadata.drift_score usage |
| `docker-compose.yml` | Modify — add models_data volume |
| `config/settings.py` | Add — MODELS_DIR config |
| `config/requirements.txt` | Add — imbalanced-learn, shap |
