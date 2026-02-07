# Bubble — System Architecture

## Container Topology

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Compose                        │
│                                                         │
│  ┌──────────┐    ┌───────────┐    ┌───────────────┐    │
│  │  nginx   │───▶│    web    │───▶│  PostgreSQL   │    │
│  │  :8080   │    │ Flask/Gun │    │    :5432      │    │
│  └──────────┘    │  icorn    │    └───────────────┘    │
│                  │  :5000    │            ▲             │
│                  └─────┬─────┘            │             │
│                        │                 │             │
│                        ▼                 │             │
│                  ┌───────────┐    ┌──────┴──────┐     │
│                  │   Redis   │◀──▶│   Celery    │     │
│                  │   :6379   │    │  (workers)  │     │
│                  └───────────┘    └─────────────┘     │
│                                         │              │
│                                         ▼              │
│                                  ┌─────────────┐      │
│                                  │   MLflow    │      │
│                                  │   :5005     │      │
│                                  └─────────────┘      │
└─────────────────────────────────────────────────────────┘
```

## Request Flow

### Dashboard Request
```
Browser → nginx:8080 → Flask:5000 → Jinja2 template → HTML response
                                  → SQLAlchemy ORM → PostgreSQL
```

### API Request
```
Client → nginx:8080 → Flask Blueprint → Service Layer → SQLAlchemy → PostgreSQL
                                                      → Redis (cache/state)
```

### Investigation Skill Execution
```
POST /api/cases/{id}/run-skill
  → Flask route (case_routes.py)
    → Save initial state to Redis
    → Dispatch Celery task (run_investigation_skill_task)
    → Return 202 + task_id

Celery worker picks up task:
  → InvestigationSkillRunner.run(case_id, max_depth, max_wallets)
    → Step 1: _step_import()      — CaseWallet → InvestigationWallet
    → Step 2: _step_trace()       — Etherscan v2 → sync_investigation_transfers()
    → Step 3: _step_expand()      — Loop: expand → sync → check limits
    → Step 4: _step_classify()    — classify_investigation_wallets()
    → Step 5: _step_assess()      — Risk scoring algorithm
    → Step 6: _step_report()      — generate_investigation_report()
  → Each step updates Redis state with progress
  → Frontend polls GET /api/cases/{id}/skill-status every 3s

GET /api/cases/{id}/skill-status
  → Read Redis key skill:investigation:{case_id}
  → Return step statuses + findings + investigation_id
```

## Data Model

### Core Entities
```
Case (case_id, title, source, status, severity, ...)
  └── CaseWallet (address, chain_code, role, label)
  └── Investigation (1:1 via import)
        ├── InvestigationWallet (address, chain_id, role, depth)
        ├── InvestigationToken (contract_address, symbol, decimals)
        └── InvestigationTransfer (from, to, value, block, timestamp)
```

### ML Entities
```
WalletScore (address, chain_id, predicted_type, confidence, scores[6], features[5])
ModelMetadata (model_name, version, accuracy, f1, production, mlflow_run_id, ...)
AuditLog (action, wallet, prediction, confidence, shap_values, ...)
```

### Dynamic Chain Tables
Each supported chain generates:
- `erc20_transfers_{trigram}` — ERC20 transfer events
- `block_transfer_events_{trigram}` — Block-level events

Generated at startup via `generate_erc20_classes()` and `generate_block_transfer_event_classes()`.

## Blueprint Architecture (14 Domains)

| Blueprint | Prefix | Routes | Domain |
|-----------|--------|--------|--------|
| `health` | `/api` | 1 | Health check |
| `cases` | `/api` | 9 | Case CRUD + skill launch |
| `investigations` | `/api` | 14 | Investigation management |
| `ml` | `/api` | 8 | ML training, models, stats |
| `classify` | `/api` | 4 | Wallet classification |
| `labels` | `/api` | 12+ | Label/tag management |
| `sync` | `/api` | 4 | Transfer sync operations |
| `tokens` | `/api` | 4 | Token management |
| `graph` | `/api` | 2 | Graph data for vis.js |
| `monitor` | `/api` | 8 | Wallet monitoring + alerts |
| `audit` | `/api` | 4 | Audit trail (EU AI Act) |
| `features` | `/api` | 2 | Feature extraction |
| `notebooks` | `/api` | 5 | Notebook management |
| `legacy` | `/api` | 4 | Legacy/migration endpoints |

## ML Pipeline

```
Feature Engineering (50+ features, 6 categories)
  → transaction, value, temporal, network, risk, behavioral

