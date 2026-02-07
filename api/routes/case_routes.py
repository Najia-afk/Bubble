"""Case management + AML Investigation Skill + chain endpoints."""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from sqlalchemy import func

case_bp = Blueprint('cases', __name__)


@case_bp.route("/cases", methods=['POST'])
def create_case():
    """Create a new case record with optional wallets."""
    from api.application.models import Case, CaseWallet

    data = request.get_json() or {}
    case_id = data.get('case_id')
    title = data.get('title')

    if not case_id or not title:
        return jsonify({"error": "Missing required fields: case_id, title"}), 400

    session = g.db_session
    existing = session.query(Case).filter_by(id=case_id).first()
    if existing:
        return jsonify({"error": "Case already exists", "case_id": case_id}), 409

    try:
        case = Case(
            id=case_id,
            title=title,
            source=data.get('source', 'osint'),
            status=data.get('status', 'active'),
            severity=data.get('severity', 'medium'),
            date_reported=datetime.fromisoformat(data['date_reported']) if data.get('date_reported') else None,
            date_incident=datetime.fromisoformat(data['date_incident']) if data.get('date_incident') else None,
            summary=data.get('summary'),
            total_stolen_usd=data.get('total_stolen_usd'),
            victim_count=data.get('victim_count'),
            attack_vector=data.get('attack_vector'),
            notes=data.get('notes')
        )
        session.add(case)
        session.flush()

        wallets = data.get('wallets', [])
        for w in wallets:
            if not w.get('address') or not w.get('chain_code'):
                continue
            session.add(CaseWallet(
                case_id=case_id,
                address=w['address'].lower(),
                chain_code=w['chain_code'].upper(),
                label=w.get('label'),
                role=w.get('role', 'related'),
                status=w.get('status'),
                notes=w.get('notes')
            ))

        session.commit()
        return jsonify({"message": "Case created", "case_id": case_id}), 201

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@case_bp.route("/cases", methods=['GET'])
def list_cases():
    """List all investigation cases from database — optimised with SQL aggregates."""
    from api.services.data_access import DataAccess
    from api.application.erc20models import Investigation, InvestigationWallet
    from sqlalchemy import func, case as sql_case

    try:
        session = g.db_session
        data = DataAccess(session)
        cases = data.get_cases()

        response_cases = []

        victim_roles = {'victim', 'theft_origin'}
        attacker_roles = {'attacker', 'hacker', 'scammer', 'exploiter', 'thief', 'suspect'}
        exchange_roles = {'exchange', 'cex', 'dex'}
        bridge_roles = {'bridge', 'cross_chain'}
        mixer_roles = {'mixer', 'tornado', 'tumbler', 'privacy'}

        inv_map = {}
        investigations = session.query(Investigation).all()
        for inv in investigations:
            inv_map[inv.name] = inv

        role_counts_q = (
            session.query(
                InvestigationWallet.investigation_id,
                InvestigationWallet.role,
                func.count().label('cnt')
            )
            .group_by(InvestigationWallet.investigation_id, InvestigationWallet.role)
            .all()
        )
        role_counts = {}
        for inv_id, role, cnt in role_counts_q:
            role_counts.setdefault(inv_id, {})[role or 'related'] = cnt

        for c in cases:
            investigation = None
            for inv_name, inv in inv_map.items():
                if c.id in inv_name or inv_name in (c.title or ''):
                    investigation = inv
                    break

            investigation_id = investigation.id if investigation else None

            victim_wallet_count = 0
            attacker_wallet_count = 0
            exchange_wallet_count = 0
            bridge_wallet_count = 0
            mixer_wallet_count = 0
            investigation_status = None
            investigation_wallet_count = 0
            investigation_token_count = 0
            investigation_reported_loss_usd = None

            if investigation:
                investigation_status = investigation.status
                investigation_wallet_count = sum(role_counts.get(investigation.id, {}).values())
                investigation_token_count = len(investigation.tokens)
                investigation_reported_loss_usd = investigation.reported_loss_usd

                rc = role_counts.get(investigation.id, {})
                for role, cnt in rc.items():
                    r = role.lower()
                    if r in victim_roles:
                        victim_wallet_count += cnt
                    elif r in attacker_roles:
                        attacker_wallet_count += cnt
                    elif r in exchange_roles:
                        exchange_wallet_count += cnt
                    elif r in bridge_roles:
                        bridge_wallet_count += cnt
                    elif r in mixer_roles:
                        mixer_wallet_count += cnt

            response_cases.append({
                "case_id": c.id,
                "title": c.title,
                "source": c.source,
                "status": c.status,
                "severity": c.severity,
                "date_reported": c.date_reported.isoformat() if c.date_reported else None,
                "summary": c.summary,
                "total_stolen_usd": c.total_stolen_usd,
                "estimated_loss_usd": investigation_reported_loss_usd,
                "victim_count": c.victim_count,
                "victim_wallet_count": victim_wallet_count,
                "attacker_wallet_count": attacker_wallet_count,
                "exchange_wallet_count": exchange_wallet_count,
                "bridge_wallet_count": bridge_wallet_count,
                "mixer_wallet_count": mixer_wallet_count,
                "attack_vector": c.attack_vector,
                "address_count": len(c.wallets),
                "mixer_deposit_count": len(c.mixer_deposits),
                "bridge_activity_count": len(c.bridge_activities),
                "chains_involved": sorted({w.chain_code for w in c.wallets if w.chain_code}),
                "investigation_id": investigation_id,
                "investigation_status": investigation_status,
                "investigation_wallet_count": investigation_wallet_count,
                "investigation_token_count": investigation_token_count,
                "investigation_reported_loss_usd": investigation_reported_loss_usd
            })

        return jsonify({"cases": response_cases, "total": len(cases)}), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@case_bp.route("/cases/<case_id>", methods=['GET'])
