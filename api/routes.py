#routes.py
from celery_worker import celery_app
from flask import Blueprint, request, jsonify, g, render_template
from datetime import datetime, timedelta
from sqlalchemy import text
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
# GRAPH DATA API FOR VISUALIZATION (uses GraphQL schema internally)
# ============================================================================

@api_bp.route("/graph/transfers", methods=['GET'])
def get_graph_transfers():
    """
    Get transfer data for visualization graph - returns vis.js compatible JSON.
    Internally uses the GraphQL schema to query data (no direct DB access).
    """
    chain = request.args.get('chain', 'POL').upper()
    symbol = request.args.get('symbol', 'ghst').lower()
    start_block = int(request.args.get('start_block', 1))
    end_block = int(request.args.get('end_block', 999999999))
    limit = int(request.args.get('limit', 500))
    
    try:
        # Use the GraphQL schema to execute query
        from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema
        
        query = '''
            query GetTransfers($trigram: String!, $symbols: [String]!, $startBlock: Int!, $endBlock: Int!, $limit: Int) {
                erc20TransferEvents(trigram: $trigram, symbols: $symbols, startBlock: $startBlock, endBlock: $endBlock, limit: $limit) {
                    edges {
                        node {
                            blockNumber
                            hash
                            fromContractAddress
                            toContractAddress
                            value
                            tokenSymbol
                            timestamp
                        }
                    }
                    pageInfo {
                        hasNextPage
                        endCursor
                    }
                }
            }
        '''
        
        result = schema.execute(
            query,
            variables={
                'trigram': chain,
                'symbols': [symbol],
                'startBlock': start_block,
                'endBlock': end_block,
                'limit': limit
            },
            context={'session': g.db_session}
        )
        
        if result.errors:
            return jsonify({
                "nodes": [],
                "edges": [],
                "stats": {"total_transfers": 0, "unique_wallets": 0, "total_volume": 0},
                "message": f"GraphQL errors: {[str(e) for e in result.errors]}"
            }), 200
        
        # Transform GraphQL response to vis.js format
        transfers = result.data.get('erc20TransferEvents', {}).get('edges', []) if result.data else []
        
        wallets = {}
        edges = []
        
        for i, edge in enumerate(transfers):
            tx = edge.get('node', {})
            from_addr = tx.get('fromContractAddress', '')
            to_addr = tx.get('toContractAddress', '')
            value = float(tx.get('value', 0)) / 1e18
            
            if not from_addr or not to_addr:
                continue
            
            # Create/update from node
            if from_addr not in wallets:
                wallets[from_addr] = {
                    'id': from_addr,
                    'label': f"{from_addr[:6]}...{from_addr[-4:]}",
                    'out_count': 0, 'in_count': 0,
                    'out_volume': 0, 'in_volume': 0
                }
            wallets[from_addr]['out_count'] += 1
            wallets[from_addr]['out_volume'] += value
            
            # Create/update to node
            if to_addr not in wallets:
                wallets[to_addr] = {
                    'id': to_addr,
                    'label': f"{to_addr[:6]}...{to_addr[-4:]}",
                    'out_count': 0, 'in_count': 0,
                    'out_volume': 0, 'in_volume': 0
                }
            wallets[to_addr]['in_count'] += 1
            wallets[to_addr]['in_volume'] += value
            
            edges.append({
                'id': i,
                'from': from_addr,
                'to': to_addr,
                'value': value,
                'title': f"{value:.2f} {symbol.upper()}<br>Block: {tx.get('blockNumber', 'N/A')}",
                'width': min(max(value / 100, 1), 8)
            })
        
        # Classify nodes
        nodes = []
        for addr, data in wallets.items():
            total_volume = data['out_volume'] + data['in_volume']
            total_txs = data['out_count'] + data['in_count']
            is_high_volume = total_volume > 10000
            is_contract = total_txs > 50 or (data['in_count'] > 20 and data['out_count'] < 5)
            
            nodes.append({
                'id': data['id'],
                'label': data['label'],
                'color': '#51cf66' if is_contract else '#ff6b6b' if is_high_volume else '#00d4ff',
                'size': 35 if is_contract else 30 if is_high_volume else 20,
                'title': f"Address: {addr}<br>In: {data['in_count']} txs ({data['in_volume']:.2f})<br>Out: {data['out_count']} txs ({data['out_volume']:.2f})"
            })
        
        total_volume = sum(e['value'] for e in edges)
        
        return jsonify({
            "nodes": nodes,
            "edges": edges,
            "stats": {
                "total_transfers": len(edges),
                "unique_wallets": len(nodes),
                "total_volume": round(total_volume, 2)
            }
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_bp.route("/stats/dashboard", methods=['GET'])
def get_dashboard_stats():
    """Get statistics for the dashboard via GraphQL schema"""
    try:
        from api.application.erc20models import Token
        session = g.db_session
        
        stats = {
            'tokens': session.query(Token).count(),
            'transfers': 0,
            'wallets': 0,
            'chains': ['POL', 'BASE', 'ETH']
        }
        
        # Use GraphQL to get transfer stats
        from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema
        
        query = '''
            query GetStats($trigram: String!, $symbols: [String]!, $startBlock: Int!, $endBlock: Int!, $limit: Int) {
                erc20TransferEvents(trigram: $trigram, symbols: $symbols, startBlock: $startBlock, endBlock: $endBlock, limit: $limit) {
                    edges {
                        node {
                            fromContractAddress
                            toContractAddress
                        }
                    }
                }
            }
        '''
        
        result = schema.execute(
            query,
            variables={
                'trigram': 'POL',
                'symbols': ['ghst'],
                'startBlock': 1,
                'endBlock': 999999999,
                'limit': 10000
            },
            context={'session': session}
        )
        
        if result.data and result.data.get('erc20TransferEvents'):
            edges = result.data['erc20TransferEvents'].get('edges', [])
            stats['transfers'] = len(edges)
            
            # Count unique wallets
            wallets = set()
            for edge in edges:
                node = edge.get('node', {})
                if node.get('fromContractAddress'):
                    wallets.add(node['fromContractAddress'])
                if node.get('toContractAddress'):
                    wallets.add(node['toContractAddress'])
            stats['wallets'] = len(wallets)
        
        return jsonify(stats), 200
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


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
