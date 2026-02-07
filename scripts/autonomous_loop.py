"""
Bubble Autonomous Loop — Continuous Investigation & ML Pipeline
Runs as a background service, periodically checking for new cases,
running investigations, retraining models, and generating reports.

Architecture:
    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌──────────────┐
    │  OSINT Feed  │───▶│ Case Intake │───▶│Investigation│───▶│  ML Training │
    │ (ZachXBT etc)│    │  & Wallets  │    │   Pipeline  │    │   & AutoML   │
    └─────────────┘    └─────────────┘    └─────────────┘    └──────────────┘
                                                                      │
    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐            │
    │  LLM Report │◀───│   Report    │◀───│  Evaluate   │◀───────────┘
    │  Enrichment │    │  Generator  │    │  & Promote  │
    └─────────────┘    └─────────────┘    └─────────────┘

Usage:
    python scripts/autonomous_loop.py                    # Run once
    python scripts/autonomous_loop.py --daemon           # Run continuously
    python scripts/autonomous_loop.py --interval 3600    # Check every hour
"""
import os
import sys
import time
import logging
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

STATE_FILE = os.path.join(PROJECT_ROOT, 'logs', 'autonomous_state.json')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(PROJECT_ROOT, 'logs', 'autonomous_loop.log'), mode='a')
    ]
)
logger = logging.getLogger('autonomous_loop')


class AutonomousState:
    """Persistent state for the autonomous loop."""

    def __init__(self):
        self.processed_cases: list = []
        self.last_training: str = None
        self.last_report: str = None
        self.total_runs: int = 0
        self.total_wallets_classified: int = 0
        self.champion_model: str = None
        self.champion_f1: float = 0.0
        self.load()

    def load(self):
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE) as f:
                    data = json.load(f)
                    for k, v in data.items():
                        if hasattr(self, k):
                            setattr(self, k, v)
        except Exception as e:
            logger.warning(f"Could not load state: {e}")

    def save(self):
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, 'w') as f:
            json.dump({
                'processed_cases': self.processed_cases,
                'last_training': self.last_training,
                'last_report': self.last_report,
                'total_runs': self.total_runs,
                'total_wallets_classified': self.total_wallets_classified,
                'champion_model': self.champion_model,
                'champion_f1': self.champion_f1,
            }, f, indent=2)

    def mark_case_processed(self, case_id: str):
        if case_id not in self.processed_cases:
            self.processed_cases.append(case_id)
        self.save()


def get_pending_cases(state: AutonomousState) -> dict:
    """Scan case reports for cases with seed wallets that haven't been processed."""
    from scripts.autonomous_runner import NEW_CASES

    pending = {}
    for case_id, config in NEW_CASES.items():
        if case_id not in state.processed_cases:
            pending[case_id] = config

    # Also check reports/cases/ for any with "Pending Investigation" status
    cases_dir = os.path.join(PROJECT_ROOT, 'reports', 'cases')
    if os.path.isdir(cases_dir):
        for fname in os.listdir(cases_dir):
            if not fname.startswith('CASE-') or not fname.endswith('.md'):
                continue
            case_id = fname.replace('.md', '')
            if case_id in state.processed_cases or case_id in pending:
                continue
            # Check if it has seed wallets
            try:
                with open(os.path.join(cases_dir, fname)) as f:
                    content = f.read()
                if 'Pending Investigation' in content and '0x' in content:
                    logger.info(f"   Found pending case with seed wallets: {case_id}")
            except Exception:
                pass

    return pending


def should_retrain(state: AutonomousState) -> bool:
    """Decide if ML models should be retrained."""
    if not state.last_training:
        return True
    try:
        last = datetime.fromisoformat(state.last_training)
        # Retrain if >24h since last training or if new cases were processed
        return (datetime.now() - last) > timedelta(hours=24)
    except Exception:
        return True


