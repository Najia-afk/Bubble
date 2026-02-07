# Bubble — AML Investigation Platform

> Blockchain Analytics & Anti-Money Laundering Investigation Platform  
> Built for on-chain investigators, compliance teams, and threat intelligence analysts.

---

## What is Bubble?

Bubble is an end-to-end AML investigation platform that traces, classifies, and scores cryptocurrency wallets across EVM-compatible blockchains. It combines automated on-chain tracing with machine learning classification and heuristic risk scoring to produce actionable intelligence for investigators tracking stolen funds, mixer usage, and exchange cash-out patterns.

## Architecture

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Web** | Flask 3.x + Gunicorn | REST API + GraphQL + Dashboard UI |
| **Workers** | Celery 5.x + Redis 7 | Async investigation tasks, ML training |
| **Database** | PostgreSQL 15 + SQLAlchemy 2.x | Persistent storage, dynamic chain tables |
| **ML** | scikit-learn + MLflow | Model training, versioning, governance |
| **Graph** | vis.js | Interactive fund-flow visualization |
| **Infra** | Docker Compose (6 containers) | web, celery, nginx, postgres, redis, mlflow |

## Codebase Structure (Post-Refactor)

```
api/
├── routes/               # 14 Flask Blueprints (split from 3235-line monolith)
│   ├── health_routes.py      # /api/health
│   ├── case_routes.py        # /api/cases, /run-skill, /skill-status
│   ├── investigation_routes.py # /api/investigations
│   ├── ml_routes.py          # /api/ml/train, /stats, /models
│   ├── classify_routes.py    # /api/classify
│   ├── graph_routes.py       # /api/graph-data
│   ├── label_routes.py       # /api/labels
│   ├── monitor_routes.py     # /api/monitor
│   ├── sync_routes.py        # /api/sync
│   ├── token_routes.py       # /api/tokens
│   ├── audit_routes.py       # /api/audit
│   ├── feature_routes.py     # /api/features
│   ├── notebook_routes.py    # /api/notebooks
│   └── legacy_routes.py      # /api/legacy endpoints
├── application/          # SQLAlchemy models (split from 574-line monolith)
│   ├── base.py               # Shared Base, chain constants
│   ├── label_models.py       # LabelType, WalletLabel, KnownBridge
│   ├── investigation_models.py # Investigation + wallet/token/transfer models
│   ├── ml_models.py          # WalletScore, AuditLog, ModelMetadata
│   ├── token_models.py       # Token, dynamic ERC20 class generators
│   └── erc20models.py        # Backward-compat re-export hub
├── services/
│   ├── investigation_skill.py # 6-step AML investigation pipeline
│   ├── ml_trainer.py         # WalletMLTrainer (RF/GB/XGBoost + MLflow)
│   ├── wallet_classifier.py  # KMeans/DBSCAN + heuristic classification
│   ├── feature_engineer.py   # 50+ feature extraction (6 categories)
│   ├── data_access.py        # 28 data access methods
│   └── ...
├── tasks/                # Celery tasks (split from 994-line monolith)
│   ├── investigation_tasks.py      # Entry point + re-export hub
│   ├── investigation_sync_tasks.py # Transfer syncing + backfill
│   ├── investigation_expand_tasks.py # Fund tracing + expansion
│   ├── investigation_classify_tasks.py # ML + heuristic classification
│   └── investigation_report_tasks.py  # Report generation
config/
├── data/                 # Seed data (cases, chains, bridges, mixers, labels)
doc/
├── README.md             # ← You are here
├── ARCHITECTURE.md       # Detailed architecture docs
├── ML_EVALUATION.md      # Data science model evaluation
├── CASE_SOURCES.md       # Case sourcing methodology
├── END_TO_END_GUIDE.md   # E2E investigation guide
├── aria_skills/          # Skill definitions and configs
reports/
├── cases/                # Per-case investigation reports
├── ml/                   # ML model evaluation reports
notebooks/                # 5 analysis notebooks
```

## Quick Start

```bash
# Clone and start all services
git clone <repo-url> && cd Bubble
docker compose build
docker compose up -d

# Verify health
curl http://localhost:8080/api/health

# Open dashboard
open http://localhost:8080/cases
```

## Key Capabilities

1. **Case Management** — Import cases with seed wallets, track status/severity
2. **AML Investigation Skill** — Automated 6-step pipeline: import → trace → expand → classify → assess → report
3. **On-Chain Tracing** — ERC20 transfer fetching via Etherscan v2 across multiple chains
4. **Fund Flow Expansion** — Iterative counterparty discovery with role determination
5. **ML Classification** — Random Forest production model (98.95% accuracy, 4 classes)
6. **Risk Scoring** — Composite scoring: mixer (+30), bridge (+20), exchange (+10), anomaly (+15)
7. **EU AI Act Compliance** — Full audit trail with SHAP explainability
8. **Interactive Graph** — vis.js visualization with 6-tier node coloring

## Documentation Index

| Document | Description |
|----------|-------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture, data flows, component interactions |
| [ML_EVALUATION.md](ML_EVALUATION.md) | Data scientist evaluation of ML pipeline |
| [CASE_SOURCES.md](CASE_SOURCES.md) | Case sourcing from OSINT investigators |
| [END_TO_END_GUIDE.md](END_TO_END_GUIDE.md) | Running an investigation end-to-end |
| [aria_skills/README.md](aria_skills/README.md) | AML Investigation Skill documentation |
| [../reports/README.md](../reports/README.md) | Investigation and ML reports |

## Current State (2026-02-07)

- **8 active cases** — $34M+ total tracked stolen funds
- **425 wallets** under investigation across 8 investigations
- **640,352 ERC20 transfers** traced
- **3 trained ML models** (RF production, GB staging, XGBoost staging)
- **Production model**: Random Forest — accuracy 98.95%, F1 98.99%, cv 91.00%
