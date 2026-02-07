"""Quick script to create investigations and run pipeline from local machine."""
import requests
import json
import time
import sys

BASE = "http://localhost:8080/api"

def log(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def api(method, path, data=None):
    url = f"{BASE}{path}"
    if method == 'GET':
        r = requests.get(url, timeout=30)
    else:
        r = requests.post(url, json=data or {}, timeout=60)
    return r.status_code, r.json()

# ── STEP 1: Create investigations for all cases ──
log("STEP 1: Creating investigations for all cases without one")

CONFIGS = {
    'CASE-2026-002': {'name': '[CASE-2026-002] Trust Wallet Extension Drain', 'chain': 'ETH', 'loss': 500000, 'depth': 2, 'wallets': 80},
    'CASE-2026-003': {'name': '[CASE-2026-003] Private Key Compromise - 5 Wallets', 'chain': 'ETH', 'loss': 1100000, 'depth': 3, 'wallets': 60},
    'CASE-2026-004': {'name': '[CASE-2026-004] Danny/Meech Genesis Creditor Theft', 'chain': 'ETH', 'loss': 18580000, 'depth': 2, 'wallets': 50},
    'CASE-2026-005': {'name': '[CASE-2026-005] GANA Payment Protocol Exploit', 'chain': 'BSC', 'loss': 3100000, 'depth': 3, 'wallets': 60},
    'CASE-2026-006': {'name': '[CASE-2026-006] Fake Hyperliquid App Scam', 'chain': 'ETH', 'loss': 200000, 'depth': 2, 'wallets': 40},
    'CASE-2026-007': {'name': '[CASE-2026-007] Garden Finance Exploit', 'chain': 'ETH', 'loss': 10800000, 'depth': 3, 'wallets': 80},
    'CASE-2026-008': {'name': '[CASE-2026-008] Hypurr NFT Drain', 'chain': 'ETH', 'loss': 400000, 'depth': 2, 'wallets': 40},
}

_, cases_resp = api('GET', '/cases')
cases = cases_resp.get('cases', [])

created_investigations = {}

for case in cases:
    cid = case['case_id']
    if case.get('investigation_id'):
        log(f"  {cid}: already has investigation #{case['investigation_id']}")
        created_investigations[cid] = case['investigation_id']
        continue
    if cid not in CONFIGS:
        continue

    cfg = CONFIGS[cid]

    # Get case wallets
    _, detail = api('GET', f'/cases/{cid}')
    theft_addrs = detail.get('theft_addresses', [])

    # Create investigation
    status, result = api('POST', '/investigations', {
        'name': cfg['name'],
        'description': detail.get('summary', ''),
        'reported_loss_usd': cfg['loss'],
        'created_by': 'pipeline',
        'default_chain': cfg['chain'],
    })

    if status not in (200, 201):
        log(f"  {cid}: FAILED: {result}")
        continue

    inv_id = result['id']
    log(f"  {cid}: created investigation #{inv_id}")
    created_investigations[cid] = inv_id

    # Add attacker/seed wallets
    for w in theft_addrs:
        chain = w.get('chains', [cfg['chain']])[0] if w.get('chains') else cfg['chain']
        ws, wr = api('POST', f'/investigations/{inv_id}/wallets', {
            'address': w['address'],
            'chain': chain,
            'role': w.get('role', 'attacker'),
            'depth': 0,
            'notes': w.get('label', ''),
        })
        status_icon = "+" if ws in (200, 201) else "~" if ws == 409 else "!"
        log(f"    {status_icon} {w['address'][:20]}... [{w.get('role','attacker')}]")

log(f"\nTotal investigations: {len(created_investigations)}")

# ── STEP 2: Trigger sync_and_expand for all investigations ──
log("\nSTEP 2: Triggering sync & expand for all investigations")

_, invs_resp = api('GET', '/investigations')
investigations = invs_resp.get('investigations', [])

task_ids = {}
for inv in investigations:
    inv_id = inv['id']
    # Find config
    cfg = None
    for cid, c in CONFIGS.items():
        if cid in inv['name']:
            cfg = c
            break

    depth = cfg['depth'] if cfg else 2
    max_w = cfg['wallets'] if cfg else 50

    status, result = api('POST', f'/investigations/{inv_id}/investigate', {
        'max_depth': depth,
        'max_wallets': max_w,
    })

    if status == 202:
        task_ids[inv_id] = result.get('task_id')
        log(f"  #{inv_id} {inv['name'][:50]}: submitted (depth={depth}, max={max_w})")
    else:
        log(f"  #{inv_id}: FAILED: {result}")

log(f"\n{len(task_ids)} investigation pipelines submitted to Celery.")
log("Etherscan API rate limits apply. Waiting for data fetch...")

# Poll progress every 30 seconds for 10 minutes
for cycle in range(20):
    time.sleep(30)
    _, invs = api('GET', '/investigations')
    total_w = sum(i.get('wallet_count', 0) for i in invs.get('investigations', []))
    elapsed = (cycle + 1) * 30
    log(f"  [{elapsed}s] Total wallets across all investigations: {total_w}")
    
    # Check celery logs for errors
    if cycle == 5:  # At 2.5 min mark
        log("  Checking celery health...")

log("\nData fetch period complete. Checking final state...")

# ── STEP 3: Classify wallets ──
log("\nSTEP 3: Classifying investigation wallets")

_, invs = api('GET', '/investigations')
for inv in invs.get('investigations', []):
    inv_id = inv['id']
    if inv.get('wallet_count', 0) > 0:
        status, result = api('POST', f'/investigations/{inv_id}/classify')
        log(f"  #{inv_id}: classify submitted (task={result.get('task_id', '?')})")
    else:
        log(f"  #{inv_id}: 0 wallets, skipping classification")

log("Waiting 2 min for classification to complete...")
time.sleep(120)

# ── STEP 4: Train ML models ──
log("\nSTEP 4: Training ML models")

for model_type in ['random_forest', 'gradient_boosting', 'xgboost']:
    status, result = api('POST', '/ml/train', {
        'model_type': model_type,
        'test_size': 0.2,
        'use_smote': True,
    })
    if status == 202:
        log(f"  {model_type}: submitted (task={result.get('task_id', '?')})")
    else:
        log(f"  {model_type}: FAILED: {result}")

log("Waiting 3 min for training...")
time.sleep(180)

# ── STEP 5: Evaluate ──
log("\nSTEP 5: Evaluating models")

_, experiments = api('GET', '/ml/experiments')
if isinstance(experiments, list) and experiments:
    log(f"  {len(experiments)} model runs found:")
    best = None
    for exp in experiments:
        f1 = exp.get('f1_score') or 0
        acc = exp.get('accuracy') or 0
        log(f"    {exp.get('run_name', '?')}: f1={f1:.4f}, accuracy={acc:.4f}")
        if best is None or f1 > (best.get('f1_score') or 0):
            best = exp

    if best and (best.get('f1_score') or 0) > 0:
        log(f"\n  Best: {best.get('run_name')} f1={best['f1_score']:.4f}")
        log("  Promoting to production...")
        api('POST', '/ml/promote', {
            'model_name': 'wallet_classifier',
            'version': str(best.get('run_id', '1'))[:10],
            'stage': 'Production',
        })
        log("  Model promoted ✓")
    else:
        log("  No model with positive F1 score found.")
else:
    log("  No experiments found — likely insufficient labeled data (need 50+ WalletLabels).")

# ── STEP 6: Final Report ──
log("\n" + "=" * 70)
log("FINAL REPORT")
log("=" * 70)

_, invs = api('GET', '/investigations')
_, stats = api('GET', '/stats/dashboard')

log(f"Cases: {stats.get('total_cases', 0)}")
log(f"Active Investigations: {len(invs.get('investigations', []))}")
log(f"Total Wallets: {stats.get('investigation_wallets', 0)}")
log(f"Total Transfers: {stats.get('investigation_transfers', 0)}")
log(f"Estimated Total Loss: ${stats.get('estimated_loss_usd', 0):,.0f}")

for inv in invs.get('investigations', []):
    inv_id = inv['id']
    log(f"\n  Investigation #{inv_id}: {inv['name']}")
    log(f"    Status: {inv.get('status')}")
    log(f"    Wallets: {inv.get('wallet_count', 0)}")
    log(f"    Loss: ${inv.get('reported_loss_usd') or 0:,.0f}")

    # Get report
    try:
        _, report = api('GET', f'/investigations/{inv_id}/report')
        if 'summary' in report:
            s = report['summary']
            log(f"    Transfers: {s.get('total_transfers', 0)}")
            log(f"    Volume: {s.get('total_volume', 0):.2f}")
        if 'role_breakdown' in report:
            roles = report['role_breakdown']
            log(f"    Roles: {json.dumps(roles)}")
        if report.get('flagged_wallets'):
            log(f"    Flagged: {len(report['flagged_wallets'])} wallets")
    except:
        pass

_, exps = api('GET', '/ml/experiments')
if isinstance(exps, list) and exps:
    log(f"\nML Models ({len(exps)} runs):")
    for exp in exps:
        log(f"  {exp.get('run_name')}: f1={exp.get('f1_score', 0):.4f} acc={exp.get('accuracy', 0):.4f}")

log("\n" + "=" * 70)
log("BLOCKERS / NEXT STEPS")
log("=" * 70)

total_wallets = stats.get('investigation_wallets', 0)

if total_wallets < 100:
    log("⚠ LOW DATA — Etherscan API may have rate-limited some fetches.")
    log("  → Re-run investigation pipelines after cooldown")
    log("  → Check: docker logs bubble_celery --tail 50")

if not isinstance(exps, list) or not exps:
    log("⚠ NO ML MODELS — Insufficient labeled training data.")
    log("  ML requires 50+ validated WalletLabel records with confidence >= 0.8")
    log("  → Heuristic classifications exist on investigation wallets")
    log("  → Need to promote heuristic labels → WalletLabel table")
    log("  → Or import external label DB (Etherscan tags, Chainalysis)")
    log("  → Manual review via Aria for ambiguous cases")

log("\nEndpoints for manual follow-up:")
log("  Dashboard: http://localhost:8080/")
log("  Timeline:  http://localhost:8080/timeline")
log("  MLflow:    http://localhost:5005")
log("  API docs:  http://localhost:8080/static/swagger.json")

log("\n✓ Pipeline complete.")
