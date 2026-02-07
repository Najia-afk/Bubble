"""
Automated Report Generator — Bubble AML Platform
Generates structured investigation and ML reports from database state.
Designed to produce LLM-consumable markdown that can be further enriched.

Usage:
    python scripts/report_generator.py                     # Generate all reports
    python scripts/report_generator.py --investigation 2   # Specific investigation
    python scripts/report_generator.py --ml                # ML evaluation report
    python scripts/report_generator.py --summary           # Platform-wide summary
"""
import os
import sys
import json
import argparse
from datetime import datetime
from typing import Dict, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class ReportGenerator:
    """
    Multi-format report generator for investigations and ML evaluations.
    All reports are Markdown with structured tables for LLM parsing.
    """

    def __init__(self, db_url: str = None):
        self.db_url = db_url
        self._loader = None
        self.timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')

    @property
    def loader(self):
        if self._loader is None:
            from notebooks.src.data_loader import DataLoader
            self._loader = DataLoader(self.db_url)
        return self._loader

    # ─── Investigation Report ─────────────────────────────────────────────

    def generate_investigation_report(self, investigation_id: int,
                                      case_title: str = None,
                                      output_dir: str = None) -> str:
        """Generate a complete investigation report from DB data."""
        wallets_df = self.loader.get_wallets(investigation_id)
        transfers_df = self.loader.get_transfers(investigation_id)
        edges_df = self.loader.get_edges(investigation_id)

        if wallets_df.empty:
            return f"# Investigation #{investigation_id}\n\n> No data found."

        title = case_title or f"Investigation #{investigation_id}"
        total_wallets = len(wallets_df)
        total_transfers = len(transfers_df)

        # Role distribution
        role_dist = wallets_df['role'].value_counts().to_dict() if 'role' in wallets_df.columns else {}

        # Value analysis
        total_volume = 0
        if not transfers_df.empty and 'value' in transfers_df.columns:
            transfers_df['value_eth'] = transfers_df['value'].astype(float) / 1e18
            total_volume = transfers_df['value_eth'].sum()

        # Timeline
        date_range = ''
        if not transfers_df.empty and 'timestamp' in transfers_df.columns:
            ts = transfers_df['timestamp']
            date_range = f"{ts.min()} → {ts.max()}"

        # Top wallets by activity
        top_senders = transfers_df['from_address'].value_counts().head(10) if not transfers_df.empty else {}
        top_receivers = transfers_df['to_address'].value_counts().head(10) if not transfers_df.empty else {}

        lines = [
            f"# {title}",
            "",
            f"> **Generated**: {self.timestamp}  ",
            f"> **Investigation ID**: {investigation_id}  ",
            f"> **Total Wallets**: {total_wallets}  ",
            f"> **Total Transfers**: {total_transfers:,}  ",
            f"> **Total Volume**: {total_volume:,.2f} ETH  ",
            f"> **Date Range**: {date_range}  ",
            "",
            "---",
            "",
            "## Wallet Role Distribution",
            "",
            "| Role | Count | Percentage |",
            "|------|-------|------------|",
        ]
        for role, count in sorted(role_dist.items(), key=lambda x: -x[1]):
            pct = count / total_wallets * 100
            lines.append(f"| {role} | {count} | {pct:.1f}% |")

        # Attacker wallets
        attackers = wallets_df[wallets_df['role'].isin(['attacker', 'theft_origin'])] if 'role' in wallets_df.columns else wallets_df.head(0)
        if not attackers.empty:
            lines.extend([
                "",
                "## Attacker / Threat Actor Wallets",
                "",
                "| Address | Role | Depth |",
                "|---------|------|-------|",
            ])
            for _, w in attackers.iterrows():
                addr = w.get('address', '')
                role = w.get('role', '')
                depth = w.get('depth', 0)
                lines.append(f"| `{addr}` | {role} | {depth} |")

        # Exchange endpoints
        exchanges = wallets_df[wallets_df['role'] == 'exchange'] if 'role' in wallets_df.columns else wallets_df.head(0)
        if not exchanges.empty:
            lines.extend([
                "",
                "## Exchange Endpoints (Fund Destinations)",
                "",
                "| Address | Depth | Notes |",
                "|---------|-------|-------|",
            ])
            for _, w in exchanges.head(20).iterrows():
                addr = w.get('address', '')
                depth = w.get('depth', 0)
                label = w.get('label', w.get('name_tag', ''))
                lines.append(f"| `{addr}` | {depth} | {label} |")

        # Mixer / Bridge detection
        for role_type in ['mixer', 'bridge']:
            typed_wallets = wallets_df[wallets_df['role'] == role_type] if 'role' in wallets_df.columns else wallets_df.head(0)
            if not typed_wallets.empty:
                lines.extend([
                    "",
                    f"## {role_type.title()} Addresses Detected",
                    "",
                    "| Address | Depth |",
                    "|---------|-------|",
                ])
                for _, w in typed_wallets.iterrows():
                    lines.append(f"| `{w.get('address', '')}` | {w.get('depth', 0)} |")

        # Top activity
        if len(top_senders) > 0:
            lines.extend([
                "",
                "## Top 10 Active Senders",
                "",
                "| Address | TX Count |",
                "|---------|----------|",
            ])
            for addr, count in top_senders.items():
                lines.append(f"| `{addr}` | {count:,} |")

        if len(top_receivers) > 0:
            lines.extend([
                "",
                "## Top 10 Active Receivers",
                "",
                "| Address | TX Count |",
                "|---------|----------|",
            ])
            for addr, count in top_receivers.items():
                lines.append(f"| `{addr}` | {count:,} |")

        # Network stats
        if not edges_df.empty:
            lines.extend([
                "",
                "## Network Analysis",
                "",
                f"- **Unique edges**: {len(edges_df)}",
                f"- **Avg transfers per edge**: {edges_df['tx_count'].mean():.1f}" if 'tx_count' in edges_df.columns else "",
            ])

        lines.extend([
            "",
            "---",
            "",
            "## LLM Analysis Prompt",
            "",
            "Use the data above to:",
            "1. Identify the fund flow pattern (layering, peeling chain, smurfing)",
            "2. Assess mixer/bridge usage and recovery feasibility",
            "3. Recommend law enforcement actions (freeze requests, subpoenas)",
            "4. Estimate total recoverable funds",
            "5. Identify cross-case correlations with known attacker clusters",
            "",
            f"*Report generated by Bubble Report Generator at {self.timestamp}*",
        ])

        content = '\n'.join(lines)

        # Save
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, f'investigation_{investigation_id}_report.md')
            with open(path, 'w') as f:
                f.write(content)
            print(f"📄 Report saved: {path}")

        return content

    # ─── ML Evaluation Report ─────────────────────────────────────────────

    def generate_ml_report(self, output_dir: str = None) -> str:
        """Generate ML model evaluation report from current model state."""
        scores_df = self.loader.get_wallet_scores()

        lines = [
            "# ML Model Evaluation Report",
            "",
            f"> **Generated**: {self.timestamp}  ",
            f"> **Total Scored Wallets**: {len(scores_df)}  ",
            "",
            "---",
            "",
        ]

        if scores_df.empty:
            lines.append("⚠️ No wallet scores found in database. Run classification first.")
        else:
            # Score distribution
            if 'predicted_type' in scores_df.columns:
                type_dist = scores_df['predicted_type'].value_counts()
                lines.extend([
                    "## Classification Distribution",
                    "",
                    "| Type | Count | Percentage |",
                    "|------|-------|------------|",
                ])
                for wtype, count in type_dist.items():
                    pct = count / len(scores_df) * 100
                    lines.append(f"| {wtype} | {count} | {pct:.1f}% |")
                lines.append("")

            # Confidence analysis
            if 'confidence' in scores_df.columns:
                lines.extend([
                    "## Confidence Analysis",
                    "",
                    f"- **Mean confidence**: {scores_df['confidence'].mean():.3f}",
                    f"- **Median confidence**: {scores_df['confidence'].median():.3f}",
                    f"- **Low confidence (<0.6)**: {(scores_df['confidence'] < 0.6).sum()} wallets",
                    f"- **High confidence (>0.9)**: {(scores_df['confidence'] > 0.9).sum()} wallets",
                    "",
                ])

            # Anomaly detection
            if 'is_anomaly' in scores_df.columns:
                anomalies = scores_df[scores_df['is_anomaly'] == True]
                lines.extend([
                    "## Anomaly Detection",
                    "",
                    f"- **Anomalous wallets**: {len(anomalies)}",
                    f"- **Anomaly rate**: {len(anomalies) / len(scores_df) * 100:.1f}%",
                    "",
                ])

            # Model version
            if 'model_version' in scores_df.columns:
                versions = scores_df['model_version'].value_counts()
                lines.extend([
                    "## Model Versions in Use",
                    "",
                    "| Version | Wallets |",
                    "|---------|---------|",
                ])
                for ver, count in versions.items():
                    lines.append(f"| {ver} | {count} |")

        lines.extend([
            "",
            "## Recommendations",
            "",
            "1. Run `notebooks/05_auto_ml.ipynb` for full AutoML comparison",
            "2. Target 2000+ training samples for production quality",
            "3. Enable SHAP explainability for audit compliance",
            "4. Set up Evidently drift monitoring",
            "5. Validate low-confidence predictions manually",
            "",
            f"*Report generated by Bubble Report Generator at {self.timestamp}*",
        ])

        content = '\n'.join(lines)

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, 'ml_evaluation_report.md')
            with open(path, 'w') as f:
                f.write(content)
            print(f"📄 Report saved: {path}")

        return content

    # ─── Platform Summary ─────────────────────────────────────────────────

    def generate_platform_summary(self, output_dir: str = None) -> str:
        """Generate a platform-wide summary of all investigations and ML state."""
        lines = [
            "# Bubble AML Platform — Status Summary",
            "",
            f"> **Generated**: {self.timestamp}  ",
            "",
            "---",
            "",
            "## Active Investigations",
            "",
            "| # | Wallets | Transfers | Top Roles |",
            "|---|---------|-----------|-----------|",
        ]

        total_wallets = 0
        total_transfers = 0

        for inv_id in range(1, 20):
            try:
                w = self.loader.get_wallets(inv_id)
                t = self.loader.get_transfers(inv_id)
                if w.empty:
                    continue
                roles = ', '.join(w['role'].value_counts().head(3).index.tolist()) if 'role' in w.columns else ''
                lines.append(f"| {inv_id} | {len(w)} | {len(t):,} | {roles} |")
                total_wallets += len(w)
                total_transfers += len(t)
            except Exception:
                continue

        lines.extend([
            "",
            f"**Totals**: {total_wallets} wallets, {total_transfers:,} transfers",
            "",
        ])

        # ML state
        try:
            scores = self.loader.get_wallet_scores()
            lines.extend([
                "## ML Classification State",
                "",
                f"- Scored wallets: {len(scores)}",
            ])
            if not scores.empty and 'predicted_type' in scores.columns:
                lines.append(f"- Types: {', '.join(scores['predicted_type'].value_counts().head(5).index.tolist())}")
        except Exception:
            lines.append("- ML scores: Not available")

        # Case files
        cases_dir = os.path.join(PROJECT_ROOT, 'reports', 'cases')
        if os.path.isdir(cases_dir):
            case_files = sorted(f for f in os.listdir(cases_dir) if f.startswith('CASE-'))
            lines.extend([
                "",
                "## Case Reports",
                "",
                f"Total case files: {len(case_files)}",
                "",
            ])
            for cf in case_files:
                lines.append(f"- [{cf}](cases/{cf})")

        lines.extend([
            "",
            "---",
            "",
            "## Quick Actions for LLM",
            "",
            "1. **New case**: Add seed wallets to `scripts/autonomous_runner.py` → run pipeline",
            "2. **Retrain ML**: Run `notebooks/05_auto_ml.ipynb` or `python scripts/autonomous_runner.py --train-only`",
            "3. **Generate reports**: `python scripts/report_generator.py --summary`",
            "4. **Add OSINT**: Update `reports/cases/CASE-2026-xxx.md` with new findings",
            "",
            f"*Platform summary generated at {self.timestamp}*",
        ])

        content = '\n'.join(lines)

        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
            path = os.path.join(output_dir, 'platform_summary.md')
            with open(path, 'w') as f:
                f.write(content)
            print(f"📄 Report saved: {path}")

        return content


def main():
    parser = argparse.ArgumentParser(description='Bubble Report Generator')
    parser.add_argument('--investigation', type=int, help='Generate report for specific investigation ID')
    parser.add_argument('--ml', action='store_true', help='Generate ML evaluation report')
    parser.add_argument('--summary', action='store_true', help='Generate platform summary')
    parser.add_argument('--all', action='store_true', help='Generate all reports')
    parser.add_argument('--output', default=os.path.join(PROJECT_ROOT, 'reports'),
                        help='Output directory for reports')
    args = parser.parse_args()

    gen = ReportGenerator()

    if args.investigation:
        gen.generate_investigation_report(args.investigation, output_dir=args.output)
    elif args.ml:
        gen.generate_ml_report(output_dir=os.path.join(args.output, 'ml'))
    elif args.summary:
        gen.generate_platform_summary(output_dir=args.output)
    elif args.all:
        gen.generate_platform_summary(output_dir=args.output)
        gen.generate_ml_report(output_dir=os.path.join(args.output, 'ml'))
        for inv_id in range(1, 15):
            try:
                gen.generate_investigation_report(inv_id, output_dir=args.output)
            except Exception:
                pass
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