Training Pipeline:
  prepare_training_data() → extract_features() → train_model()
    → Cross-validation (StratifiedKFold, k=5)
    → MLflow logging (params, metrics, artifacts)
    → SHAP importance computation
    → Model persistence (MLflow model registry)

Classification Pipeline:
  classify(address, chain_code)
    → feature_engineer.extract_features(address)
    → ML model prediction (production model)
    → Heuristic fallback (if ML unavailable)
    → Known entity matching (exchange/mixer/bridge lists)
    → WalletScore persistence + AuditLog entry

Production Model: Random Forest
  → 381 samples × 10 features × 4 classes
  → Accuracy: 98.95%, F1: 98.99%, CV: 91.00%
  → Hyperparameters: {n_estimators, max_depth, min_samples_split, ...}
```

## Risk Scoring Algorithm

```python
base_score = 0
if mixer_interactions > 0:    base_score += 30  # Mixer usage is highest risk
if bridge_crossings > 0:      base_score += 20  # Cross-chain movement
if exchange_endpoints > 0:    base_score += 10  # Cash-out detection
if anomaly_detected:          base_score += 15  # Statistical anomaly

# Normalize to 0-100 scale
risk_score = min(100, base_score + contextual_adjustments)

# Labels
CRITICAL ≥ 70  |  HIGH ≥ 50  |  MEDIUM ≥ 25  |  LOW < 25
```
## Autonomous Pipeline Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                    AUTONOMOUS INVESTIGATION LOOP                      │
│                                                                      │
│  ┌─────────────┐    ┌──────────────┐    ┌────────────────────────┐  │
│  │ OSINT Feed  │───▶│ Case Scanner │───▶│ Investigation Pipeline │  │
│  │ (ZachXBT,   │    │ reports/     │    │ 6-step skill:          │  │
│  │  rekt.news, │    │ cases/*.md   │    │  import → trace →      │  │
│  │  PeckShield)│    │              │    │  expand → classify →   │  │
│  └─────────────┘    └──────────────┘    │  assess → report      │  │
│                                         └───────────┬────────────┘  │
│                                                     │               │
│  ┌─────────────┐    ┌──────────────┐    ┌──────────▼────────────┐  │
│  │ LLM Report  │◀───│   Report     │◀───│  AutoML Engine        │  │
│  │ Enrichment  │    │  Generator   │    │  7 models × Optuna    │  │
│  │ (Aria)      │    │  Markdown    │    │  → Champion promotion │  │
│  └─────────────┘    └──────────────┘    └───────────────────────┘  │
│                                                                      │
│  State: logs/autonomous_state.json                                   │
│  Logs:  logs/autonomous_loop.log                                     │
│  Cycle: 1 hour (configurable)                                        │
└──────────────────────────────────────────────────────────────────────┘
```

### AutoML Model Selection

| Model | Type | Default | Optuna Tuned |
|-------|------|---------|--------------|
| RandomForest | Ensemble | ✅ | n_estimators, max_depth, min_samples |
| GradientBoosting | Ensemble | ✅ | n_estimators, learning_rate, subsample |
| ExtraTrees | Ensemble | ✅ | n_estimators, max_depth |
| LogisticRegression | Linear | ✅ | C, penalty, solver |
| SVM | Kernel | ✅ | C, kernel, gamma |
| XGBoost | Gradient | Optional | + reg_alpha, reg_lambda, colsample |
| LightGBM | Gradient | Optional | + num_leaves, reg_alpha, reg_lambda |

### Scripts

| Script | Purpose |
|--------|---------|
| `scripts/autonomous_loop.py` | Continuous daemon: scan → investigate → train → report |
| `scripts/autonomous_runner.py` | One-shot pipeline for specific cases |
| `scripts/report_generator.py` | Structured markdown reports for LLM consumption |
| `notebooks/05_auto_ml.ipynb` | Interactive AutoML with visualizations |

### Notebooks

| Notebook | Purpose |
|----------|---------|
| `01_wallet_tagging.ipynb` | Feature engineering + model training |
| `02_victim_classification.ipynb` | Incoming sender classification |
| `03_path_analysis.ipynb` | Fund flow graph analysis |
| `04_aml_monitoring.ipynb` | Alert rules engine + dashboard |
| `05_auto_ml.ipynb` | **AutoML**: 7 models, Optuna, SHAP, auto-promote |