def run_automl_training(state: AutonomousState):
    """Run the AutoML engine for model selection and training."""
    logger.info("🧠 Running AutoML model selection...")

    try:
        from notebooks.src.data_loader import DataLoader
        from notebooks.src.automl_engine import BubbleAutoML

        loader = DataLoader()
        automl = BubbleAutoML(loader=loader)

        results = automl.run(
            n_trials=10,  # Conservative for background operation
            timeout_per_model=90,
            cv_folds=5,
            use_smote=True,
        )

        if automl.best_model_name:
            state.champion_model = automl.best_model_name
            best_metrics = results.get(automl.best_model_name, {})
            state.champion_f1 = best_metrics.get('f1_weighted', 0)
            logger.info(f"   🏆 Champion: {automl.best_model_name} (F1={state.champion_f1:.4f})")

            # Try promote to MLflow
            automl.promote_best()

            # Save report
            automl.save_report()

        state.last_training = datetime.now().isoformat()
        state.save()

    except Exception as e:
        logger.error(f"   AutoML failed: {e}")
        # Fallback to API-based training
        try:
            from scripts.autonomous_runner import step_train_models, step_evaluate_and_promote
            step_train_models()
            step_evaluate_and_promote()
            state.last_training = datetime.now().isoformat()
            state.save()
        except Exception as e2:
            logger.error(f"   Fallback training also failed: {e2}")


def run_report_generation(state: AutonomousState):
    """Generate all pending reports."""
    logger.info("📄 Generating reports...")

    try:
        from scripts.report_generator import ReportGenerator
        gen = ReportGenerator()

        # Platform summary
        gen.generate_platform_summary(output_dir=os.path.join(PROJECT_ROOT, 'reports'))

        # ML report
        gen.generate_ml_report(output_dir=os.path.join(PROJECT_ROOT, 'reports', 'ml'))

        state.last_report = datetime.now().isoformat()
        state.save()
        logger.info("   ✅ Reports generated")

    except Exception as e:
        logger.error(f"   Report generation failed: {e}")


def run_single_cycle(state: AutonomousState):
    """Execute one complete cycle of the autonomous loop."""
    state.total_runs += 1
    logger.info(f"\n{'═' * 70}")
    logger.info(f"🔄 AUTONOMOUS CYCLE #{state.total_runs} — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'═' * 70}")

    # 1. Check for pending cases
    pending = get_pending_cases(state)
    if pending:
        logger.info(f"📋 Found {len(pending)} pending cases: {', '.join(pending.keys())}")

        # Process cases via autonomous runner
        try:
            from scripts.autonomous_runner import run_full_pipeline
            results = run_full_pipeline(pending, train_after=False)

            for case_id, result in results.items():
                if result.get('success'):
                    state.mark_case_processed(case_id)
                    state.total_wallets_classified += result.get('wallet_count', 0)
        except Exception as e:
            logger.error(f"Pipeline failed: {e}")
    else:
        logger.info("📋 No pending cases")

    # 2. Retrain if needed
    if should_retrain(state):
        run_automl_training(state)
    else:
        logger.info(f"🧠 ML training up to date (last: {state.last_training})")

    # 3. Generate reports
    run_report_generation(state)

    # 4. Summary
    state.save()
    logger.info(f"\n📊 CYCLE #{state.total_runs} SUMMARY:")
    logger.info(f"   Cases processed total: {len(state.processed_cases)}")
    logger.info(f"   Wallets classified total: {state.total_wallets_classified}")
    logger.info(f"   Champion model: {state.champion_model} (F1={state.champion_f1:.4f})")
    logger.info(f"   Last training: {state.last_training}")


def main():
    parser = argparse.ArgumentParser(description='Bubble Autonomous Loop')
    parser.add_argument('--daemon', action='store_true', help='Run continuously')
    parser.add_argument('--interval', type=int, default=3600, help='Seconds between cycles (default: 1h)')
    parser.add_argument('--reset', action='store_true', help='Reset persistent state')
    args = parser.parse_args()

    state = AutonomousState()

    if args.reset:
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        state = AutonomousState()
        logger.info("🗑️  State reset")

    if args.daemon:
        logger.info(f"🤖 Autonomous daemon started (interval: {args.interval}s)")
        while True:
            try:
                run_single_cycle(state)
            except KeyboardInterrupt:
                logger.info("🛑 Stopped by user")
                break
            except Exception as e:
                logger.error(f"Cycle error: {e}")

            logger.info(f"\n⏳ Next cycle in {args.interval}s...")
            time.sleep(args.interval)
    else:
        run_single_cycle(state)


if __name__ == '__main__':
    main()
