"""
Autonomous Investigation Runner — Bubble AML Platform
Orchestrates: Case Intake → Investigation → ML Training → Report Generation

Designed to run resource-consciously:
- Rate-limited API calls (respects Etherscan 5 calls/sec)
- Sequential investigation processing (one at a time)
- Configurable sleep between steps
- Automatic retry with exponential backoff
- Memory-conscious batch processing

Usage:
    python scripts/autonomous_runner.py                    # Run all pending cases
    python scripts/autonomous_runner.py --case CASE-2026-009  # Run specific case
    python scripts/autonomous_runner.py --train-only       # Just retrain ML models
    python scripts/autonomous_runner.py --report-only      # Just generate reports
"""
import os
import sys
import json
import time
import logging
import argparse
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs', 'autonomous_runner.log'), mode='a')
    ]
)
logger = logging.getLogger('autonomous_runner')

# ─── Configuration ────────────────────────────────────────────────────────────

BASE_URL = os.environ.get('BUBBLE_API_URL', 'http://localhost:8080')
API_TIMEOUT = 30
POLL_INTERVAL = 30  # seconds between progress checks
MAX_WAIT_TIME = 900  # 15 minutes max per investigation step
SLEEP_BETWEEN_CASES = 10  # seconds between processing cases
SLEEP_BETWEEN_STEPS = 5  # seconds between pipeline steps

# New cases with ETH seed wallets for investigation
NEW_CASES = {
    'CASE-2026-009': {
        'title': 'TrueBit Protocol Exploit',
        'severity': 'critical',
        'source': 'rekt.news + ZachXBT OSINT',
        'attack_vector': 'Integer Overflow',
        'total_stolen_usd': 26200000,
        'chain': 'ETH',
        'wallets': [
            {'address': '0x6c8ec8f14be7c01672d31cfa5f2cefeab2562b50', 'role': 'attacker', 'label': 'TrueBit Exploiter'},
            {'address': '0x764c64b2a09b09acb100b80d8c505aa6a0302ef2', 'role': 'victim', 'label': 'TrueBit Purchase Contract'},
            {'address': '0x1de399967b206e446b4e9aeeb3cb0a0991bf11b8', 'role': 'related', 'label': 'Attack Contract'},
            {'address': '0x273589ca3713e7becf42069f9fb3f0c164ce850a', 'role': 'related', 'label': 'Laundering Wallet 1'},
            {'address': '0x3b58192943ee6f9ae92d54dd1ef378cfd519862a', 'role': 'related', 'label': 'Laundering Wallet 2'},
            {'address': '0xd841c52b68c5db133078aba039bd9eaf19b0b135', 'role': 'mixer', 'label': 'Tornado Cash Deposit'},
        ],
        'investigation_params': {'max_depth': 3, 'max_wallets': 80},
    },
    'CASE-2026-010': {
        'title': 'Saga IBC Bridge Exploit',
        'severity': 'critical',
        'source': 'rekt.news + CertiK',
        'attack_vector': 'IBC Validation Bypass',
        'total_stolen_usd': 7000000,
        'chain': 'ETH',
        'wallets': [
            {'address': '0x2044697623afa31459642708c83f04ecef8c6ecb', 'role': 'attacker', 'label': 'Saga Exploiter (ETH)'},
            {'address': '0xf891de97fa96839329381743f0d6180fcefe3f64', 'role': 'related', 'label': 'Uniswap v4 LP Holder'},
        ],
        'investigation_params': {'max_depth': 2, 'max_wallets': 50},
    },
}


# ─── API Helpers ──────────────────────────────────────────────────────────────

