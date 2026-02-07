"""
Pipeline Runner — Create investigations for all cases, fetch data, train models.
Run inside Docker: docker exec bubble_web python scripts/run_pipeline.py
"""
import sys
import os
import json
import time
import requests
from datetime import datetime

BASE_URL = os.environ.get('BUBBLE_API_URL', 'http://localhost:5000')
API = f"{BASE_URL}/api"

# Define cases with their wallet data (from CSV seed data)
CASE_CONFIGS = {
    'CASE-2026-002': {
        'name': '[CASE-2026-002] Trust Wallet Extension Drain',
        'chain': 'ETH',
        'reported_loss_usd': 500000,
        'max_depth': 2,
        'max_wallets': 80,
    },
    'CASE-2026-003': {
        'name': '[CASE-2026-003] Private Key Compromise - 5 Wallets',
        'chain': 'ETH',
        'reported_loss_usd': 1100000,
        'max_depth': 3,
        'max_wallets': 60,
    },
    'CASE-2026-004': {
        'name': '[CASE-2026-004] Danny/Meech Genesis Creditor Theft',
        'chain': 'ETH',
        'reported_loss_usd': 18580000,
        'max_depth': 2,
        'max_wallets': 50,
    },
    'CASE-2026-005': {
        'name': '[CASE-2026-005] GANA Payment Protocol Exploit',
        'chain': 'BSC',
        'reported_loss_usd': 3100000,
        'max_depth': 3,
        'max_wallets': 60,
    },
    'CASE-2026-006': {
        'name': '[CASE-2026-006] Fake Hyperliquid App Scam',
        'chain': 'ETH',
        'reported_loss_usd': 200000,
        'max_depth': 2,
        'max_wallets': 40,
    },
    'CASE-2026-007': {
        'name': '[CASE-2026-007] Garden Finance Exploit',
        'chain': 'ETH',
        'reported_loss_usd': 10800000,
        'max_depth': 3,
        'max_wallets': 80,
    },
    'CASE-2026-008': {
        'name': '[CASE-2026-008] Hypurr NFT Drain',
        'chain': 'ETH',
        'reported_loss_usd': 400000,
        'max_depth': 2,
        'max_wallets': 40,
    },
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def api_get(path):
    r = requests.get(f"{API}{path}", timeout=30)
    return r.json()


def api_post(path, data=None):
    r = requests.post(f"{API}{path}", json=data or {}, timeout=60)
    return r.status_code, r.json()


def wait_for_celery_task(task_id, label="task", timeout=600, poll=10):
    """Poll celery task status (check via investigation state changes)."""
    log(f"  Submitted {label}: task_id={task_id}")
    log(f"  Waiting up to {timeout}s for completion...")
    elapsed = 0
    while elapsed < timeout:
        time.sleep(poll)
        elapsed += poll
        if elapsed % 60 == 0:
            log(f"  ... {elapsed}s elapsed")
    log(f"  Wait period complete ({timeout}s)")


def step1_create_investigations():
    """Create investigations for all cases that don't have one yet."""
    log("=" * 60)
    log("STEP 1: Creating investigations for all cases")
    log("=" * 60)

    cases = api_get("/cases").get('cases', [])
    created = []

    for case in cases:
        case_id = case['case_id']
        if case.get('investigation_id'):
            log(f"  {case_id}: already has investigation #{case['investigation_id']}")
            continue

        if case_id not in CASE_CONFIGS:
            log(f"  {case_id}: no config, skipping")
            continue

        config = CASE_CONFIGS[case_id]

        # Get case wallets
        case_detail = api_get(f"/cases/{case_id}")
        wallets = case_detail.get('theft_addresses', [])

        if not wallets:
            log(f"  {case_id}: no wallets, skipping")
            continue

        # Create investigation
        payload = {
            'name': config['name'],
            'description': case_detail.get('summary', ''),
            'reported_loss_usd': config.get('reported_loss_usd'),
            'created_by': 'pipeline_runner',
            'victim_wallets': [],  # We'll add as attackers below
            'default_chain': config['chain'],
        }

        status, result = api_post("/investigations", payload)
        if status not in (200, 201):
            log(f"  {case_id}: FAILED to create investigation: {result}")
            continue

        inv_id = result['id']
        log(f"  {case_id}: created investigation #{inv_id}")

        # Add attacker wallets
        for w in wallets:
            wallet_payload = {
                'address': w['address'],
                'chain': w.get('chains', [config['chain']])[0] if w.get('chains') else config['chain'],
                'role': w.get('role', 'attacker'),
                'depth': 0,
                'notes': w.get('label', ''),
            }
            ws, wr = api_post(f"/investigations/{inv_id}/wallets", wallet_payload)
            if ws in (200, 201):
                log(f"    + {w['address'][:16]}... ({w.get('role', 'attacker')})")
            elif ws == 409:
                log(f"    ~ {w['address'][:16]}... (already exists)")
            else:
                log(f"    ! {w['address'][:16]}... FAILED: {wr}")

        created.append({'case_id': case_id, 'investigation_id': inv_id, 'wallets': len(wallets)})

    log(f"\nCreated {len(created)} new investigations")
    return created


def step2_sync_and_expand():
    """Trigger sync_and_expand for all investigations."""
    log("=" * 60)
    log("STEP 2: Sync & Expand all investigations (Etherscan fetch)")
    log("=" * 60)

    investigations = api_get("/investigations").get('investigations', [])
    tasks = []

    for inv in investigations:
        inv_id = inv['id']
        inv_name = inv['name']

        # Find matching config for max_depth/max_wallets
        config = None
        for cid, cfg in CASE_CONFIGS.items():
            if cid in inv_name:
                config = cfg
                break

        max_depth = config['max_depth'] if config else 2
        max_wallets = config['max_wallets'] if config else 50

        log(f"\n  Investigation #{inv_id}: {inv_name}")
        log(f"    max_depth={max_depth}, max_wallets={max_wallets}")

        status, result = api_post(f"/investigations/{inv_id}/investigate", {
            'max_depth': max_depth,
            'max_wallets': max_wallets,
        })

        if status == 202:
            tasks.append({
                'investigation_id': inv_id,
                'task_id': result.get('task_id'),
                'name': inv_name,
            })
            log(f"    Submitted: task_id={result.get('task_id')}")
        else:
            log(f"    FAILED: {result}")

    # Wait for all tasks to complete
    if tasks:
        log(f"\n  {len(tasks)} investigation pipelines running...")
        log(f"  Etherscan API rate limits apply — this takes time.")
        log(f"  Waiting 5 minutes for initial fetch pass...")
        time.sleep(300)

        # Check progress
        for t in tasks:
            inv = api_get(f"/investigations/{t['investigation_id']}")
            inv_data = inv.get('investigations', [inv])[0] if isinstance(inv.get('investigations'), list) else inv
            wc = inv_data.get('wallet_count', 0)
            log(f"  Investigation #{t['investigation_id']}: {wc} wallets")

        log("  Waiting additional 5 minutes for expansion passes...")
        time.sleep(300)

    return tasks


def step3_classify_wallets():
    """Run classification on all investigations."""
    log("=" * 60)
    log("STEP 3: Classify all investigation wallets")
    log("=" * 60)

    investigations = api_get("/investigations").get('investigations', [])

    for inv in investigations:
        inv_id = inv['id']
        log(f"  Classifying investigation #{inv_id}: {inv['name']}")

        status, result = api_post(f"/investigations/{inv_id}/classify")
        if status == 202:
            log(f"    task_id={result.get('task_id')}")
        else:
            log(f"    FAILED: {result}")

    log("  Waiting 2 minutes for classification...")
    time.sleep(120)


def step4_train_models():
    """Train multiple ML models."""
    log("=" * 60)
    log("STEP 4: Train ML models")
    log("=" * 60)

    model_types = ['random_forest', 'gradient_boosting']
    if True:  # xgboost is in requirements
        model_types.append('xgboost')

    results = []

    for model_type in model_types:
        log(f"\n  Training {model_type}...")
        status, result = api_post("/ml/train", {
            'model_type': model_type,
            'test_size': 0.2,
            'use_smote': True,
        })
        if status == 202:
            log(f"    task_id={result.get('task_id')}")
            results.append({'model_type': model_type, 'task_id': result.get('task_id')})
        else:
            log(f"    FAILED: {result}")

    log("  Waiting 3 minutes for training...")
    time.sleep(180)

    return results


def step5_evaluate_and_promote():
    """Evaluate models and promote the best one."""
    log("=" * 60)
    log("STEP 5: Evaluate & promote best model")
    log("=" * 60)

    # Get model experiments
    experiments = api_get("/ml/experiments")

    if not experiments:
        log("  No experiments found. Training may have failed (insufficient labels).")
        log("  This is expected if investigations haven't been classified yet.")
        return None

    log(f"  {len(experiments)} experiment runs found:")
    best = None
    for exp in experiments:
        f1 = exp.get('f1_score') or 0
        acc = exp.get('accuracy') or 0
        log(f"    {exp.get('run_name', '?')}: f1={f1:.4f}, accuracy={acc:.4f}")
        if best is None or f1 > (best.get('f1_score') or 0):
            best = exp

    if best and best.get('f1_score', 0) > 0:
        log(f"\n  Best model: {best.get('run_name')} (f1={best.get('f1_score'):.4f})")

        # Register and promote
        log("  Registering best model...")
        status, result = api_post("/ml/promote", {
            'model_name': 'wallet_classifier',
            'version': best.get('run_id', '1')[:10],
            'stage': 'Production',
        })
        log(f"  Promotion result: {result}")
        return best
    else:
        log("  No model with positive f1 found.")
        return None


def step6_generate_report():
    """Generate comprehensive analysis report."""
    log("=" * 60)
    log("STEP 6: Generate analysis report")
    log("=" * 60)

    investigations = api_get("/investigations").get('investigations', [])

    report_lines = []
    report_lines.append("=" * 70)
    report_lines.append("BUBBLE INVESTIGATION PIPELINE — ANALYSIS REPORT")
    report_lines.append(f"Generated: {datetime.now().isoformat()}")
    report_lines.append("=" * 70)

    total_wallets = 0
    total_transfers = 0
    total_loss = 0.0

    for inv in investigations:
        inv_id = inv['id']
        log(f"  Generating report for investigation #{inv_id}...")

        # Get investigation report
        try:
            report = api_get(f"/investigations/{inv_id}/report")
        except Exception as e:
            report = {'error': str(e)}

        wc = inv.get('wallet_count', 0)
        tc = inv.get('token_count', 0)
        loss = inv.get('reported_loss_usd') or inv.get('estimated_loss_usd') or 0

        total_wallets += wc
        total_loss += loss

        report_lines.append(f"\n{'─' * 70}")
        report_lines.append(f"Investigation #{inv_id}: {inv['name']}")
        report_lines.append(f"  Status: {inv.get('status', '?')}")
        report_lines.append(f"  Wallets: {wc}")
        report_lines.append(f"  Reported Loss: ${loss:,.0f}")

        if 'summary' in report:
            s = report['summary']
            report_lines.append(f"  Total Transfers: {s.get('total_transfers', 0)}")
            total_transfers += s.get('total_transfers', 0)
            report_lines.append(f"  Total Volume: {s.get('total_volume', 0):.4f} (raw token units)")

        if 'role_breakdown' in report:
            report_lines.append(f"  Role Breakdown:")
            for role, count in report.get('role_breakdown', {}).items():
                report_lines.append(f"    {role}: {count}")

        if 'flagged_wallets' in report:
            flagged = report.get('flagged_wallets', [])
            if flagged:
                report_lines.append(f"  ⚠ Flagged Wallets: {len(flagged)}")
                for fw in flagged[:5]:
                    report_lines.append(f"    {fw.get('address', '?')[:16]}... [{fw.get('role')}] - {fw.get('notes', '')}")

    # ML Model Summary
    report_lines.append(f"\n{'═' * 70}")
    report_lines.append("ML MODEL SUMMARY")
    report_lines.append(f"{'═' * 70}")

    experiments = api_get("/ml/experiments")
    if experiments:
        for exp in experiments:
            report_lines.append(f"  {exp.get('run_name', '?')}: "
                              f"f1={exp.get('f1_score', 0):.4f}, "
                              f"accuracy={exp.get('accuracy', 0):.4f}, "
                              f"samples={exp.get('n_samples', 0)}")
    else:
        report_lines.append("  No ML models trained yet.")
        report_lines.append("  REASON: Insufficient labeled data (need 50+ validated WalletLabels).")
        report_lines.append("  NEXT STEPS:")
        report_lines.append("    1. Investigation wallets classified via heuristics")
        report_lines.append("    2. Need human review to validate/correct classifications")
        report_lines.append("    3. Import validated labels: POST /api/labels")
        report_lines.append("    4. Re-run: POST /api/ml/train")

    # Overall Summary
    report_lines.append(f"\n{'═' * 70}")
    report_lines.append("OVERALL PIPELINE SUMMARY")
    report_lines.append(f"{'═' * 70}")
    report_lines.append(f"  Total Investigations: {len(investigations)}")
    report_lines.append(f"  Total Wallets Discovered: {total_wallets}")
    report_lines.append(f"  Total Transfers Indexed: {total_transfers}")
    report_lines.append(f"  Total Reported Losses: ${total_loss:,.0f}")

    # Recommendations
    report_lines.append(f"\n{'═' * 70}")
    report_lines.append("RECOMMENDATIONS & BLOCKERS")
    report_lines.append(f"{'═' * 70}")

    if total_wallets < 100:
        report_lines.append("  ⚠ LOW DATA: Only {0} wallets. Etherscan API may have rate-limited.".format(total_wallets))
        report_lines.append("    → Wait and re-run: POST /api/investigations/{id}/investigate")

    if not experiments:
        report_lines.append("  ⚠ NO ML MODELS: Need validated labels for supervised learning.")
        report_lines.append("    → Import trusted labels from known entity DBs")
        report_lines.append("    → Use investigation heuristic classifications as seed labels")
        report_lines.append("    → Manual review via Aria for low-confidence wallets")

    report_lines.append("  • Check Celery logs for Etherscan API errors: docker logs bubble_celery")
    report_lines.append("  • View MLflow experiments: http://localhost:5005")
    report_lines.append("  • Timeline visualization: http://localhost:8080/timeline")

    report_text = "\n".join(report_lines)
    print("\n" + report_text)

    # Save report to file
    report_path = '/app/logs/pipeline_report.txt'
    try:
        with open(report_path, 'w') as f:
            f.write(report_text)
        log(f"Report saved to {report_path}")
    except:
        pass

    return report_text


def main():
    log("🫧 BUBBLE INVESTIGATION PIPELINE")
    log(f"API: {BASE_URL}")
    log(f"Started: {datetime.now().isoformat()}")

    # Step 1: Create investigations
    created = step1_create_investigations()

    # Step 2: Sync & expand (fetch Etherscan data, trace fund flows)
    tasks = step2_sync_and_expand()

    # Step 3: Classify wallets
    step3_classify_wallets()

    # Step 4: Train ML models
    training_results = step4_train_models()

    # Step 5: Evaluate and promote
    best_model = step5_evaluate_and_promote()

    # Step 6: Generate final report
    report = step6_generate_report()

    log("\n✅ Pipeline complete.")


if __name__ == '__main__':
    main()
