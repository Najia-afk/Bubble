# Aria Skills — AML Investigation Platform

## Overview

Aria Skills are automated, composable investigation pipelines that orchestrate blockchain analytics workflows. Each skill is defined as a JSON configuration with typed inputs, ordered steps, state management, and structured outputs.

## Skills Registry

| Skill | Category | Trigger | Description |
|-------|----------|---------|-------------|
| [investigation_skill.json](investigation_skill.json) | investigation | `POST /api/cases/{id}/run-skill` | Full 6-step AML investigation pipeline |
| [ml_classification_skill.json](ml_classification_skill.json) | ml | `POST /api/classify` | ML + heuristic wallet classification |
| [risk_scoring_skill.json](risk_scoring_skill.json) | risk | Internal (step 5 of investigation) | Composite risk scoring algorithm |

## Investigation Skill Pipeline

The primary skill — `aml_investigation` — orchestrates the complete investigation lifecycle:

```
┌────────────┐    ┌────────────┐    ┌────────────┐
│  1. IMPORT │───▶│  2. TRACE  │───▶│ 3. EXPAND  │
│  📥 Case   │    │  🔗 Fetch  │    │ 🕵️ Follow  │
│  → Invest. │    │  transfers │    │  the money │
└────────────┘    └────────────┘    └─────┬──────┘
                                          │
                                          ▼
┌────────────┐    ┌────────────┐    ┌────────────┐
│ 6. REPORT  │◀───│  5. ASSESS │◀───│4. CLASSIFY │
│  📊 Final  │    │  ⚠️ Risk   │    │ 🤖 ML +    │
│  findings  │    │  scoring   │    │ heuristics │
└────────────┘    └────────────┘    └────────────┘
```

### Step Details

#### Step 1: Import Case (`_step_import`)
- **Source**: `api/services/investigation_skill.py`
- **Action**: Creates `Investigation` record from `Case` seed wallets
- **Maps**: `CaseWallet` → `InvestigationWallet` with role normalization
- **Resolves**: chain_code → chain_id via `CHAIN_CODE_TO_ID` mapping

#### Step 2: Trace Transfers (`_step_trace`)
- **Source**: `api/tasks/investigation_sync_tasks.py`
- **Action**: Fetches ERC20 transfer history from Etherscan v2 API
- **Scope**: All seed wallets across their respective chains
- **Storage**: Dynamic `erc20_transfers_{chain}` tables

#### Step 3: Follow the Money (`_step_expand`)
- **Source**: `api/tasks/investigation_expand_tasks.py`
- **Action**: Iterative counterparty discovery
- **Loop**: Up to `max_depth` iterations of expand → sync → check
- **Termination**: 0 new wallets found OR `max_wallets` limit reached
- **Role Assignment**: `_determine_role()` classifies discovered wallets

#### Step 4: ML Classification (`_step_classify`)
- **Source**: `api/tasks/investigation_classify_tasks.py`
- **Action**: Classify all investigation wallets using 3-tier system:
  1. Production ML model (Random Forest)
  2. Heuristic rules (transaction pattern matching)
  3. Known entity matching (exchange/mixer/bridge databases)

#### Step 5: Risk Assessment (`_step_assess`)
- **Source**: `api/services/investigation_skill.py`
- **Action**: Compute composite risk score for the investigation
- **Scoring**: mixer (+30), bridge (+20), exchange (+10), anomaly (+15)
- **Labels**: CRITICAL ≥70, HIGH ≥50, MEDIUM ≥25, LOW <25

#### Step 6: Generate Report (`_step_report`)
- **Source**: `api/tasks/investigation_report_tasks.py`
- **Action**: Compile structured report with all findings
- **Output**: Risk assessment, classification breakdown, wallet inventory

### State Management

Investigation progress is tracked in Redis with key `skill:investigation:{case_id}` (TTL 24h):

```json
{
  "status": "running",
  "case_id": "CASE-2026-001",
  "investigation_id": 1,
  "started_at": "2026-02-07T18:00:00Z",
  "current_step": "expand",
  "steps": {
    "import": {"status": "completed", "elapsed_seconds": 1.2, "result": {"message": "..."}},
    "trace": {"status": "completed", "elapsed_seconds": 45.7, "result": {"message": "..."}},
    "expand": {"status": "running", "started_at": "2026-02-07T18:01:00Z"},
    "classify": {"status": "pending"},
    "assess": {"status": "pending"},
    "report": {"status": "pending"}
  },
  "findings": null
}
```

### Failure Mode

All steps use `failure_mode: continue` — if a step fails, the error is logged and the pipeline proceeds to the next step. This ensures partial results are always available even if one component has issues.

### Frontend Integration

The Cases page (`templates/cases.html` + `static/js/cases.js`) includes:
- Slide-out skill panel with max_depth and max_wallets controls
- Vertical step timeline with real-time status indicators
- Findings display with risk meter and classification grid
- Post-completion link to graph visualization

### API Examples

**Launch Investigation:**
```bash
curl -X POST http://localhost:8080/api/cases/CASE-2026-001/run-skill \
  -H "Content-Type: application/json" \
  -d '{"max_depth": 3, "max_wallets": 100}'
```

**Poll Status:**
```bash
curl http://localhost:8080/api/cases/CASE-2026-001/skill-status
```

## Creating New Skills

To add a new Aria Skill:

1. **Define the skill JSON** in `doc/aria_skills/` with inputs, steps, and outputs
2. **Implement the runner** in `api/services/` as a class with `run()` method
3. **Create Celery task** wrapper in `api/tasks/`
4. **Add API route** in the appropriate blueprint under `api/routes/`
5. **Add state management** via Redis for progress tracking
6. **Add frontend controls** if user-facing
