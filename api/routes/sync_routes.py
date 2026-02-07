"""TigerGraph sync endpoints."""

from flask import Blueprint, request, jsonify
from api.tasks.tigergraph_tasks import (
    sync_tokens_to_tigergraph,
    sync_token_transfers_24h,
    full_tigergraph_sync,
    sync_investigation_addresses,
)

sync_bp = Blueprint('sync', __name__)


@sync_bp.route("/sync/tokens", methods=['POST'])
def trigger_token_sync():
    """Trigger token sync to TigerGraph."""
    task = sync_tokens_to_tigergraph.delay()
    return jsonify({"message": "Token sync task submitted", "task_id": task.id}), 202


@sync_bp.route("/sync/transfers", methods=['POST'])
def trigger_transfer_sync():
    """Trigger token transfer sync for last 24h."""
    data = request.json if request.is_json else {}

    token_symbol = data.get('token_symbol', 'USDT')
    chains = data.get('chains', ['ETH', 'POL', 'BSC', 'BASE'])

    task = sync_token_transfers_24h.delay(token_symbol=token_symbol, chains=chains)
    return jsonify({
        "message": f"{token_symbol} transfer sync task submitted",
        "task_id": task.id,
        "token": token_symbol,
        "chains": chains
    }), 202


@sync_bp.route("/sync/investigation", methods=['POST'])
def trigger_investigation_sync():
    """Trigger sync for investigation case addresses."""
    data = request.json if request.is_json else {}
    case_id = data.get('case_id')

    task = sync_investigation_addresses.delay(case_id=case_id)
    return jsonify({
        "message": "Investigation address sync task submitted",
        "task_id": task.id,
        "case_id": case_id or "all"
    }), 202


@sync_bp.route("/sync/full", methods=['POST'])
def trigger_full_sync():
    """Trigger full TigerGraph sync."""
    task = full_tigergraph_sync.delay()
    return jsonify({"message": "Full sync task submitted", "task_id": task.id}), 202
