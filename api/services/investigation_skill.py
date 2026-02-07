"""
AML Investigation Skill Engine
===============================
Automated crypto-forensic pipeline — the "Crypto Investigator" skill.

Runs a multi-step analysis on a case:
  1. IMPORT   — Case → Investigation (seed wallets)
  2. TRACE    — Sync transfers from blockchain (Etherscan v2)
  3. EXPAND   — Follow the money (outgoing → suspects, incoming → funds source)
  4. CLASSIFY — ML model + heuristics + known-entity matching
  5. ASSESS   — Risk scoring, exchange/mixer/bridge detection
  6. REPORT   — Generate findings summary

Progress is streamed to Redis so the UI can poll for live updates.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Optional

from sqlalchemy import func

logger = logging.getLogger('celery_tasks')


# ── Redis progress helpers ──────────────────────────────────────────────

def _redis_client():
    """Lazy import to avoid circular imports at module level."""
    from celery_worker import celery_app
    return celery_app.backend.client


SKILL_KEY_PREFIX = 'skill:investigation:'


def _skill_key(case_id: str) -> str:
    return f'{SKILL_KEY_PREFIX}{case_id}'


def save_skill_progress(case_id: str, state: Dict):
    """Persist skill execution state to Redis (TTL 24h)."""
    r = _redis_client()
    r.setex(_skill_key(case_id), 86400, json.dumps(state, default=str))


def get_skill_progress(case_id: str) -> Optional[Dict]:
    """Read current skill execution state from Redis."""
    r = _redis_client()
    raw = r.get(_skill_key(case_id))
    if raw:
        return json.loads(raw)
    return None


# ── Skill Step Definitions ──────────────────────────────────────────────

SKILL_STEPS = [
    {'id': 'import',   'label': 'Import Case',        'icon': '📥', 'description': 'Create investigation from case wallets'},
    {'id': 'trace',    'label': 'Trace Transfers',     'icon': '🔗', 'description': 'Fetch ERC20 transfers from blockchain'},
    {'id': 'expand',   'label': 'Follow the Money',    'icon': '🕵️', 'description': 'Discover connected wallets via fund flows'},
    {'id': 'classify', 'label': 'ML Classification',   'icon': '🤖', 'description': 'Run ML models + heuristics on all wallets'},
    {'id': 'assess',   'label': 'Risk Assessment',     'icon': '⚠️', 'description': 'Score risk, detect exchanges/mixers/bridges'},
    {'id': 'report',   'label': 'Generate Report',     'icon': '📊', 'description': 'Compile investigation findings'},
]


def _make_state(case_id: str, investigation_id: int = None, **extra) -> Dict:
    """Build a fresh skill state dict."""
    return {
        'case_id': case_id,
        'investigation_id': investigation_id,
        'status': 'pending',          # pending | running | completed | failed
        'current_step': None,
        'started_at': None,
        'completed_at': None,
        'steps': {s['id']: {'status': 'pending', 'result': None, 'started_at': None, 'completed_at': None} for s in SKILL_STEPS},
        'findings': {},
        'error': None,
        **extra,
    }


# ── Individual step executors ───────────────────────────────────────────

def _step_import(session, case_id: str, state: Dict) -> Dict:
    """Step 1: Import Case → Investigation."""
    from api.application.models import Case, CaseWallet
    from api.application.erc20models import Investigation, InvestigationWallet, InvestigationToken

    case = session.query(Case).filter_by(id=case_id).first()
    if not case:
        raise ValueError(f'Case {case_id} not found')

    # Check if already imported
    existing = session.query(Investigation).filter(
        Investigation.name.ilike(f'%{case_id}%')
    ).first()

    if existing:
        return {
            'investigation_id': existing.id,
            'message': f'Already imported as Investigation #{existing.id}',
            'reused': True,
        }

    # Create investigation
    inv = Investigation(
        name=f'[{case_id}] {case.title}',
        description=case.summary or f'Automated investigation from case {case_id}',
        status='in_progress',
        incident_date=case.date_incident,
        reported_loss_usd=case.total_stolen_usd,
        created_by='skill_engine',
    )
    session.add(inv)
    session.flush()

    # Map case wallets → investigation wallets
    case_wallets = session.query(CaseWallet).filter_by(case_id=case_id).all()
    wallet_count = 0
    chains_seen = set()

    ROLE_MAP = {
        'attacker': 'attacker', 'hacker': 'attacker', 'scammer': 'attacker',
        'exploiter': 'attacker', 'thief': 'attacker',
        'victim': 'victim', 'treasury': 'victim',
        'mixer': 'related', 'bridge': 'related', 'exchange': 'related',
    }

    for cw in case_wallets:
        role = ROLE_MAP.get(cw.role, 'related')
        chain_id = {'ETH': 1, 'POL': 137, 'BSC': 56, 'ARB': 42161, 'OP': 10,
                     'BASE': 8453, 'AVAX': 43114, 'FTM': 250}.get(cw.chain_code, 1)

        session.add(InvestigationWallet(
            investigation_id=inv.id,
            address=cw.address.lower(),
            chain_id=chain_id,
            role=role,
            depth=0,
            parent_address=None,
        ))
        chains_seen.add(cw.chain_code)
        wallet_count += 1

    session.commit()

    return {
        'investigation_id': inv.id,
        'wallets_imported': wallet_count,
        'chains': list(chains_seen),
        'message': f'Created Investigation #{inv.id} with {wallet_count} seed wallets',
        'reused': False,
    }


def _step_trace(session, investigation_id: int, state: Dict) -> Dict:
    """Step 2: Sync transfers from blockchain."""
    from api.tasks.investigation_tasks import sync_investigation_transfers

    result = sync_investigation_transfers(investigation_id)
    if result.get('status') == 'error':
        raise RuntimeError(f"Sync failed: {result.get('message')}")

    return {
        'transfers_added': result.get('transfers_added', 0),
        'wallets_processed': result.get('wallets_processed', 0),
        'message': f"Synced {result.get('transfers_added', 0)} transfers from blockchain",
    }


def _step_expand(session, investigation_id: int, state: Dict,
                 max_depth: int = 3, max_wallets: int = 100) -> Dict:
    """Step 3: Follow the money — discover connected wallets."""
    from api.tasks.investigation_tasks import expand_investigation, sync_investigation_transfers
    from api.application.erc20models import InvestigationWallet

    total_new = 0
    total_transfers = 0
    iterations = 0

    for i in range(max_depth):
        iterations += 1

        expand_result = expand_investigation(investigation_id,
                                             max_depth=max_depth,
                                             max_wallets=max_wallets)
        new_wallets = expand_result.get('new_wallets_added', 0)
        total_new += new_wallets

        if new_wallets == 0:
            break

        # Sync transfers for new wallets
        sync_result = sync_investigation_transfers(investigation_id)
        total_transfers += sync_result.get('transfers_added', 0)

        # Update progress mid-step
        state['steps']['expand']['result'] = {
            'iteration': iterations,
            'new_wallets_so_far': total_new,
            'transfers_so_far': total_transfers,
        }
        save_skill_progress(state['case_id'], state)

        if expand_result.get('total_wallets', 0) >= max_wallets:
            break

    total_wallets = session.query(func.count(InvestigationWallet.id)).filter_by(
        investigation_id=investigation_id
    ).scalar()

    return {
        'iterations': iterations,
        'new_wallets_discovered': total_new,
        'additional_transfers': total_transfers,
        'total_wallets': total_wallets,
        'message': f"Discovered {total_new} wallets in {iterations} hops ({total_wallets} total)",
    }


def _step_classify(session, investigation_id: int, state: Dict) -> Dict:
    """Step 4: ML classification on all investigation wallets."""
    from api.tasks.investigation_tasks import classify_investigation_wallets

    result = classify_investigation_wallets(investigation_id)
    if result.get('status') == 'error':
        raise RuntimeError(f"Classification failed: {result.get('message')}")

    # Aggregate classification results
    type_counts = {}
    source_counts = {}
    for r in result.get('results', []):
        ptype = r.get('predicted_type', 'unknown')
        src = r.get('source', 'unknown')
        type_counts[ptype] = type_counts.get(ptype, 0) + 1
        source_counts[src] = source_counts.get(src, 0) + 1

    return {
        'wallets_classified': result.get('wallets_classified', 0),
        'roles_updated': result.get('roles_updated', 0),
        'by_type': type_counts,
        'by_source': source_counts,
        'message': f"Classified {result.get('wallets_classified', 0)} wallets, {result.get('roles_updated', 0)} roles updated",
    }


def _step_assess(session, investigation_id: int, state: Dict) -> Dict:
    """Step 5: Risk assessment — aggregate risk indicators."""
    from api.application.erc20models import InvestigationWallet, InvestigationTransfer, WalletScore

    wallets = session.query(InvestigationWallet).filter_by(
        investigation_id=investigation_id
    ).all()

    risk_indicators = {
        'exchange_endpoints': [],
        'mixer_interactions': [],
        'bridge_crossings': [],
        'high_risk_wallets': [],
        'flagged_wallets': [],
    }
    risk_score = 0.0
    total_volume = 0.0

    for w in wallets:
        if w.role == 'exchange':
            risk_indicators['exchange_endpoints'].append({
                'address': w.address,
                'received': w.total_received,
            })
            risk_score += 10  # Exchange = potential recovery point
        elif w.role == 'mixer':
            risk_indicators['mixer_interactions'].append({
                'address': w.address,
                'depth': w.depth,
            })
            risk_score += 30  # Mixer = high laundering risk
        elif w.role == 'bridge':
            risk_indicators['bridge_crossings'].append({
                'address': w.address,
                'depth': w.depth,
            })
            risk_score += 20  # Bridge = cross-chain evasion

        if w.is_flagged:
            risk_indicators['flagged_wallets'].append(w.address)

        total_volume += (w.total_received or 0) + (w.total_sent or 0)

    # Check wallet scores for anomalies
    addresses = [w.address for w in wallets]
    if addresses:
        anomalies = session.query(WalletScore).filter(
            WalletScore.address.in_(addresses),
            WalletScore.is_anomaly == True
        ).all()
        for a in anomalies:
            risk_indicators['high_risk_wallets'].append({
                'address': a.address,
                'predicted_type': a.predicted_type,
                'anomaly_score': a.anomaly_score,
            })
            risk_score += 15

    # Normalize risk score (0-100)
    risk_level = min(risk_score, 100)
    if risk_level >= 70:
        risk_label = 'CRITICAL'
    elif risk_level >= 50:
        risk_label = 'HIGH'
    elif risk_level >= 25:
        risk_label = 'MEDIUM'
    else:
        risk_label = 'LOW'

    return {
        'risk_score': risk_level,
        'risk_label': risk_label,
        'total_volume': total_volume,
        'indicators': {k: len(v) if isinstance(v, list) else v for k, v in risk_indicators.items()},
        'details': risk_indicators,
        'message': f"Risk: {risk_label} ({risk_level}/100) — {len(risk_indicators['exchange_endpoints'])} exchanges, "
                   f"{len(risk_indicators['mixer_interactions'])} mixers, {len(risk_indicators['bridge_crossings'])} bridges",
    }


def _step_report(session, investigation_id: int, state: Dict) -> Dict:
    """Step 6: Generate final investigation report."""
    from api.tasks.investigation_tasks import generate_investigation_report

    result = generate_investigation_report(investigation_id)
    if result.get('status') == 'error':
        raise RuntimeError(f"Report failed: {result.get('message')}")

    report = result.get('report', {})

    # Enrich with assessment data
    assessment = state['steps'].get('assess', {}).get('result', {})
    report['risk_assessment'] = {
        'risk_score': assessment.get('risk_score', 0),
        'risk_label': assessment.get('risk_label', 'UNKNOWN'),
        'indicators': assessment.get('indicators', {}),
    }

    # ML classification summary
    classify_result = state['steps'].get('classify', {}).get('result', {})
    report['classification_summary'] = {
        'wallets_classified': classify_result.get('wallets_classified', 0),
        'by_type': classify_result.get('by_type', {}),
        'by_source': classify_result.get('by_source', {}),
    }

    return {
        'report': report,
        'message': f"Report complete: {report.get('summary', {}).get('total_wallets', 0)} wallets analysed",
    }


# ── Main pipeline orchestrator ──────────────────────────────────────────

STEP_EXECUTORS = {
    'import': _step_import,
    'trace': _step_trace,
    'expand': _step_expand,
    'classify': _step_classify,
    'assess': _step_assess,
    'report': _step_report,
}


def run_investigation_skill(case_id: str, max_depth: int = 3, max_wallets: int = 100) -> Dict:
    """
    Execute the full AML investigation pipeline for a case.
    
    Called by Celery task — progress saved to Redis at each step
    so the frontend can poll for live updates.
    """
    from utils.database import get_session_factory

    SessionFactory = get_session_factory()
    session = SessionFactory()
    state = _make_state(case_id)
    state['status'] = 'running'
    state['started_at'] = datetime.now(timezone.utc).isoformat()
    save_skill_progress(case_id, state)

    investigation_id = None

    try:
        for step_def in SKILL_STEPS:
            step_id = step_def['id']
            state['current_step'] = step_id
            state['steps'][step_id]['status'] = 'running'
            state['steps'][step_id]['started_at'] = datetime.now(timezone.utc).isoformat()
            save_skill_progress(case_id, state)

            start_time = time.time()
            logger.info(f"[SKILL] Case {case_id} — step '{step_id}' started")

            try:
                # Route to the correct executor
                if step_id == 'import':
                    result = _step_import(session, case_id, state)
                    investigation_id = result['investigation_id']
                    state['investigation_id'] = investigation_id
                elif step_id == 'expand':
                    result = _step_expand(session, investigation_id, state,
                                          max_depth=max_depth, max_wallets=max_wallets)
                else:
                    executor = STEP_EXECUTORS[step_id]
                    result = executor(session, investigation_id, state)

                elapsed = round(time.time() - start_time, 1)
                state['steps'][step_id]['status'] = 'completed'
                state['steps'][step_id]['result'] = result
                state['steps'][step_id]['completed_at'] = datetime.now(timezone.utc).isoformat()
                state['steps'][step_id]['elapsed_seconds'] = elapsed

                logger.info(f"[SKILL] Case {case_id} — step '{step_id}' completed in {elapsed}s")
                save_skill_progress(case_id, state)

            except Exception as step_err:
                elapsed = round(time.time() - start_time, 1)
                state['steps'][step_id]['status'] = 'failed'
                state['steps'][step_id]['error'] = str(step_err)
                state['steps'][step_id]['elapsed_seconds'] = elapsed
                logger.error(f"[SKILL] Case {case_id} — step '{step_id}' failed: {step_err}", exc_info=True)
                save_skill_progress(case_id, state)
                # Continue to next steps rather than aborting entirely
                # (e.g. classify might still work even if expand partially fails)
                continue

        # Build high-level findings
        state['findings'] = _build_findings(state)
        state['status'] = 'completed'
        state['completed_at'] = datetime.now(timezone.utc).isoformat()
        save_skill_progress(case_id, state)

        logger.info(f"[SKILL] Case {case_id} — investigation skill COMPLETED")
        return state

    except Exception as e:
        state['status'] = 'failed'
        state['error'] = str(e)
        state['completed_at'] = datetime.now(timezone.utc).isoformat()
        save_skill_progress(case_id, state)
        logger.error(f"[SKILL] Case {case_id} — pipeline failed: {e}", exc_info=True)
        return state
    finally:
        session.close()


def _build_findings(state: Dict) -> Dict:
    """Distill step results into a clean findings summary."""
    findings = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'case_id': state['case_id'],
        'investigation_id': state.get('investigation_id'),
    }

    # From import step
    import_r = state['steps']['import'].get('result', {})
    findings['seed_wallets'] = import_r.get('wallets_imported', 0)
    findings['chains'] = import_r.get('chains', [])

    # From trace step
    trace_r = state['steps']['trace'].get('result', {})
    findings['transfers_fetched'] = trace_r.get('transfers_added', 0)

    # From expand step
    expand_r = state['steps']['expand'].get('result', {})
    findings['wallets_discovered'] = expand_r.get('new_wallets_discovered', 0)
    findings['total_wallets'] = expand_r.get('total_wallets', 0)
    findings['trace_depth'] = expand_r.get('iterations', 0)

    # From classify step
    classify_r = state['steps']['classify'].get('result', {})
    findings['classification'] = classify_r.get('by_type', {})
    findings['ml_source_breakdown'] = classify_r.get('by_source', {})

    # From assess step
    assess_r = state['steps']['assess'].get('result', {})
    findings['risk_score'] = assess_r.get('risk_score', 0)
    findings['risk_label'] = assess_r.get('risk_label', 'UNKNOWN')
    findings['exchange_count'] = assess_r.get('indicators', {}).get('exchange_endpoints', 0)
    findings['mixer_count'] = assess_r.get('indicators', {}).get('mixer_interactions', 0)
    findings['bridge_count'] = assess_r.get('indicators', {}).get('bridge_crossings', 0)

    # From report step
    report_r = state['steps']['report'].get('result', {})
    report = report_r.get('report', {})
    findings['flagged_wallets'] = report.get('summary', {}).get('flagged_wallets', 0)

    return findings
