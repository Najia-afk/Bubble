# api/tasks/investigation_tasks.py
"""
BACKWARD-COMPAT RE-EXPORT HUB.

All investigation tasks have been split into focused modules:
  - investigation_sync_tasks.py    → sync_investigation_transfers, backfill_token_prices_for_transfers
  - investigation_expand_tasks.py  → expand_investigation, sync_and_expand, _load_known_addresses, _determine_role
  - investigation_classify_tasks.py → classify_investigation_wallets, _classify_from_transfers
  - investigation_report_tasks.py  → generate_investigation_report

This file re-exports everything so existing imports continue to work.
"""

# ── AML Investigation Skill Task (kept here — tiny, top-level entry point) ──
from celery import shared_task


@shared_task(name='run_investigation_skill', bind=True, max_retries=0,
             soft_time_limit=1800, time_limit=2000)
def run_investigation_skill_task(self, case_id: str, max_depth: int = 3,
                                  max_wallets: int = 100):
    """
    Celery wrapper for the AML Investigation Skill pipeline.
    Runs the full 6-step automated investigation and stores progress in Redis.
    """
    from api.services.investigation_skill import run_investigation_skill
    return run_investigation_skill(case_id, max_depth=max_depth, max_wallets=max_wallets)


# ── Re-exports from sub-modules ──────────────────────────────────────────

from api.tasks.investigation_sync_tasks import (
    sync_investigation_transfers,
    backfill_token_prices_for_transfers,
    _get_scan_key,
)

from api.tasks.investigation_expand_tasks import (
    expand_investigation,
    sync_and_expand,
    _load_known_addresses,
    _determine_role,
    TERMINAL_ROLES,
    HIGH_COUNTERPARTY_THRESHOLD,
)

from api.tasks.investigation_classify_tasks import (
    classify_investigation_wallets,
    _classify_from_transfers,
)

from api.tasks.investigation_report_tasks import (
    generate_investigation_report,
)

__all__ = [
    'run_investigation_skill_task',
    'sync_investigation_transfers',
    'backfill_token_prices_for_transfers',
    'expand_investigation',
    'sync_and_expand',
    'classify_investigation_wallets',
    'generate_investigation_report',
    '_get_scan_key',
    '_load_known_addresses',
    '_determine_role',
    '_classify_from_transfers',
    'TERMINAL_ROLES',
    'HIGH_COUNTERPARTY_THRESHOLD',
]
