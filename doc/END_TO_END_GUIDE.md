# End-to-End Investigation Guide

## Prerequisites

- Docker Compose running: `docker compose up -d`
- All 6 containers healthy: `docker compose ps`
- At least one case loaded: `curl http://localhost:8080/api/cases`

## E2E Workflow: From Case to Report

### Step 1 — Create or Select a Case

**Option A: Use existing case**
```bash
# List cases
curl http://localhost:8080/api/cases | jq '.cases[].case_id'
```

**Option B: Create new case from OSINT**
```bash
curl -X POST http://localhost:8080/api/cases \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "CASE-2026-009",
    "title": "Test Protocol Exploit",
    "source": "osint",
    "status": "active",
    "severity": "high",
    "attack_vector": "smart_contract_exploit",
    "total_stolen_usd": 250000,
    "summary": "Attacker exploited reentrancy vulnerability...",
    "wallets": [
      {"address": "0x1234...", "chain_code": "ETH", "role": "attacker"}
    ]
  }'
```

### Step 2 — Launch Investigation Skill

```bash
# Launch with default params (depth=3, wallets=100)
curl -X POST http://localhost:8080/api/cases/CASE-2026-008/run-skill \
  -H "Content-Type: application/json" \
  -d '{"max_depth": 2, "max_wallets": 50}'
```

Response (HTTP 202):
```json
{
  "message": "Investigation skill launched",
  "task_id": "abc123...",
  "case_id": "CASE-2026-008"
}
```

### Step 3 — Monitor Progress

**CLI monitoring:**
```bash
# Poll every 5 seconds
while true; do
  curl -s http://localhost:8080/api/cases/CASE-2026-008/skill-status | jq '.status, .current_step'
  sleep 5
done
```

**Dashboard monitoring:**
1. Open http://localhost:8080/cases
2. Click "🔍 Investigate" on the case row
3. Watch the 6-step timeline update in real-time

**Celery logs:**
```bash
docker compose logs celery --tail 20 -f
```

### Step 4 — Review Results

```bash
# Full skill status with findings
curl http://localhost:8080/api/cases/CASE-2026-008/skill-status | jq '.'
```

Expected findings structure:
```json
{
  "status": "completed",
  "findings": {
    "seed_wallets": 1,
    "chains": ["ETH"],
    "transfers_fetched": 15234,
    "wallets_discovered": 38,
    "total_wallets": 40,
    "trace_depth": 2,
    "classification": {"normal": 20, "exchange": 8, "attacker": 5, "suspect": 3, "mixer": 2, "bridge": 2},
    "risk_score": 65,
    "risk_label": "HIGH",
    "exchange_count": 8,
    "mixer_count": 2,
    "bridge_count": 2,
    "flagged_wallets": 7
  }
}
```

### Step 5 — Explore Investigation

```bash
# Get investigation details
curl http://localhost:8080/api/investigations/2 | jq '.'

# Get investigation wallets with classifications
curl http://localhost:8080/api/investigations/2/wallets | jq '.'

# Get investigation transfers
curl http://localhost:8080/api/investigations/2/transfers | jq '.total'
```

### Step 6 — Visualize Graph & Timeline

**Transaction Graph:**
Open in browser: http://localhost:8080/graph?investigation_id=2

The graph shows:
- **Node colors**: Classification-based coloring (attacker=red, exchange=blue, mixer=purple, suspect=orange, related=gray)
- **Node sizes**: Normalized by transfer volume
- **Edges**: Fund flows with amounts and timestamps
- **Physics**: vis.js Barnes-Hut simulation
- **Date filter**: Filter edges by timestamp range

**Timeline View:**
Open in browser: http://localhost:8080/timeline/2

The timeline shows:
- **X-axis**: Real timestamps (first-seen time per wallet)
- **Y-axis**: BFS depth from seed wallets
- **Nodes**: Colored by classification, positioned chronologically
- **Edge tooltips**: First/last transaction dates
- **Layouts**: Timeline (default), Hierarchical, Force-directed

**Investigation Detail (combined view):**
Open in browser: http://localhost:8080/investigations/2

Includes 5 tabs: Summary, Wallets, Graph (iframe), Timeline, Transfers

### Step 7 — ML Model Check

```bash
# Current production model stats
curl http://localhost:8080/api/ml/stats | jq '.'

# All trained models
curl http://localhost:8080/api/ml/models | jq '.models[] | {name, version, accuracy, is_production}'
```

**AutoML Pipeline (for retraining):**
```bash
# Option A: Host execution (recommended)
.venv\Scripts\python -X utf8 notebooks/_host_pipeline.py

# Option B: Docker execution
docker exec bubble_web python notebooks/_host_pipeline.py

# Check results
cat notebooks/data/models/results_*.json | python -m json.tool
```

**Current champion**: ExtraTrees (Test F1=0.8882, 89.6% overall accuracy on 374 wallets)

### Step 8 — Audit Trail

```bash
# Check audit logs for the investigation
curl http://localhost:8080/api/audit?investigation_id=2 | jq '.logs | length'
```

## Validation Checklist

After E2E run, verify:

- [ ] Case created with correct seed wallets
- [ ] Investigation created (linked to case)
- [ ] Transfers synced from blockchain
- [ ] Counterparty wallets discovered
- [ ] ML classification ran on all wallets
- [ ] Risk score computed
- [ ] Report generated
- [ ] Graph visualization works
- [ ] Audit trail populated
- [ ] Celery task completed without crash
- [ ] Redis state shows "completed" status

## Troubleshooting

| Issue | Check | Fix |
|-------|-------|-----|
| Skill stuck on "trace" | `docker compose logs celery` | Check API keys in settings |
| 0 transfers fetched | Etherscan rate limits | Wait or use premium API key |
| ML classification fails | `curl /api/ml/stats` | Retrain if no production model |
| Graph empty | Check investigation has transfers | Run expand with higher depth |
| Redis state stale | `skill:investigation:{id}` TTL | Re-run skill |