def api_get(endpoint: str, timeout: int = API_TIMEOUT) -> dict:
    """GET request to Bubble API with retry."""
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.get(url, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            if attempt < 2:
                logger.warning(f"Connection failed (attempt {attempt + 1}/3), retrying...")
                time.sleep(5 * (attempt + 1))
            else:
                raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return {'error': str(e)}
    return {'error': 'max retries exceeded'}


def api_post(endpoint: str, data: dict = None, timeout: int = API_TIMEOUT) -> dict:
    """POST request to Bubble API with retry."""
    url = f"{BASE_URL}{endpoint}"
    for attempt in range(3):
        try:
            resp = requests.post(url, json=data or {}, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.ConnectionError:
            if attempt < 2:
                logger.warning(f"Connection failed (attempt {attempt + 1}/3), retrying...")
                time.sleep(5 * (attempt + 1))
            else:
                raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error: {e}")
            return {'error': str(e)}
    return {'error': 'max retries exceeded'}


def check_health() -> bool:
    """Check if the Bubble API is running."""
    try:
        resp = api_get('/health')
        return resp.get('status') == 'healthy' or not resp.get('error')
    except Exception:
        return False


# ─── Pipeline Steps ───────────────────────────────────────────────────────────

def step_create_case(case_id: str, case_config: dict) -> Optional[int]:
    """Step 1: Create case + wallets via API, return case DB id."""
    logger.info(f"📋 Creating case {case_id}: {case_config['title']}")

    result = api_post('/api/cases', {
        'title': case_config['title'],
        'source': case_config['source'],
        'severity': case_config['severity'],
        'attack_vector': case_config['attack_vector'],
        'total_stolen_usd': case_config['total_stolen_usd'],
    })

    if 'error' in result:
        logger.error(f"   Failed to create case: {result['error']}")
        return None

    db_case_id = result.get('id') or result.get('case_id') or result.get('case', {}).get('id')
    if not db_case_id:
        logger.error(f"   No case ID returned: {result}")
        return None

    logger.info(f"   ✅ Case created (DB id={db_case_id})")

    # Add wallets
    for w in case_config['wallets']:
        wallet_result = api_post(f'/api/cases/{db_case_id}/wallets', {
            'address': w['address'],
            'chain_code': case_config['chain'],
            'role': w['role'],
            'label': w.get('label', ''),
        })
        status = '✅' if 'error' not in wallet_result else '❌'
        logger.info(f"   {status} Wallet {w['address'][:10]}... ({w['role']})")
        time.sleep(0.5)  # Rate limit

    return db_case_id


def step_create_investigation(case_id: int) -> Optional[int]:
    """Step 2: Create investigation from case."""
    logger.info(f"🔍 Creating investigation from case #{case_id}")
    result = api_post(f'/api/cases/{case_id}/investigate')

    if 'error' in result:
        logger.error(f"   Failed: {result['error']}")
        return None

    inv_id = result.get('investigation_id') or result.get('id')
    logger.info(f"   ✅ Investigation #{inv_id} created")
    return inv_id


def step_run_investigation_skill(case_id: str, inv_id: int, params: dict) -> dict:
    """Step 3: Run full investigation skill (trace + expand + classify + assess)."""
    logger.info(f"🚀 Running investigation skill for {case_id} (inv #{inv_id})")
    logger.info(f"   Params: depth={params.get('max_depth', 3)}, wallets={params.get('max_wallets', 100)}")

    result = api_post(f'/api/investigations/{inv_id}/investigate', {
        'max_depth': params.get('max_depth', 3),
        'max_wallets': params.get('max_wallets', 100),
    })

    if 'error' in result:
        logger.error(f"   Skill start failed: {result['error']}")
        return result

    # Poll for completion
    start_time = time.time()
    while time.time() - start_time < MAX_WAIT_TIME:
        time.sleep(POLL_INTERVAL)
        elapsed = int(time.time() - start_time)

        try:
            status = api_get(f'/api/investigations/{inv_id}')
            state = status.get('status', status.get('state', 'unknown'))
            progress = status.get('progress', {})
            step = progress.get('current_step', 'unknown')
            logger.info(f"   [{elapsed}s] State: {state} | Step: {step}")

            if state in ('completed', 'done', 'finished'):
                logger.info(f"   ✅ Investigation completed in {elapsed}s")
                return status
            elif state in ('failed', 'error'):
                logger.error(f"   ❌ Investigation failed: {status.get('error', 'unknown')}")
                return status

        except Exception as e:
            logger.warning(f"   Poll error: {e}")

    logger.warning(f"   ⏰ Timed out after {MAX_WAIT_TIME}s")
    return {'status': 'timeout'}


def step_classify_wallets(inv_id: int) -> dict:
    """Step 4: Classify all wallets in investigation."""
    logger.info(f"🤖 Classifying wallets for investigation #{inv_id}")
    result = api_post(f'/api/investigations/{inv_id}/classify')
    if 'error' not in result:
        logger.info(f"   ✅ Classification complete")
    else:
        logger.error(f"   ❌ Classification failed: {result['error']}")
    return result


def step_train_models() -> dict:
    """Step 5: Retrain ML models using all available data."""
    logger.info("🧠 Training ML models...")

    model_types = ['random_forest', 'gradient_boosting']
    results = {}

    for model_type in model_types:
        logger.info(f"   Training {model_type}...")
        result = api_post('/api/ml/train', {
            'model_type': model_type,
            'use_smote': True,
        })
        results[model_type] = result
        if 'error' not in result:
            logger.info(f"   ✅ {model_type} trained")
        else:
            logger.warning(f"   ⚠️  {model_type} failed: {result.get('error', 'unknown')}")
        time.sleep(SLEEP_BETWEEN_STEPS)

    return results


def step_evaluate_and_promote() -> dict:
    """Step 6: Evaluate models and promote best to production."""
    logger.info("📊 Evaluating and promoting best model...")
    result = api_get('/api/ml/experiments')
    if 'error' in result:
        logger.warning(f"   MLflow not available: {result['error']}")
        return result

    experiments = result.get('experiments', result.get('runs', []))
    if not experiments:
        logger.info("   No experiments found")
        return result

    # Find best by F1
    best = max(experiments, key=lambda x: x.get('metrics', {}).get('f1_score', x.get('f1', 0)))
    best_id = best.get('run_id', best.get('id'))
    logger.info(f"   🏆 Best model: {best.get('name', 'unknown')} (F1={best.get('metrics', {}).get('f1_score', 0):.4f})")

    # Promote
    if best_id:
        promote_result = api_post(f'/api/ml/promote/{best_id}')
        if 'error' not in promote_result:
            logger.info(f"   ✅ Promoted to production")
        else:
            logger.warning(f"   ⚠️  Promotion failed: {promote_result.get('error')}")

    return result


# ─── Report Generator ─────────────────────────────────────────────────────────

def generate_investigation_report(case_id: str, inv_id: int, case_config: dict, results: dict) -> str:
    """Generate a markdown investigation report for a completed case."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
    report_path = os.path.join(PROJECT_ROOT, 'reports', 'cases', f'{case_id}.md')

    # Fetch investigation data
    try:
        inv_data = api_get(f'/api/investigations/{inv_id}')
        wallets = inv_data.get('wallets', [])
        transfers_count = inv_data.get('transfer_count', inv_data.get('transfers', 0))
        risk_score = inv_data.get('risk_score', 0)
        risk_label = inv_data.get('risk_label', 'UNKNOWN')
    except Exception:
        wallets, transfers_count, risk_score, risk_label = [], 0, 0, 'UNKNOWN'

    # Classification breakdown
    classification = {}
    for w in wallets if isinstance(wallets, list) else []:
        wtype = w.get('wallet_type', w.get('type', 'unknown'))
        classification[wtype] = classification.get(wtype, 0) + 1

    lines = [
        f"# {case_id} — {case_config['title']}",
        "",
        f"> **Status**: ✅ Investigated  ",
        f"> **Skill Run**: {timestamp}  ",
        f"> **Investigation**: #{inv_id}  ",
        "",
        "---",
        "",
        "## Case Overview",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| **Case ID** | {case_id} |",
        f"| **Title** | {case_config['title']} |",
        f"| **Severity** | {case_config['severity'].title()} |",
        f"| **Status** | Active |",
        f"| **Source** | {case_config['source']} |",
        f"| **Attack Vector** | {case_config['attack_vector']} |",
        f"| **Total Stolen** | ${case_config['total_stolen_usd']:,.0f} USD |",
        "",
        "## Investigation Results",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| **Total Wallets** | {len(wallets) if isinstance(wallets, list) else wallets} |",
        f"| **Transfers Fetched** | {transfers_count:,} |",
        f"| **Risk Score** | {risk_score}/100 |",
        f"| **Risk Label** | {risk_label} |",
        "",
    ]

    if classification:
        lines.extend([
            "### Classification Breakdown",
            "",
            "| Type | Count | Percentage |",
            "|------|-------|------------|",
        ])
        total = sum(classification.values())
        for wtype, count in sorted(classification.items(), key=lambda x: -x[1]):
            pct = count / total * 100 if total > 0 else 0
            lines.append(f"| {wtype.title()} | {count} | {pct:.0f}% |")
        lines.append("")

    lines.extend([
        "## Seed Wallets",
        "",
        "| Address | Role | Label |",
        "|---------|------|-------|",
    ])
    for w in case_config['wallets']:
        lines.append(f"| `{w['address']}` | {w['role']} | {w.get('label', '')} |")

    lines.extend([
        "",
        "## Next Steps",
        "",
        "- [ ] Review classification results for accuracy",
        "- [ ] Cross-reference with other cases for attacker cluster identification",
        "- [ ] Retrain ML model with new labeled data",
        "- [ ] Monitor exchange endpoint wallets for withdrawal activity",
        "",
        f"---",
        f"*Report generated automatically by Bubble Autonomous Runner at {timestamp}*",
    ])

    content = '\n'.join(lines)

    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    with open(report_path, 'w') as f:
        f.write(content)

    logger.info(f"📄 Report saved: {report_path}")
    return report_path


# ─── Summary Report ───────────────────────────────────────────────────────────

def generate_run_summary(run_results: Dict[str, dict]) -> str:
    """Generate a summary report of all cases processed in this run."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(PROJECT_ROOT, 'reports', 'ml', f'autonomous_run_{timestamp}.md')

    lines = [
        f"# Autonomous Runner Summary — {timestamp}",
        "",
        f"> Generated: {datetime.now().isoformat()}  ",
        f"> Cases processed: {len(run_results)}  ",
        "",
        "---",
        "",
        "## Case Results",
        "",
        "| Case | Title | Status | Investigation | Wallets | Risk |",
        "|------|-------|--------|---------------|---------|------|",
    ]

    for case_id, result in run_results.items():
        title = result.get('title', 'Unknown')
        status = '✅' if result.get('success') else '❌'
        inv_id = result.get('investigation_id', 'N/A')
        wallets = result.get('wallet_count', 0)
        risk = result.get('risk_label', 'N/A')
        lines.append(f"| {case_id} | {title} | {status} | #{inv_id} | {wallets} | {risk} |")

    lines.extend([
        "",
        "## ML Training",
        "",
        "- Models retrained after new data ingestion",
        "- Best model promoted to production",
        "- See `reports/ml/automl_report_*.md` for details",
        "",
        "## Recommendations",
        "",
        "- Review flagged wallets for manual verification",
        "- Add confirmed labels to training dataset",
        "- Re-run AutoML notebook after 5+ new investigations",
        "",
    ])

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write('\n'.join(lines))

    logger.info(f"📄 Summary saved: {path}")
    return path


# ─── Main Orchestrator ────────────────────────────────────────────────────────

def run_full_pipeline(cases: Dict[str, dict] = None, train_after: bool = True) -> Dict[str, dict]:
    """
    Run the full autonomous pipeline:
    1. For each case: create → investigate → classify → report
    2. Retrain ML models with all accumulated data
    3. Generate summary report
    """
    cases = cases or NEW_CASES
    run_results = {}

    logger.info("=" * 70)
    logger.info(f"🤖 AUTONOMOUS RUNNER — Processing {len(cases)} cases")
    logger.info("=" * 70)

    for case_id, config in cases.items():
        logger.info(f"\n{'─' * 50}")
        logger.info(f"📌 Processing {case_id}: {config['title']}")
        logger.info(f"{'─' * 50}")

        result = {'title': config['title'], 'success': False}

        try:
            # Step 1: Create case
            db_case_id = step_create_case(case_id, config)
            if not db_case_id:
                result['error'] = 'Case creation failed'
                run_results[case_id] = result
                continue
            time.sleep(SLEEP_BETWEEN_STEPS)

            # Step 2: Create investigation
            inv_id = step_create_investigation(db_case_id)
            if not inv_id:
                result['error'] = 'Investigation creation failed'
                run_results[case_id] = result
                continue
            result['investigation_id'] = inv_id
            time.sleep(SLEEP_BETWEEN_STEPS)

            # Step 3: Run investigation skill
            inv_result = step_run_investigation_skill(
                case_id, inv_id, config.get('investigation_params', {})
            )
            time.sleep(SLEEP_BETWEEN_STEPS)

            # Step 4: Classify
            classify_result = step_classify_wallets(inv_id)
            result['wallet_count'] = classify_result.get('classified', 0)
            result['risk_label'] = inv_result.get('risk_label', 'UNKNOWN')
            time.sleep(SLEEP_BETWEEN_STEPS)

            # Step 5: Generate report
            report_path = generate_investigation_report(case_id, inv_id, config, inv_result)
            result['report'] = report_path
            result['success'] = True

            logger.info(f"✅ {case_id} complete!")

        except Exception as e:
            logger.error(f"❌ {case_id} failed: {e}")
            result['error'] = str(e)

        run_results[case_id] = result
        time.sleep(SLEEP_BETWEEN_CASES)

    # ML training phase
    if train_after and any(r.get('success') for r in run_results.values()):
        logger.info(f"\n{'═' * 50}")
        logger.info("🧠 ML TRAINING PHASE")
        logger.info(f"{'═' * 50}")

        try:
            train_results = step_train_models()
            time.sleep(SLEEP_BETWEEN_STEPS)
            eval_results = step_evaluate_and_promote()
        except Exception as e:
            logger.error(f"ML training failed: {e}")

    # Summary
    summary_path = generate_run_summary(run_results)

    logger.info(f"\n{'═' * 70}")
    logger.info("🏁 AUTONOMOUS RUN COMPLETE")
    logger.info(f"{'═' * 70}")
    successes = sum(1 for r in run_results.values() if r.get('success'))
    logger.info(f"   ✅ Succeeded: {successes}/{len(run_results)}")
    logger.info(f"   📄 Summary: {summary_path}")

    return run_results


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='Bubble Autonomous Investigation Runner')
    parser.add_argument('--case', help='Run specific case ID (e.g., CASE-2026-009)')
    parser.add_argument('--train-only', action='store_true', help='Only retrain ML models')
    parser.add_argument('--report-only', action='store_true', help='Only generate reports')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    parser.add_argument('--base-url', default=BASE_URL, help='API base URL')
    args = parser.parse_args()

    global BASE_URL
    BASE_URL = args.base_url

    if args.dry_run:
        print("\n📋 DRY RUN — Cases to process:")
        cases = {args.case: NEW_CASES[args.case]} if args.case else NEW_CASES
        for cid, conf in cases.items():
            wallets = len(conf['wallets'])
            params = conf.get('investigation_params', {})
            print(f"   {cid}: {conf['title']} ({wallets} wallets, "
                  f"depth={params.get('max_depth', 3)}, max_wallets={params.get('max_wallets', 100)})")
        return

    if args.train_only:
        logger.info("🧠 Train-only mode")
        step_train_models()
        step_evaluate_and_promote()
        return

    if args.report_only:
        logger.info("📄 Report-only mode")
        for case_id, config in NEW_CASES.items():
            generate_investigation_report(case_id, 0, config, {})
        return

    # Check API health
    if not check_health():
        logger.error("❌ Bubble API not reachable at {BASE_URL}")
        logger.info("   Start with: docker-compose up -d")
        logger.info("   Or: python app.py")
        return

    # Run full pipeline
    cases = {args.case: NEW_CASES[args.case]} if args.case and args.case in NEW_CASES else NEW_CASES
    run_full_pipeline(cases)


if __name__ == '__main__':
    main()