def get_case(case_id):
    """Get detailed case information."""
    from api.services.data_access import DataAccess

    try:
        data = DataAccess(g.db_session)
        case = data.get_case(case_id)

        if not case:
            return jsonify({"error": f"Case not found: {case_id}"}), 404

        all_addresses = [{
            "address": w.address, "chains": [w.chain_code],
            "label": w.label, "role": w.role, "status": w.status, "type": "evm"
        } for w in case.wallets]

        return jsonify({
            "case_id": case.id, "title": case.title, "source": case.source,
            "status": case.status, "severity": case.severity,
            "date_reported": case.date_reported.isoformat() if case.date_reported else None,
            "summary": case.summary, "total_stolen_usd": case.total_stolen_usd,
            "victim_count": case.victim_count, "attack_vector": case.attack_vector,
            "notes": case.notes, "theft_addresses": all_addresses,
            "mixer_deposits": [{"protocol": m.mixer_protocol, "amount": m.amount, "chain": m.chain_code} for m in case.mixer_deposits],
            "bridge_activity": [{"from_chain": b.from_chain, "to_chain": b.to_chain, "amount_usd": b.amount_usd} for b in case.bridge_activities]
        }), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@case_bp.route("/cases/<case_id>/import", methods=['POST'])
def import_case_to_investigation(case_id):
    """Import a case from DB into an Investigation record."""
    from api.services.data_access import DataAccess
    from api.application.erc20models import Investigation, InvestigationWallet, TRIGRAM_TO_CHAIN_ID

    try:
        data = DataAccess(g.db_session)
        case = data.get_case(case_id)

        if not case:
            return jsonify({"error": f"Case not found: {case_id}"}), 404

        session = g.db_session
        existing = session.query(Investigation).filter(
            Investigation.name.like(f"%{case.id}%")
        ).first()

        if existing:
            return jsonify({"error": "Case already imported", "investigation_id": existing.id}), 409

        investigation = Investigation(
            name=f"[{case.id}] {case.title}",
            description=f"Source: {case.source}\nAttack: {case.attack_vector}\n\n{case.notes or ''}",
            status='open',
            reported_loss_usd=case.total_stolen_usd,
            created_by=f"{case.source}_import"
        )
        session.add(investigation)
        session.flush()

        addresses_added = 0
        for wallet in case.wallets:
            chain_id = TRIGRAM_TO_CHAIN_ID.get(wallet.chain_code, 1)
            inv_wallet = InvestigationWallet(
                investigation_id=investigation.id,
                address=wallet.address.lower(),
                chain_id=chain_id,
                role=wallet.role or 'related',
                depth=0,
                notes=wallet.label
            )
            session.add(inv_wallet)
            addresses_added += 1

        session.commit()
        return jsonify({
            "message": "Case imported successfully",
            "investigation_id": investigation.id,
            "case_id": case.id,
            "addresses_added": addresses_added
        }), 201

    except Exception as e:
        g.db_session.rollback()
        return jsonify({"error": str(e)}), 500


