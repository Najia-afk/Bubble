#routes.py
from celery_worker import celery_app
from flask import Blueprint, request, jsonify, g, render_template
from datetime import datetime, timedelta
from sqlalchemy import text
from api.tasks.tasks import fetch_erc20_transfer_history_task, fetch_token_price_history_task, fetch_last_token_price_history_task
from api.tasks.fetch_token_data_task import fetch_token_data_task
from api.tasks.tigergraph_tasks import sync_tokens_to_tigergraph, sync_ghst_transfers_24h, full_tigergraph_sync
from api.tasks.import_labels_task import import_labels_from_api, import_labels_for_address

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


@api_bp.route("/investigations", methods=['GET'])
def investigations_page():
    """Investigations list page"""
    return render_template('investigations.html')


@api_bp.route("/investigations/<int:investigation_id>", methods=['GET'])
def investigation_detail_page(investigation_id):
    """Investigation detail page"""
    return render_template('investigation_detail.html', investigation_id=investigation_id)


@api_bp.route("/classify", methods=['GET'])
def classify_page():
    """Wallet classification page with SHAP explainability"""
    return render_template('classify.html')


@api_bp.route("/models", methods=['GET'])
def models_page():
    """ML models management page"""
    return render_template('models.html')


@api_bp.route("/audit", methods=['GET'])
def audit_page():
    """Audit trail page for compliance"""
    return render_template('audit.html')


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
# WALLET LABELS ENDPOINTS
# ============================================================================

@api_bp.route("/labels/import", methods=['POST'])
def trigger_labels_import():
    """
    Trigger import of wallet labels from eth-labels API.
    Imports exchange, bridge, mixer, phishing labels for all supported chains.
    """
    data = request.get_json() if request.is_json else {}
    
    chain_ids = data.get('chain_ids')  # Optional: [1, 137, 56, 8453]
    label_types = data.get('label_types')  # Optional: ['exchange', 'bridge', 'mixer']
    
    task = import_labels_from_api.delay(chain_ids=chain_ids, label_types=label_types)
    
    return jsonify({
        "message": "Labels import task submitted",
        "task_id": task.id,
        "chain_ids": chain_ids or "all",
        "label_types": label_types or "default"
    }), 202


