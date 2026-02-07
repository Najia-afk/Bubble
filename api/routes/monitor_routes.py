"""Real-time wallet monitoring and alert endpoints."""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta, timezone
from sqlalchemy import func, desc

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route("/monitor/suspects", methods=['GET'])
def get_suspect_wallets_for_monitoring():
    """Get all suspect wallets from investigations for monitoring."""
    from api.application.erc20models import (
        Investigation, InvestigationWallet, InvestigationTransfer, CHAIN_ID_TO_TRIGRAM
    )

    session = g.db_session
    attacker_roles = {'attacker', 'hacker', 'scammer', 'exploiter', 'thief', 'suspect'}

    wallets = session.query(InvestigationWallet).filter(
        func.lower(InvestigationWallet.role).in_(attacker_roles)
    ).all()

    result = []
    for w in wallets:
        chain_code = CHAIN_ID_TO_TRIGRAM.get(w.chain_id, 'ETH')

        investigation = session.query(Investigation).filter_by(id=w.investigation_id).first()
        inv_name = investigation.name if investigation else None

        last_out = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.from_address) == w.address.lower()
        ).order_by(desc(InvestigationTransfer.timestamp)).first()

        last_in = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.to_address) == w.address.lower()
        ).order_by(desc(InvestigationTransfer.timestamp)).first()

        outflows = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.from_address) == w.address.lower()
        ).all()

        total_out_value = sum(float(t.value or 0) for t in outflows)
        destinations = list(set(t.to_address for t in outflows if t.to_address))

        result.append({
            "address": w.address, "chain": chain_code, "role": w.role,
            "label": w.notes or '', "investigation_id": w.investigation_id,
            "investigation_name": inv_name,
            "last_out_tx": last_out.tx_hash if last_out else None,
            "last_out_time": last_out.timestamp.isoformat() if last_out and last_out.timestamp else None,
            "last_out_to": last_out.to_address if last_out else None,
            "last_out_value": float(last_out.value) if last_out and last_out.value else None,
            "last_out_token": last_out.token_symbol if last_out else None,
            "last_in_time": last_in.timestamp.isoformat() if last_in and last_in.timestamp else None,
            "total_outflows": len(outflows),
            "total_out_value": total_out_value,
            "unique_destinations": len(destinations)
        })

    result.sort(key=lambda x: x.get('last_out_time') or '', reverse=True)
    return jsonify({"suspects": result, "total": len(result)}), 200


@monitor_bp.route("/monitor/wallets", methods=['GET'])
def get_monitored_wallets():
    """Get list of monitored wallets."""
    from api.services.wallet_monitor import WalletMonitorService

    chain = request.args.get('chain')
    case_id = request.args.get('case_id')

    monitor = WalletMonitorService(g.db_session)
    wallets = monitor.get_wallets(chain=chain, case_id=case_id)

    return jsonify({
        "wallets": [
            {
                "address": w.address, "chain": w.chain_code,
                "case_id": w.case_id, "label": w.label,
                "added_at": w.added_at.isoformat() if w.added_at else None,
                "last_activity": w.last_activity.isoformat() if w.last_activity else None,
                "alert_count": w.alert_count or 0,
                "total_in": w.total_in_usd or 0,
                "total_out": w.total_out_usd or 0
            }
            for w in wallets
        ],
        "total": len(wallets)
    }), 200


@monitor_bp.route("/monitor/wallets", methods=['POST'])
def add_monitored_wallet():
    """Add a wallet to monitoring."""
    from api.services.wallet_monitor import WalletMonitorService

    data = request.get_json()
    if not data.get('address'):
        return jsonify({"error": "Missing required field: address"}), 400

    monitor = WalletMonitorService(g.db_session)
    wallet = monitor.add_wallet(
        address=data['address'],
        chain=data.get('chain', 'ETH'),
        case_id=data.get('case_id'),
        label=data.get('label', '')
    )
    g.db_session.commit()

    return jsonify({
        "message": "Wallet added to monitoring",
        "address": wallet.address,
        "chain": wallet.chain_code
    }), 201


@monitor_bp.route("/monitor/wallets/<address>", methods=['DELETE'])
def remove_monitored_wallet(address):
    """Remove a wallet from monitoring."""
    from api.services.wallet_monitor import WalletMonitorService

    chain = request.args.get('chain', 'ETH')
    monitor = WalletMonitorService(g.db_session)
    removed = monitor.remove_wallet(address, chain)

    if removed:
        g.db_session.commit()
        return jsonify({"message": "Wallet removed from monitoring"}), 200
    return jsonify({"error": "Wallet not found in monitoring"}), 404


@monitor_bp.route("/monitor/cases/<case_id>/start", methods=['POST'])
def start_case_monitoring(case_id):
    """Start monitoring all addresses from a case."""
    from api.tasks.monitor_tasks import start_case_monitoring as start_task

    task = start_task.delay(case_id)
    return jsonify({"message": "Case monitoring started", "task_id": task.id, "case_id": case_id}), 202


@monitor_bp.route("/monitor/alerts", methods=['GET'])
def get_alerts():
    """Get recent alerts."""
    from api.services.wallet_monitor import WalletMonitorService

    chain = request.args.get('chain')
    alert_type = request.args.get('type')
    hours = int(request.args.get('hours', 24))
    limit = int(request.args.get('limit', 100))

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    monitor = WalletMonitorService(g.db_session)
    alerts = monitor.get_alerts(chain=chain, alert_type=alert_type, since=since, limit=limit)

    return jsonify({"alerts": [monitor.to_dict(a) for a in alerts], "total": len(alerts)}), 200


@monitor_bp.route("/monitor/stats", methods=['GET'])
def get_monitor_stats():
    """Get monitoring statistics."""
    from api.services.wallet_monitor import WalletMonitorService

    monitor = WalletMonitorService(g.db_session)
    stats = monitor.get_stats()
    return jsonify(stats), 200


@monitor_bp.route("/monitor/check", methods=['POST'])
def trigger_activity_check():
    """Trigger manual activity check on monitored wallets."""
    from api.tasks.monitor_tasks import check_wallet_activity

    data = request.get_json() or {}
    chain = data.get('chain')

    task = check_wallet_activity.delay(chain=chain)
    return jsonify({"message": "Activity check started", "task_id": task.id, "chain": chain or "all"}), 202
