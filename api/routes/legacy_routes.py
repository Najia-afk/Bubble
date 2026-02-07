"""Legacy / original endpoints — token price/transfer history and task status."""

from flask import Blueprint, request, jsonify
from datetime import datetime
from celery_worker import celery_app
from api.tasks.tasks import (
    fetch_erc20_transfer_history_task,
    fetch_token_price_history_task,
    fetch_last_token_price_history_task,
)

legacy_bp = Blueprint('legacy', __name__)


@legacy_bp.route("/get_token_price_history", methods=['GET'])
def get_token_price_history():
    symbols = request.args.get('symbols').split(',')
    start_date_str = request.args.get('startDate', None)
    end_date_str = request.args.get('endDate', None)

    if not symbols or not start_date_str or not end_date_str:
        return jsonify({"error": "Missing data. Please provide symbols, startDate, and endDate as query parameters."}), 400

    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").isoformat()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").isoformat()

    task = fetch_token_price_history_task.delay(symbols, start_date, end_date)
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202


@legacy_bp.route("/get_last_token_price_history", methods=['GET'])
def get_last_token_price_history():
    symbols = request.args.get('symbols').split(',')
    if symbols is None:
        return jsonify({"error": "No symbols provided"}), 400

    task = fetch_last_token_price_history_task.delay(symbols)
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202


@legacy_bp.route("/get_erc20_transfer_history", methods=['GET', 'POST'])
def get_erc20_transfer_history():
    if request.method == 'POST' and request.is_json:
        trigrams_info = request.json
        if not trigrams_info:
            return jsonify({"error": "No data provided. Please provide a JSON payload with trigrams information."}), 400
    else:
        trigram = request.args.get('trigram', None)
        symbols_query = request.args.get('symbols', '')
        symbols = symbols_query.split(',') if symbols_query else []
        start_block = request.args.get('startBlock', type=int)
        end_block = request.args.get('endBlock', type=int)
        after = request.args.get('after', None)
        limit = request.args.get('limit', None)

        missing_params = [
            param for param, value in [
                ('trigram', trigram), ('symbols', symbols_query),
                ('startBlock', start_block), ('endBlock', end_block)
            ] if not value
        ]
        if missing_params:
            return jsonify({"error": f"Missing data. Please provide {' '.join(missing_params)} as query parameters."}), 400

        trigrams_info = [{
            "trigram": trigram,
            "symbols": symbols,
            "startBlock": start_block,
            "endBlock": end_block,
            "after": after,
            "limit": limit
        }]

    task = fetch_erc20_transfer_history_task.delay(trigrams_info)
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202


@legacy_bp.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = celery_app.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({'state': task.state, 'status': 'Pending...', 'result': task.result, 'task_id': task.task_id})
    elif task.state == 'SUCCESS':
        return jsonify({'state': task.state, 'result': task.result})
    elif task.state == 'FAILURE':
        return jsonify({'state': task.state, 'status': 'Task failed', 'error': str(task.info)})
    else:
        return jsonify({'state': task.state, 'status': 'Task is in progress'})
