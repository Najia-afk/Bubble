"""Token management endpoints — CRUD and fetch scheduling."""

from flask import Blueprint, request, jsonify, g
from datetime import datetime

token_bp = Blueprint('tokens', __name__)


@token_bp.route("/tokens/add", methods=['POST'])
def add_token():
    """Add a new token and generate dynamic tables."""
    from scripts.src.fetch_erc20_info_coingecko import store_token_data_and_generate_tables

    data = request.get_json()

    contract_address = data.get('contract_address')
    blockchain = data.get('blockchain')
    trigram = data.get('trigram')

    if not all([contract_address, blockchain, trigram]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        store_token_data_and_generate_tables(
            blockchain=blockchain,
            contract_addresses=[contract_address],
            trigram=trigram
        )
        return jsonify({
            "message": "Token added successfully",
            "contract_address": contract_address,
            "trigram": trigram
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@token_bp.route("/tokens/manual", methods=['POST'])
def add_token_manual():
    """Add a token directly without external lookup."""
    from api.application.erc20models import Token

    data = request.get_json() or {}
    symbol = data.get('symbol')
    name = data.get('name')
    contract_address = data.get('contract_address')
    trigram = data.get('trigram')
    asset_platform_id = data.get('asset_platform_id')

    if not all([symbol, name, contract_address, trigram, asset_platform_id]):
        return jsonify({"error": "Missing required fields"}), 400

    session = g.db_session
    existing = session.query(Token).filter_by(contract_address=contract_address).first()
    if existing:
        return jsonify({"message": "Token already exists", "contract_address": contract_address}), 200

    token = Token(
        symbol=symbol,
        name=name,
        contract_address=contract_address,
        asset_platform_id=asset_platform_id,
        trigram=trigram
    )
    session.add(token)
    session.commit()

    return jsonify({
        "message": "Token added",
        "contract_address": contract_address,
        "trigram": trigram
    }), 201


@token_bp.route("/tokens/list", methods=['GET'])
def list_tokens():
    """List all registered tokens."""
    from api.application.erc20models import Token

    try:
        session = g.db_session
        tokens = session.query(Token).all()

        return jsonify({
            "tokens": [
                {
                    "id": token.id,
                    "symbol": token.symbol,
                    "name": token.name,
                    "contract_address": token.contract_address,
                    "trigram": token.trigram,
                    "asset_platform_id": token.asset_platform_id,
                    "history_tag": token.history_tag,
                    "transfert_erc20_tag": token.transfert_erc20_tag
                }
                for token in tokens
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@token_bp.route("/tokens/schedule_fetch", methods=['POST'])
def schedule_token_fetch():
    """Schedule fetch tasks for a token."""
    from api.tasks.fetch_token_data_task import fetch_token_data_task

    data = request.get_json()

    symbol = data.get('symbol')
    chains = data.get('chains', [])
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    fetch_mode = data.get('fetch_mode', 'both')

    if not all([symbol, chains, start_date]):
        return jsonify({"error": "Missing required fields"}), 400

    try:
        task_data = {
            "symbol": symbol,
            "chains": chains,
            "start_date": start_date,
            "end_date": end_date or datetime.now().strftime("%Y-%m-%d"),
            "fetch_mode": fetch_mode
        }

        task = fetch_token_data_task.delay(task_data)

        return jsonify({
            "message": "Fetch task scheduled",
            "task_id": task.id,
            "symbol": symbol,
            "chains": chains
        }), 202

    except Exception as e:
        return jsonify({"error": str(e)}), 500
