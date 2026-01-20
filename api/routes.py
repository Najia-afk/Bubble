#routes.py
from celery_worker import celery_app
from flask import Blueprint, request, jsonify, g, render_template
from datetime import datetime
from api.tasks.tasks import fetch_erc20_transfer_history_task, fetch_token_price_history_task, fetch_last_token_price_history_task
from api.tasks.fetch_token_data_task import fetch_token_data_task
from api.tasks.tigergraph_tasks import sync_tokens_to_tigergraph, sync_ghst_transfers_24h, full_tigergraph_sync

api_bp = Blueprint('api', __name__)


# ============================================================================
# HEALTH CHECK
# ============================================================================

@api_bp.route("/health", methods=['GET'])
def health_check():
    """Health check endpoint for Docker"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "service": "bubble-api"
    }), 200


# ============================================================================
# FRONTEND ROUTES
# ============================================================================

@api_bp.route("/", methods=['GET'])
def index():
    """Main dashboard"""
    return render_template('dashboard.html')


@api_bp.route("/admin", methods=['GET'])
def admin():
    """Admin panel - Token Management"""
    return render_template('admin/token_management.html')


@api_bp.route("/visualize", methods=['GET'])
def visualize():
    """Visualization page"""
    return render_template('visualizations/transaction_flow.html')


# ============================================================================
# TOKEN MANAGEMENT ENDPOINTS
# ============================================================================

@api_bp.route("/tokens/add", methods=['POST'])
def add_token():
    """Add a new token and generate dynamic tables"""
    from scripts.src.fetch_erc20_info_coingecko import store_token_data_and_generate_tables
    
    data = request.get_json()
    
    contract_address = data.get('contract_address')
    blockchain = data.get('blockchain')
    trigram = data.get('trigram')
    
    if not all([contract_address, blockchain, trigram]):
        return jsonify({"error": "Missing required fields"}), 400
    
    try:
        # Use the original script to add token
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


@api_bp.route("/tokens/list", methods=['GET'])
def list_tokens():
    """List all registered tokens"""
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


@api_bp.route("/tokens/schedule_fetch", methods=['POST'])
def schedule_token_fetch():
    """Schedule fetch tasks for a token"""
    
    data = request.get_json()
    
    token_id = data.get('token_id')
    symbol = data.get('symbol')
    chains = data.get('chains', [])
    start_date = data.get('start_date')
    end_date = data.get('end_date')
    fetch_mode = data.get('fetch_mode', 'both')  # price_history, transfers, both
    
    if not all([symbol, chains, start_date]):
        return jsonify({"error": "Missing required fields"}), 400
    
    try:
        # Create task payload
        task_data = {
            "symbol": symbol,
            "chains": chains,
            "start_date": start_date,
            "end_date": end_date or datetime.now().strftime("%Y-%m-%d"),
            "fetch_mode": fetch_mode
        }
        
        # Submit to Celery
        task = fetch_token_data_task.delay(task_data)
        
        return jsonify({
            "message": "Fetch task scheduled",
            "task_id": task.id,
            "symbol": symbol,
            "chains": chains
        }), 202
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# TIGERGRAPH SYNC ENDPOINTS
# ============================================================================

@api_bp.route("/sync/tokens", methods=['POST'])
def trigger_token_sync():
    """Trigger token sync to TigerGraph"""
    task = sync_tokens_to_tigergraph.delay()
    return jsonify({
        "message": "Token sync task submitted",
        "task_id": task.id
    }), 202


@api_bp.route("/sync/ghst", methods=['POST'])
def trigger_ghst_sync():
    """Trigger GHST transfer sync for last 24h"""
    chains = request.json.get('chains', ['POL', 'BASE']) if request.is_json else ['POL', 'BASE']
    
    task = sync_ghst_transfers_24h.delay(token_symbol='GHST', chains=chains)
    return jsonify({
        "message": "GHST transfer sync task submitted",
        "task_id": task.id,
        "chains": chains
    }), 202


@api_bp.route("/sync/full", methods=['POST'])
def trigger_full_sync():
    """Trigger full TigerGraph sync"""
    task = full_tigergraph_sync.delay()
    return jsonify({
        "message": "Full sync task submitted",
        "task_id": task.id
    }), 202


# ============================================================================
# EXISTING ENDPOINTS
# ============================================================================

@api_bp.route("/get_token_price_history", methods=['GET'])
def get_token_price_history():
    symbols = request.args.get('symbols').split(',')
    start_date_str = request.args.get('startDate', None)
    end_date_str = request.args.get('endDate', None)

    if not symbols or not start_date_str or not end_date_str:
        return jsonify({"error": "Missing data. Please provide symbols, startDate, and endDate as query parameters."}), 400

    # Convert start and end dates from string to DateTime format or ensure they're in the correct string format
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").isoformat()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").isoformat()

    
    task = fetch_token_price_history_task.delay(symbols, start_date, end_date)

    # Immediately return the task ID for future status checks
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202

#http://localhost:9999/api/get_token_price_history?symbols=ghst,kek&startDate=2019-01-01&endDate=2025-01-31

@api_bp.route("/get_last_token_price_history", methods=['GET'])
def  get_last_token_price_history():
    symbols = request.args.get('symbols').split(',')
    if symbols is None:
        return jsonify({"error": "No symbols provided"}), 400

    
    # Enqueue the task
    task = fetch_last_token_price_history_task.delay(symbols)

    # Immediately return the task ID for future status checks
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202

#http://localhost:9999/api/get_last_token_price_history?symbols=ghst,kek

@api_bp.route("/get_erc20_transfer_history", methods=['GET', 'POST'])
def get_erc20_transfer_history():
    
    if request.method == 'POST' and request.is_json:
        trigrams_info = request.json
        if not trigrams_info:
            return jsonify({"error": "No data provided. Please provide a JSON payload with trigrams information."}), 400
    else:
        trigram = request.args.get('trigram', None)
        # Use a fallback empty string to ensure split() always works
        symbols_query = request.args.get('symbols', '')
        symbols = symbols_query.split(',') if symbols_query else []
        start_block = request.args.get('startBlock', type=int)
        end_block = request.args.get('endBlock', type=int)
        after = request.args.get('after', None)
        limit = request.args.get('limit', None)

        # Check for presence of each parameter individually for clearer error messaging
        missing_params = [param for param, value in [('trigram', trigram), ('symbols', symbols_query), ('startBlock', start_block), ('endBlock', end_block)] if not value]
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

    # Immediately return the task ID for future status checks
    return jsonify({"message": "Task submitted", "task_id": task.id}), 202


#http://localhost:9999/api/get_erc20_transfer_history?trigram=POL&symbols=ghst,gltr&startBlock=1&endBlock=999999999
# Example usage:
# [
#     {"trigram": "ETH", "symbols": ["DAI", "USDC"], "startBlock": 1000000, "endBlock": 2000000},
#     {"trigram": "BSC", "symbols": ["CAKE", "BNB"], "startBlock": 5000000, "endBlock": 6000000},
# ]
# 
@api_bp.route('/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    task = celery_app.AsyncResult(task_id)
    if task.state == 'PENDING':
        return jsonify({'state': task.state,'status': 'Pending...', 'result': task.result, 'task_id':task.task_id})
    elif task.state == 'SUCCESS':
        return jsonify({'state': task.state, 'result': task.result})
    elif task.state == 'FAILURE':
        return jsonify({'state': task.state, 'status': 'Task failed', 'error': str(task.info)})
    else:
        return jsonify({'state': task.state, 'status': 'Task is in progress'})
#http://localhost:9999/api/task_status/<task_id>

def init_api_routes(app):
    app.register_blueprint(api_bp, url_prefix='/api')
