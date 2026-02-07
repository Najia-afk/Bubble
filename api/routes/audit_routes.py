"""Audit trail endpoints — logs, stats, export."""

from flask import Blueprint, request, jsonify, g, Response
from datetime import datetime
from sqlalchemy import func

audit_bp = Blueprint('audit', __name__)


@audit_bp.route("/audit/stats", methods=['GET'])
def get_audit_stats():
    """Get audit log statistics."""
    from api.application.erc20models import AuditLog

    try:
        session = g.db_session

        counts = session.query(
            AuditLog.action_type, func.count(AuditLog.id)
        ).group_by(AuditLog.action_type).all()

        result = {
            "classifications": 0, "investigations": 0,
            "validations": 0, "model_actions": 0, "alerts": 0
        }

        for action_type, count in counts:
            if action_type == 'classification':
                result['classifications'] = count
            elif action_type == 'investigation':
                result['investigations'] = count
            elif action_type == 'validation':
                result['validations'] = count
            elif action_type == 'model':
                result['model_actions'] = count
            elif action_type == 'alert':
                result['alerts'] = count

        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@audit_bp.route("/audit", methods=['GET'])
def get_audit_logs():
    """Get audit logs with filtering and pagination."""
    from api.application.erc20models import AuditLog

    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))
    action_type = request.args.get('action_type')
    validation_status = request.args.get('validation_status')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    investigation_id = request.args.get('investigation_id')
    wallet_address = request.args.get('wallet_address')

    try:
        session = g.db_session
        query = session.query(AuditLog)

        if action_type:
            query = query.filter_by(action_type=action_type)
        if validation_status:
            query = query.filter_by(validation_status=validation_status)
        if investigation_id:
            query = query.filter_by(investigation_id=int(investigation_id))
        if wallet_address:
            query = query.filter(AuditLog.wallet_address.ilike(f'%{wallet_address}%'))
        if date_from:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(date_to))

        total = query.count()
        logs = query.order_by(AuditLog.timestamp.desc()).offset((page - 1) * page_size).limit(page_size).all()

        return jsonify({
            "total": total, "page": page, "page_size": page_size,
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "action_type": log.action_type, "user_id": log.user_id,
                    "investigation_id": log.investigation_id,
                    "wallet_address": log.wallet_address,
                    "predicted_type": log.predicted_type,
                    "confidence": log.confidence,
                    "validation_status": log.validation_status,
                    "model_version": log.model_version, "notes": log.notes
                }
                for log in logs
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@audit_bp.route("/audit/<int:log_id>", methods=['GET'])
def get_audit_log_detail(log_id):
    """Get detailed audit log entry."""
    from api.application.erc20models import AuditLog

    try:
        session = g.db_session
        log = session.query(AuditLog).filter_by(id=log_id).first()

        if not log:
            return jsonify({"error": "Audit log not found"}), 404

        return jsonify({
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "action_type": log.action_type, "user_id": log.user_id,
            "investigation_id": log.investigation_id,
            "wallet_address": log.wallet_address, "chain_id": log.chain_id,
            "predicted_type": log.predicted_type, "confidence": log.confidence,
            "model_version": log.model_version, "mlflow_run_id": log.mlflow_run_id,
            "shap_values": log.shap_values, "validation_status": log.validation_status,
            "validated_by": log.validated_by,
            "validated_at": log.validated_at.isoformat() if log.validated_at else None,
            "notes": log.notes
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@audit_bp.route("/audit/export", methods=['GET'])
def export_audit_logs():
    """Export audit logs as CSV or JSON."""
    from api.application.erc20models import AuditLog
    import csv
    import io

    format_type = request.args.get('format', 'json')
    action_type = request.args.get('action_type')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    try:
        session = g.db_session
        query = session.query(AuditLog)

        if action_type:
            query = query.filter_by(action_type=action_type)
        if date_from:
            query = query.filter(AuditLog.timestamp >= datetime.fromisoformat(date_from))
        if date_to:
            query = query.filter(AuditLog.timestamp <= datetime.fromisoformat(date_to))

        logs = query.order_by(AuditLog.timestamp.desc()).limit(10000).all()

        if format_type == 'csv':
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(['ID', 'Timestamp', 'Action', 'User', 'Wallet', 'Prediction', 'Confidence', 'Validation', 'Model', 'Notes'])

            for log in logs:
                writer.writerow([
                    log.id,
                    log.timestamp.isoformat() if log.timestamp else '',
                    log.action_type, log.user_id, log.wallet_address,
                    log.predicted_type, log.confidence, log.validation_status,
                    log.model_version, log.notes
                ])

            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=audit_log.csv'}
            )

        else:
            return jsonify({
                "logs": [
                    {
                        "id": log.id,
                        "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                        "action_type": log.action_type, "user_id": log.user_id,
                        "wallet_address": log.wallet_address,
                        "predicted_type": log.predicted_type,
                        "confidence": log.confidence,
                        "validation_status": log.validation_status,
                        "model_version": log.model_version, "notes": log.notes
                    }
                    for log in logs
                ]
            }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