@api_bp.route("/labels/lookup/<address>", methods=['GET'])
def lookup_address_labels(address):
    """
    Look up labels for a specific address.
    First checks local DB, then optionally fetches from API if not found.
    """
    from api.application.erc20models import WalletLabel, CHAIN_ID_TO_TRIGRAM
    
    fetch_if_missing = request.args.get('fetch', 'false').lower() == 'true'
    
    try:
        session = g.db_session
        
        # Query local labels
        labels = session.query(WalletLabel).filter(
            WalletLabel.address == address.lower()
        ).all()
        
        if labels:
            return jsonify({
                "address": address,
                "labels": [
                    {
                        "id": label.id,
                        "chain_id": label.chain_id,
                        "chain": CHAIN_ID_TO_TRIGRAM.get(label.chain_id, 'UNKNOWN'),
                        "label": label.label,
                        "label_type": label.label_type,
                        "name_tag": label.name_tag,
                        "source": label.source,
                        "confidence": label.confidence,
                        "is_trusted": label.is_trusted,
                        "validated_by": label.validated_by,
                        "notes": label.notes
                    }
                    for label in labels
                ],
                "source": "database"
            }), 200
        
        # If not found and fetch requested, trigger API lookup
        if fetch_if_missing:
            task = import_labels_for_address.delay(address)
            return jsonify({
                "address": address,
                "labels": [],
                "message": "No local labels found. API lookup started.",
                "task_id": task.id,
                "source": "pending_api"
            }), 202
        
        return jsonify({
            "address": address,
            "labels": [],
            "source": "database"
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/labels/wallet/<address>", methods=['POST'])
def add_wallet_label(address):
    """
    Add a manual label to a wallet address.
    Used by analysts during investigations.
    """
    from api.application.erc20models import WalletLabel, TRIGRAM_TO_CHAIN_ID
    
    data = request.get_json()
    
    label = data.get('label')
    chain = data.get('chain', 'ETH').upper()  # Trigram: ETH, POL, BSC, BASE
    label_type = data.get('label_type')  # Optional: exchange, bridge, mixer, etc.
    name_tag = data.get('name_tag')
    notes = data.get('notes')
    is_trusted = data.get('is_trusted', False)
    validated_by = data.get('validated_by')
    
    if not label:
        return jsonify({"error": "Missing required field: label"}), 400
    
    chain_id = TRIGRAM_TO_CHAIN_ID.get(chain)
    if chain_id is None:
        return jsonify({"error": f"Unknown chain: {chain}. Use ETH, POL, BSC, or BASE"}), 400
    
    try:
        session = g.db_session
        
        # Check if exists
        existing = session.query(WalletLabel).filter_by(
            address=address.lower(),
            chain_id=chain_id,
            label=label
        ).first()
        
        if existing:
            # Update existing
            existing.label_type = label_type or existing.label_type
            existing.name_tag = name_tag or existing.name_tag
            existing.notes = notes or existing.notes
            existing.is_trusted = is_trusted
            existing.validated_by = validated_by
            existing.validated_at = datetime.utcnow() if is_trusted else existing.validated_at
            existing.updated_at = datetime.utcnow()
            session.commit()
            
            return jsonify({
                "message": "Label updated",
                "id": existing.id,
                "address": address.lower(),
                "label": label
            }), 200
        
        # Create new
        wallet_label = WalletLabel(
            address=address.lower(),
            chain_id=chain_id,
            label=label,
            label_type=label_type,
            name_tag=name_tag,
            source='manual',
            confidence=1.0,
            is_trusted=is_trusted,
            validated_by=validated_by,
            validated_at=datetime.utcnow() if is_trusted else None,
            notes=notes
        )
        session.add(wallet_label)
        session.commit()
        
        return jsonify({
            "message": "Label created",
            "id": wallet_label.id,
            "address": address.lower(),
            "label": label,
            "chain": chain
        }), 201
        
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/labels/wallet/<address>", methods=['DELETE'])
def delete_wallet_label(address):
    """Delete a label from a wallet address"""
    from api.application.erc20models import WalletLabel, TRIGRAM_TO_CHAIN_ID
    
    label = request.args.get('label')
    chain = request.args.get('chain', 'ETH').upper()
    
    if not label:
        return jsonify({"error": "Missing required parameter: label"}), 400
    
    chain_id = TRIGRAM_TO_CHAIN_ID.get(chain)
    if chain_id is None:
        return jsonify({"error": f"Unknown chain: {chain}"}), 400
    
    try:
        session = g.db_session
        
        deleted = session.query(WalletLabel).filter_by(
            address=address.lower(),
            chain_id=chain_id,
            label=label
        ).delete()
        
        session.commit()
        
        if deleted:
            return jsonify({
                "message": "Label deleted",
                "address": address.lower(),
                "label": label,
                "chain": chain
            }), 200
        else:
            return jsonify({"error": "Label not found"}), 404
            
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/labels/validate/<int:label_id>", methods=['POST'])
def validate_label(label_id):
    """Mark a label as trusted/validated by an analyst"""
    from api.application.erc20models import WalletLabel
    
    data = request.get_json() or {}
    validated_by = data.get('validated_by', 'analyst')
    is_trusted = data.get('is_trusted', True)
    notes = data.get('notes')
    
    try:
        session = g.db_session
        
        label = session.query(WalletLabel).filter_by(id=label_id).first()
        if not label:
            return jsonify({"error": "Label not found"}), 404
        
        label.is_trusted = is_trusted
        label.validated_by = validated_by
        label.validated_at = datetime.utcnow()
        if notes:
            label.notes = notes
        label.updated_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify({
            "message": "Label validated",
            "id": label_id,
            "is_trusted": is_trusted,
            "validated_by": validated_by
        }), 200
        
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/labels/types", methods=['GET'])
def list_label_types():
    """List all available label types"""
    from api.application.erc20models import LabelType
    
    try:
        session = g.db_session
        label_types = session.query(LabelType).order_by(LabelType.priority.desc()).all()
        
        return jsonify({
            "label_types": [
                {
                    "name": lt.name,
                    "description": lt.description,
                    "color": lt.color,
                    "priority": lt.priority
                }
                for lt in label_types
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/labels/stats", methods=['GET'])
def labels_stats():
    """Get statistics about wallet labels in the database"""
    from api.application.erc20models import WalletLabel, LabelType, KnownBridge, CHAIN_ID_TO_TRIGRAM
    from sqlalchemy import func
    
    try:
        session = g.db_session
        
        # Count by chain
        chain_counts = session.query(
            WalletLabel.chain_id,
            func.count(WalletLabel.id)
        ).group_by(WalletLabel.chain_id).all()
        
        # Count by label type
        type_counts = session.query(
            WalletLabel.label_type,
            func.count(WalletLabel.id)
        ).group_by(WalletLabel.label_type).all()
        
        # Count by source
        source_counts = session.query(
            WalletLabel.source,
            func.count(WalletLabel.id)
        ).group_by(WalletLabel.source).all()
        
        # Total counts
        total_labels = session.query(WalletLabel).count()
        trusted_labels = session.query(WalletLabel).filter_by(is_trusted=True).count()
        known_bridges = session.query(KnownBridge).count()
        
        return jsonify({
            "total_labels": total_labels,
            "trusted_labels": trusted_labels,
            "known_bridges": known_bridges,
            "by_chain": {
                CHAIN_ID_TO_TRIGRAM.get(chain_id, str(chain_id)): count
                for chain_id, count in chain_counts
            },
            "by_type": {
                label_type or 'unknown': count
                for label_type, count in type_counts
            },
            "by_source": {
                source: count
                for source, count in source_counts
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/bridges/list", methods=['GET'])
def list_known_bridges():
    """List all known bridge addresses"""
    from api.application.erc20models import KnownBridge, CHAIN_ID_TO_TRIGRAM
    
    try:
        session = g.db_session
        bridges = session.query(KnownBridge).filter_by(is_active=True).all()
        
        return jsonify({
            "bridges": [
                {
                    "address": bridge.address,
                    "chain_id": bridge.chain_id,
                    "chain": CHAIN_ID_TO_TRIGRAM.get(bridge.chain_id, 'UNKNOWN'),
                    "protocol": bridge.protocol,
                    "direction": bridge.direction,
                    "name": bridge.name
                }
                for bridge in bridges
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# INVESTIGATION ENDPOINTS (Forensic Case Management)
# ============================================================================

@api_bp.route("/investigations", methods=['GET'])
def list_investigations():
    """List all investigations"""
    from api.application.erc20models import Investigation
    
    try:
        session = g.db_session
        status_filter = request.args.get('status')
        
        query = session.query(Investigation)
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        investigations = query.order_by(Investigation.created_at.desc()).all()
        
        return jsonify({
            "investigations": [
                {
                    "id": inv.id,
                    "name": inv.name,
                    "status": inv.status,
                    "incident_date": inv.incident_date.isoformat() if inv.incident_date else None,
                    "reported_loss_usd": inv.reported_loss_usd,
                    "created_by": inv.created_by,
                    "assigned_to": inv.assigned_to,
                    "created_at": inv.created_at.isoformat() if inv.created_at else None,
                    "wallet_count": len(inv.wallets),
                    "token_count": len(inv.tokens)
                }
                for inv in investigations
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/investigations", methods=['POST'])
def create_investigation():
    """
    Create a new investigation case.
    
    Body:
    {
        "name": "Customer Hack 2026-01-25",
        "description": "Customer reports stolen GHST tokens",
        "incident_date": "2026-01-15T10:00:00",
        "reported_loss_usd": 50000,
        "created_by": "analyst",
        "victim_wallets": ["0x123...", "0x456..."],
        "tokens": [{"symbol": "GHST", "contract_address": "0x...", "chain": "POL", "stolen_amount": 10000}]
    }
    """
    from api.application.erc20models import Investigation, InvestigationWallet, InvestigationToken, WalletScore, TRIGRAM_TO_CHAIN_ID, Base
    
    data = request.get_json()
    
    if not data.get('name'):
        return jsonify({"error": "Missing required field: name"}), 400
    
    try:
        session = g.db_session
        
        # Ensure tables exist
        Base.metadata.create_all(session.get_bind(), tables=[
            Investigation.__table__, 
            InvestigationWallet.__table__,
            InvestigationToken.__table__,
            WalletScore.__table__
        ])
        
        # Parse incident date
        incident_date = None
        if data.get('incident_date'):
            try:
                incident_date = datetime.fromisoformat(data['incident_date'].replace('Z', '+00:00'))
            except:
                incident_date = datetime.utcnow()
        
        # Create investigation
        investigation = Investigation(
            name=data['name'],
            description=data.get('description'),
            status='open',
            incident_date=incident_date,
            reported_loss_usd=data.get('reported_loss_usd'),
            created_by=data.get('created_by', 'system'),
            assigned_to=data.get('assigned_to'),
            notes=data.get('notes')
        )
        session.add(investigation)
        session.flush()  # Get ID
        
        # Add victim wallets
        victim_wallets = data.get('victim_wallets', [])
        default_chain = data.get('default_chain', 'POL')
        
        for wallet_addr in victim_wallets:
            wallet = InvestigationWallet(
                investigation_id=investigation.id,
                address=wallet_addr.lower(),
                chain_id=TRIGRAM_TO_CHAIN_ID.get(default_chain.upper(), 137),
                role='victim',
                depth=0
            )
            session.add(wallet)
        
        # Add tracked tokens
        tokens = data.get('tokens', [])
        for token_data in tokens:
            token = InvestigationToken(
                investigation_id=investigation.id,
                contract_address=token_data.get('contract_address', '').lower(),
                chain_id=TRIGRAM_TO_CHAIN_ID.get(token_data.get('chain', 'POL').upper(), 137),
                symbol=token_data.get('symbol'),
                stolen_amount=token_data.get('stolen_amount')
            )
            session.add(token)
        
        session.commit()
        
        return jsonify({
            "message": "Investigation created",
            "id": investigation.id,
            "name": investigation.name,
            "victim_wallets_added": len(victim_wallets),
            "tokens_added": len(tokens)
        }), 201
        
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/investigations/<int:investigation_id>", methods=['GET'])
def get_investigation(investigation_id):
    """Get investigation details with all wallets and tokens"""
    from api.application.erc20models import Investigation, CHAIN_ID_TO_TRIGRAM
    
    try:
        session = g.db_session
        
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            return jsonify({"error": "Investigation not found"}), 404
        
        return jsonify({
            "id": investigation.id,
            "name": investigation.name,
            "description": investigation.description,
            "status": investigation.status,
            "incident_date": investigation.incident_date.isoformat() if investigation.incident_date else None,
            "reported_loss_usd": investigation.reported_loss_usd,
            "created_by": investigation.created_by,
            "assigned_to": investigation.assigned_to,
            "created_at": investigation.created_at.isoformat() if investigation.created_at else None,
            "updated_at": investigation.updated_at.isoformat() if investigation.updated_at else None,
            "notes": investigation.notes,
            "wallets": [
                {
                    "id": w.id,
                    "address": w.address,
                    "chain_id": w.chain_id,
                    "chain": CHAIN_ID_TO_TRIGRAM.get(w.chain_id, 'UNKNOWN'),
                    "role": w.role,
                    "depth": w.depth,
                    "parent_address": w.parent_address,
                    "total_received": w.total_received,
                    "total_sent": w.total_sent,
                    "is_flagged": w.is_flagged,
                    "notes": w.notes
                }
                for w in investigation.wallets
            ],
            "tokens": [
                {
                    "id": t.id,
                    "symbol": t.symbol,
                    "contract_address": t.contract_address,
                    "chain_id": t.chain_id,
                    "chain": CHAIN_ID_TO_TRIGRAM.get(t.chain_id, 'UNKNOWN'),
                    "stolen_amount": t.stolen_amount
                }
                for t in investigation.tokens
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/investigations/<int:investigation_id>/wallets", methods=['POST'])
def add_investigation_wallet(investigation_id):
    """Add a wallet to an investigation"""
    from api.application.erc20models import Investigation, InvestigationWallet, TRIGRAM_TO_CHAIN_ID
    
    data = request.get_json()
    
    if not data.get('address'):
        return jsonify({"error": "Missing required field: address"}), 400
    
    try:
        session = g.db_session
        
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            return jsonify({"error": "Investigation not found"}), 404
        
        chain = data.get('chain', 'POL').upper()
        chain_id = TRIGRAM_TO_CHAIN_ID.get(chain, 137)
        
        # Check if wallet already exists
        existing = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id,
            address=data['address'].lower(),
            chain_id=chain_id
        ).first()
        
        if existing:
            return jsonify({"error": "Wallet already in investigation", "wallet_id": existing.id}), 409
        
        wallet = InvestigationWallet(
            investigation_id=investigation_id,
            address=data['address'].lower(),
            chain_id=chain_id,
            role=data.get('role', 'related'),
            depth=data.get('depth', 0),
            parent_address=data.get('parent_address'),
            is_flagged=data.get('is_flagged', False),
            notes=data.get('notes')
        )
        session.add(wallet)
        session.commit()
        
        return jsonify({
            "message": "Wallet added",
            "id": wallet.id,
            "address": wallet.address,
            "role": wallet.role
        }), 201
        
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@api_bp.route("/investigations/<int:investigation_id>/expand", methods=['POST'])
def trigger_investigation_expand(investigation_id):
    """
    Trigger auto-expansion of investigation - follows fund flows from tracked wallets.
    """
    from api.tasks.investigation_tasks import expand_investigation
    
    data = request.get_json() or {}
    max_depth = data.get('max_depth', 3)
    max_wallets = data.get('max_wallets', 100)
    
    task = expand_investigation.delay(
        investigation_id=investigation_id,
        max_depth=max_depth,
        max_wallets=max_wallets
    )
    
    return jsonify({
        "message": "Expansion task submitted",
        "task_id": task.id,
        "investigation_id": investigation_id,
        "max_depth": max_depth,
        "max_wallets": max_wallets
    }), 202


@api_bp.route("/investigations/<int:investigation_id>/classify", methods=['POST'])
def trigger_investigation_classify(investigation_id):
    """
    Run ML classification on all wallets in the investigation.
    """
    from api.tasks.investigation_tasks import classify_investigation_wallets
    
    task = classify_investigation_wallets.delay(investigation_id=investigation_id)
    
    return jsonify({
        "message": "Classification task submitted",
        "task_id": task.id,
        "investigation_id": investigation_id
    }), 202


@api_bp.route("/investigations/<int:investigation_id>/report", methods=['GET'])
def get_investigation_report(investigation_id):
    """
    Get a summary report for an investigation.
    """
    from api.tasks.investigation_tasks import generate_investigation_report
    
    # Run synchronously for immediate response
    result = generate_investigation_report(investigation_id)
    
    if result.get('status') == 'error':
        return jsonify(result), 404
    
    return jsonify(result), 200


@api_bp.route("/investigations/<int:investigation_id>/status", methods=['PUT'])
def update_investigation_status(investigation_id):
    """Update investigation status"""
    from api.application.erc20models import Investigation
    
    data = request.get_json()
    new_status = data.get('status')
    
    if new_status not in ['open', 'in_progress', 'closed', 'archived']:
        return jsonify({"error": "Invalid status. Use: open, in_progress, closed, archived"}), 400
    
    try:
        session = g.db_session
        
        investigation = session.query(Investigation).filter_by(id=investigation_id).first()
        if not investigation:
            return jsonify({"error": "Investigation not found"}), 404
        
        investigation.status = new_status
        investigation.updated_at = datetime.utcnow()
        if new_status == 'closed':
            investigation.closed_at = datetime.utcnow()
        
        session.commit()
        
        return jsonify({
            "message": "Status updated",
            "id": investigation_id,
            "status": new_status
        }), 200
        
    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


# ============================================================================
# WALLET CLASSIFICATION ENDPOINTS (ML Scoring)
# ============================================================================

@api_bp.route("/wallets/<address>/classify", methods=['GET'])
def classify_wallet(address):
    """
    Classify a wallet using ML and heuristics.
    Returns predicted type (exchange, bridge, whale, etc.) with confidence score.
    """
    from api.services.wallet_classifier import get_wallet_classifier
    
    chain = request.args.get('chain', 'POL').upper()
    
    try:
        classifier = get_wallet_classifier()
        result = classifier.classify(address, chain, save_result=True)
        
        return jsonify(result), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/wallets/<address>/similar", methods=['GET'])
def find_similar_wallets(address):
    """Find wallets with similar behavior patterns"""
    from api.services.wallet_classifier import get_wallet_classifier
    
    chain = request.args.get('chain', 'POL').upper()
    limit = int(request.args.get('limit', 10))
    
    try:
        classifier = get_wallet_classifier()
        similar = classifier.find_similar_wallets(address, chain, limit)
        
        return jsonify({
            "address": address,
            "chain": chain,
            "similar_wallets": similar
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/wallets/batch-classify", methods=['POST'])
def batch_classify_wallets():
    """Classify multiple wallets at once"""
    from api.services.wallet_classifier import get_wallet_classifier
    
    data = request.get_json()
    addresses = data.get('addresses', [])
    chain = data.get('chain', 'POL').upper()
    
    if not addresses:
        return jsonify({"error": "No addresses provided"}), 400
    
    if len(addresses) > 50:
        return jsonify({"error": "Maximum 50 addresses per request"}), 400
    
    try:
        classifier = get_wallet_classifier()
        results = classifier.batch_classify(addresses, chain)
        
        return jsonify({
            "chain": chain,
            "results": results
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/scores/stats", methods=['GET'])
def get_wallet_scores_stats():
    """Get statistics about wallet classifications"""
    from api.application.erc20models import WalletScore, CHAIN_ID_TO_TRIGRAM
    from sqlalchemy import func
    
    try:
        session = g.db_session
        
        # Count by predicted type
        type_counts = session.query(
            WalletScore.predicted_type,
            func.count(WalletScore.id)
        ).group_by(WalletScore.predicted_type).all()
        
        # Count anomalies
        anomaly_count = session.query(WalletScore).filter_by(is_anomaly=True).count()
        
        # Total scored
        total_scored = session.query(WalletScore).count()
        
        return jsonify({
            "total_scored": total_scored,
            "anomalies": anomaly_count,
            "by_type": {
                ptype or 'unknown': count
                for ptype, count in type_counts
            }
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# ML TRAINING AND MODEL MANAGEMENT ENDPOINTS
# ============================================================================

@api_bp.route("/ml/stats", methods=['GET'])
def get_ml_stats():
    """Get ML model statistics"""
    from api.application.erc20models import ModelMetadata, AuditLog
    from sqlalchemy import func
    
    try:
        session = g.db_session
        
        # Count models
        total_models = session.query(ModelMetadata).count()
        production_models = session.query(ModelMetadata).filter_by(is_production=True).count()
        
        # Get average accuracy from latest models
        latest = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).limit(5).all()
        avg_accuracy = sum(m.accuracy or 0 for m in latest) / len(latest) if latest else 0
        
        # Get last trained
        last = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).first()
        last_trained = last.created_at.strftime('%Y-%m-%d') if last else 'Never'
        
        # Check for drift alerts
        drift_status = 'OK'
        if last and last.drift_detected:
            drift_status = 'DRIFT'
        
        return jsonify({
            "total_models": total_models,
            "production_models": production_models,
            "avg_accuracy": avg_accuracy,
            "last_trained": last_trained,
            "drift_status": drift_status
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ml/models", methods=['GET'])
def get_ml_models():
    """Get list of registered models"""
    from api.application.erc20models import ModelMetadata
    
    try:
        session = g.db_session
        models = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).all()
        
        return jsonify([
            {
                "id": m.id,
                "name": m.model_name,
                "version": m.version,
                "stage": 'Production' if m.is_production else 'Staging' if m.is_validated else 'None',
                "accuracy": m.accuracy,
                "f1_score": m.f1_score,
                "created": m.created_at.isoformat() if m.created_at else None,
                "run_id": m.mlflow_run_id
            }
            for m in models
        ]), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ml/train", methods=['POST'])
def train_ml_model():
    """Train a new ML model"""
    from api.tasks.ml_tasks import train_wallet_classifier
    
    data = request.get_json() or {}
    
    model_type = data.get('model_type', 'xgboost')
    chain = data.get('chain')
    token = data.get('token')
    test_size = data.get('test_size', 0.2)
    use_smote = data.get('use_smote', True)
    
    # Submit async task
    task = train_wallet_classifier.delay(
        model_type=model_type,
        chain=chain,
        token=token,
        test_size=test_size,
        use_smote=use_smote
    )
    
    return jsonify({
        "message": "Training task submitted",
        "task_id": task.id
    }), 202


@api_bp.route("/ml/check-drift", methods=['POST'])
def check_model_drift():
    """Check for data drift"""
    from api.tasks.ml_tasks import check_model_drift as drift_task
    
    task = drift_task.delay()
    
    return jsonify({
        "message": "Drift check submitted",
        "task_id": task.id
    }), 202


@api_bp.route("/ml/drift", methods=['GET'])
def get_drift_status():
    """Get latest drift detection results"""
    from api.application.erc20models import ModelMetadata
    
    try:
        session = g.db_session
        
        # Get production model
        prod = session.query(ModelMetadata).filter_by(is_production=True).first()
        
        if not prod:
            return jsonify({"error": "No production model found"}), 404
        
        return jsonify({
            "drift_detected": prod.drift_detected or False,
            "drift_score": prod.drift_score or 0.0,
            "last_checked": prod.last_drift_check.isoformat() if prod.last_drift_check else None,
            "model_name": prod.model_name,
            "version": prod.version
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ml/promote", methods=['POST'])
def promote_ml_model():
    """Promote a model to a new stage"""
    from api.tasks.ml_tasks import promote_model_to_production
    
    data = request.get_json()
    
    model_name = data.get('model_name')
    version = data.get('version')
    stage = data.get('stage', 'Production')
    
    if not model_name or not version:
        return jsonify({"error": "model_name and version required"}), 400
    
    task = promote_model_to_production.delay(model_name, version, stage)
    
    return jsonify({
        "message": "Promotion task submitted",
        "task_id": task.id
    }), 202


@api_bp.route("/ml/experiments", methods=['GET'])
def get_ml_experiments():
    """Get list of MLflow experiments/runs"""
    from api.application.erc20models import ModelMetadata
    
    try:
        session = g.db_session
        runs = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).limit(20).all()
        
        return jsonify([
            {
                "run_id": r.mlflow_run_id,
                "run_name": r.model_name,
                "model_type": r.model_type,
                "accuracy": r.accuracy,
                "f1_score": r.f1_score,
                "precision": r.precision,
                "recall": r.recall,
                "n_samples": r.n_samples,
                "start_time": r.created_at.isoformat() if r.created_at else None
            }
            for r in runs
        ]), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/ml/feature-importance", methods=['GET'])
def get_feature_importance():
    """Get SHAP feature importance from production model"""
    from api.application.erc20models import ModelMetadata
    import json
    
    try:
        session = g.db_session
        
        prod = session.query(ModelMetadata).filter_by(is_production=True).first()
        
        if not prod or not prod.shap_importance:
            return jsonify({"error": "No production model with SHAP importance"}), 404
        
        importance = json.loads(prod.shap_importance) if isinstance(prod.shap_importance, str) else prod.shap_importance
        
        return jsonify({
            "model_name": prod.model_name,
            "version": prod.version,
            "importance": importance
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============================================================================
# AUDIT TRAIL ENDPOINTS
# ============================================================================

@api_bp.route("/audit/stats", methods=['GET'])
def get_audit_stats():
    """Get audit log statistics"""
    from api.application.erc20models import AuditLog
    from sqlalchemy import func
    
    try:
        session = g.db_session
        
        # Count by action type
        counts = session.query(
            AuditLog.action_type,
            func.count(AuditLog.id)
        ).group_by(AuditLog.action_type).all()
        
        result = {
            "classifications": 0,
            "investigations": 0,
            "validations": 0,
            "model_actions": 0,
            "alerts": 0
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


@api_bp.route("/audit", methods=['GET'])
def get_audit_logs():
    """Get audit logs with filtering and pagination"""
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
            "total": total,
            "page": page,
            "page_size": page_size,
            "logs": [
                {
                    "id": log.id,
                    "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                    "action_type": log.action_type,
                    "user_id": log.user_id,
                    "investigation_id": log.investigation_id,
                    "wallet_address": log.wallet_address,
                    "predicted_type": log.predicted_type,
                    "confidence": log.confidence,
                    "validation_status": log.validation_status,
                    "model_version": log.model_version,
                    "notes": log.notes
                }
                for log in logs
            ]
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/audit/<int:log_id>", methods=['GET'])
def get_audit_log_detail(log_id):
    """Get detailed audit log entry"""
    from api.application.erc20models import AuditLog
    
    try:
        session = g.db_session
        
        log = session.query(AuditLog).filter_by(id=log_id).first()
        
        if not log:
            return jsonify({"error": "Audit log not found"}), 404
        
        return jsonify({
            "id": log.id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "action_type": log.action_type,
            "user_id": log.user_id,
            "investigation_id": log.investigation_id,
            "wallet_address": log.wallet_address,
            "chain_id": log.chain_id,
            "predicted_type": log.predicted_type,
            "confidence": log.confidence,
            "model_version": log.model_version,
            "mlflow_run_id": log.mlflow_run_id,
            "shap_values": log.shap_values,
            "validation_status": log.validation_status,
            "validated_by": log.validated_by,
            "validated_at": log.validated_at.isoformat() if log.validated_at else None,
            "notes": log.notes
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/audit/export", methods=['GET'])
def export_audit_logs():
    """Export audit logs as CSV or JSON"""
    from api.application.erc20models import AuditLog
    import csv
    import io
    from flask import Response
    
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
                    log.action_type,
                    log.user_id,
                    log.wallet_address,
                    log.predicted_type,
                    log.confidence,
                    log.validation_status,
                    log.model_version,
                    log.notes
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
                        "action_type": log.action_type,
                        "user_id": log.user_id,
                        "wallet_address": log.wallet_address,
                        "predicted_type": log.predicted_type,
                        "confidence": log.confidence,
                        "validation_status": log.validation_status,
                        "model_version": log.model_version,
                        "notes": log.notes
                    }
                    for log in logs
                ]
            }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