# ── AML Investigation Skill ────────────────────────────────────────────

@case_bp.route("/cases/<case_id>/run-skill", methods=['POST'])
def run_case_skill(case_id):
    """Launch the AML Investigation Skill pipeline for a case."""
    from api.tasks.investigation_tasks import run_investigation_skill_task
    from api.services.investigation_skill import save_skill_progress, _make_state

    data = request.get_json() or {}
    max_depth = data.get('max_depth', 3)
    max_wallets = data.get('max_wallets', 100)

    state = _make_state(case_id)
    state['status'] = 'queued'
    state['started_at'] = datetime.now(timezone.utc).isoformat()
    save_skill_progress(case_id, state)

    task = run_investigation_skill_task.delay(
        case_id=case_id, max_depth=max_depth, max_wallets=max_wallets,
    )

    return jsonify({
        "message": "AML Investigation Skill launched",
        "task_id": task.id,
        "case_id": case_id,
        "max_depth": max_depth,
        "max_wallets": max_wallets,
    }), 202


@case_bp.route("/cases/<case_id>/skill-status", methods=['GET'])
def get_case_skill_status(case_id):
    """Poll the current progress of the AML Investigation Skill."""
    from api.services.investigation_skill import get_skill_progress, SKILL_STEPS

    state = get_skill_progress(case_id)
    if not state:
        return jsonify({
            "case_id": case_id,
            "status": "none",
            "message": "No skill run found for this case. Click 'Run Investigation' to start.",
            "steps": SKILL_STEPS,
        }), 200

    return jsonify(state), 200


@case_bp.route("/cases/theft-addresses", methods=['GET'])
def get_all_theft_addresses():
    """Get all theft addresses from all cases."""
    from api.services.data_access import DataAccess

    try:
        data = DataAccess(g.db_session)
        cases = data.get_cases()

        addresses = []
        for case in cases:
            for w in case.wallets:
                addresses.append({"address": w.address, "chain": w.chain_code, "case_id": case.id, "label": w.label})

        by_chain = {}
        for addr in addresses:
            chain = addr['chain'].upper()
            if chain not in by_chain:
                by_chain[chain] = []
            by_chain[chain].append(addr)

        return jsonify({"addresses": addresses, "by_chain": by_chain, "total": len(addresses)}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Chain management ────────────────────────────────────────────────────

@case_bp.route("/chains", methods=['GET'])
def list_chains():
    """List all supported chains."""
    from api.services.data_access import DataAccess

    try:
        data = DataAccess(g.db_session)
        chains = data.get_chains()
        return jsonify({
            "chains": [
                {"trigram": c.code, "name": c.name, "chain_id": c.chain_id, "native_token": c.native_token, "is_active": c.is_active}
                for c in chains
            ],
            "total": len(chains)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@case_bp.route("/chains/<trigram>", methods=['GET'])
def get_chain(trigram):
    """Get chain details."""
    from api.services.data_access import DataAccess

    try:
        data = DataAccess(g.db_session)
        chain = data.get_chain(trigram.upper())

        if not chain:
            return jsonify({"error": f"Chain not found: {trigram}"}), 404

        return jsonify({
            "trigram": chain.code, "name": chain.name, "chain_id": chain.chain_id,
            "native_token": chain.native_token, "explorer_name": chain.explorer_name,
            "explorer_api_url": chain.explorer_api_url, "is_active": chain.is_active
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
