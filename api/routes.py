#routes.py
from celery_worker import celery_app
from flask import Blueprint, request, jsonify, g
from datetime import datetime, timedelta
from sqlalchemy import text
from api.tasks.tasks import fetch_erc20_transfer_history_task, fetch_token_price_history_task, fetch_last_token_price_history_task
from api.tasks.fetch_token_data_task import fetch_token_data_task
from api.tasks.tigergraph_tasks import sync_tokens_to_tigergraph, sync_token_transfers_24h, full_tigergraph_sync, sync_investigation_addresses
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
    """
    Get statistics for the dashboard - generalized for any token.
    Returns aggregate stats across all registered tokens and chains.
    """
    try:
        from api.application.erc20models import Token, Investigation, InvestigationWallet, InvestigationTransfer
        from api.services.data_access import DataAccess
        
        session = g.db_session
        data = DataAccess(session)
        
        # Get all chains from DB
        chains = data.get_chain_codes()
        
        stats = {
            'tokens': session.query(Token).count(),
            'transfers': 0,
            'wallets': 0,
            'chains': chains,
            'total_cases': 0,
            'active_cases': 0,
            'investigating_cases': 0,
            'total_investigations': 0,
            'investigation_wallets': 0,
            'investigation_transfers': 0,
            'estimated_loss_usd': 0
        }
        
        # Count cases from data source
        try:
            all_cases = data.get_cases()
            stats['total_cases'] = len(all_cases)
            stats['active_cases'] = len([c for c in all_cases if c.status == 'active'])
            stats['investigating_cases'] = len([c for c in all_cases if c.status == 'investigating'])
            
            # Sum estimated losses
            total_loss = sum(c.total_stolen_usd or 0 for c in all_cases)
            stats['estimated_loss_usd'] = total_loss
        except Exception:
            pass
        
        # Count investigations from DB
        try:
            stats['total_investigations'] = session.query(Investigation).count()
            stats['investigation_wallets'] = session.query(InvestigationWallet).count()
            stats['investigation_transfers'] = session.query(InvestigationTransfer).count()
        except Exception:
            pass
        
        # Try to get transfer stats from registered tokens
        tokens = session.query(Token).limit(10).all()  # Limit for performance
        
        all_wallets = set()
        total_transfers = 0
        
        for token in tokens:
            try:
                table_name = f"{token.symbol.lower()}_{token.trigram.lower()}_erc20_transfer_event"
                
                # Check if table exists
                check_query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = :table_name
                    )
                """)
                exists = session.execute(check_query, {'table_name': table_name}).scalar()
                
                if exists:
                    # Count transfers
                    count_query = text(f"SELECT COUNT(*) FROM {table_name} LIMIT 10000")
                    count = session.execute(count_query).scalar() or 0
                    total_transfers += min(count, 10000)  # Cap per table
                    
                    # Get unique wallets (sample)
                    wallet_query = text(f"""
                        SELECT DISTINCT from_contract_address FROM {table_name} LIMIT 1000
                        UNION
                        SELECT DISTINCT to_contract_address FROM {table_name} LIMIT 1000
                    """)
                    wallets = session.execute(wallet_query).fetchall()
                    all_wallets.update([w[0] for w in wallets if w[0]])
                    
            except Exception as e:
                continue  # Skip tables that don't exist or have issues
        
        stats['transfers'] = total_transfers
        stats['wallets'] = len(all_wallets)
        
        return jsonify(stats), 200
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


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


@api_bp.route("/tokens/manual", methods=['POST'])
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


@api_bp.route("/sync/transfers", methods=['POST'])
def trigger_transfer_sync():
    """
    Trigger token transfer sync for last 24h.
    Generalized endpoint - specify token and chains.
    """
    data = request.json if request.is_json else {}
    
    token_symbol = data.get('token_symbol', 'USDT')  # Default to USDT (most common)
    chains = data.get('chains', ['ETH', 'POL', 'BSC', 'BASE'])
    
    task = sync_token_transfers_24h.delay(token_symbol=token_symbol, chains=chains)
    return jsonify({
        "message": f"{token_symbol} transfer sync task submitted",
        "task_id": task.id,
        "token": token_symbol,
        "chains": chains
    }), 202


@api_bp.route("/sync/investigation", methods=['POST'])
def trigger_investigation_sync():
    """Trigger sync for investigation case addresses"""
    data = request.json if request.is_json else {}
    
    case_id = data.get('case_id')  # Optional - None syncs all
    
    task = sync_investigation_addresses.delay(case_id=case_id)
    return jsonify({
        "message": "Investigation address sync task submitted",
        "task_id": task.id,
        "case_id": case_id or "all"
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


@api_bp.route("/labels/categories", methods=['GET'])
def list_label_categories():
    """List label categories."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    categories = data.get_label_categories()
    
    return jsonify({
        "categories": [
            {
                "name": c.name,
                "description": c.description,
                "risk_level": c.risk_level,
                "color": c.color,
                "priority": c.priority
            }
            for c in categories
        ],
        "total": len(categories)
    }), 200


@api_bp.route("/tags/<address>", methods=['GET'])
def get_wallet_tags(address):
    """Get tags for a wallet."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    tags = data.get_wallet_tags(address, chain_code=chain)
    
    return jsonify({
        "address": address,
        "chain": chain,
        "tags": [
            {
                "id": t.id,
                "tag": t.tag,
                "chain": t.chain_code,
                "source": t.source,
                "confidence": t.confidence,
                "category": t.category.name if t.category else None,
                "risk_level": t.category.risk_level if t.category else None
            }
            for t in tags
        ],
        "total": len(tags)
    }), 200


@api_bp.route("/tags/<address>", methods=['POST'])
def add_wallet_tag(address):
    """Add tag to a wallet."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    body = request.get_json() or {}
    tag = body.get('tag')
    chain = (body.get('chain') or 'ETH').upper()
    source = body.get('source', 'manual')
    confidence = float(body.get('confidence', 1.0))
    
    if not tag:
        return jsonify({"error": "tag is required"}), 400
    
    wt = data.add_wallet_tag(address, chain, tag, source=source, confidence=confidence)
    g.db_session.commit()
    
    return jsonify({
        "id": wt.id,
        "address": wt.address,
        "chain": wt.chain_code,
        "tag": wt.tag,
        "source": wt.source,
        "confidence": wt.confidence
    }), 201


@api_bp.route("/mixers", methods=['GET'])
def list_mixers():
    """List known mixers."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    mixers = data.get_mixers(chain_code=chain)
    
    return jsonify({
        "mixers": [
            {
                "address": m.address,
                "chain": m.chain_code,
                "protocol": m.protocol,
                "name": m.name,
                "pool_size": m.pool_size
            }
            for m in mixers
        ],
        "total": len(mixers)
    }), 200


@api_bp.route("/bridges", methods=['GET'])
def list_bridges():
    """List known bridges."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    bridges = data.get_bridges(chain_code=chain)
    
    return jsonify({
        "bridges": [
            {
                "address": b.address,
                "chain": b.chain_code,
                "protocol": b.protocol,
                "name": b.name,
                "direction": b.direction
            }
            for b in bridges
        ],
        "total": len(bridges)
    }), 200


@api_bp.route("/check/<address>", methods=['GET'])
def check_address(address):
    """Check address risk profile using DB data."""
    from api.services.data_access import DataAccess
    
    data = DataAccess(g.db_session)
    chain = request.args.get('chain')
    is_mixer = data.is_mixer(address, chain_code=chain)
    is_bridge = data.is_bridge(address, chain_code=chain)
    tags = data.get_wallet_tags(address, chain_code=chain)
    risk_level = _get_risk_level(is_mixer, is_bridge, tags)
    
    return jsonify({
        "address": address,
        "chain": chain,
        "is_mixer": is_mixer,
        "is_bridge": is_bridge,
        "risk_level": risk_level,
        "tags": [
            {
                "tag": t.tag,
                "chain": t.chain_code,
                "source": t.source,
                "confidence": t.confidence,
                "category": t.category.name if t.category else None,
                "risk_level": t.category.risk_level if t.category else None
            }
            for t in tags
        ]
    }), 200


def _get_risk_level(is_mixer: bool, is_bridge: bool, tags: list) -> str:
    """Determine risk level based on flags and tags."""
    if is_mixer:
        return "high"
    
    level_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    tag_levels = [
        t.category.risk_level
        for t in tags
        if t.category and t.category.risk_level
    ]
    if tag_levels:
        return max(tag_levels, key=lambda l: level_rank.get(l, 0))
    
    if is_bridge:
        return "medium"
    
    return "low"


# ============================================================================
# INVESTIGATION ENDPOINTS (Forensic Case Management)
# ============================================================================

@api_bp.route("/investigations", methods=['GET'])
def list_investigations():
    """List all investigations"""
    from api.application.erc20models import (
        Investigation,
        InvestigationWallet,
        InvestigationTransfer,
        TokenPriceHistory
    )
    from sqlalchemy import func
    
    try:
        session = g.db_session
        status_filter = request.args.get('status')
        
        query = session.query(Investigation)
        if status_filter:
            query = query.filter_by(status=status_filter)
        
        investigations = query.order_by(Investigation.created_at.desc()).all()

        victim_roles = {'victim', 'theft_origin'}
        
        response_investigations = []

        for inv in investigations:
            estimated_loss_usd = None

            wallets = session.query(InvestigationWallet).filter_by(
                investigation_id=inv.id
            ).all()

            victim_wallets = {
                w.address for w in wallets if (w.role or '').lower() in victim_roles
            }
            if not victim_wallets and wallets:
                victim_wallets = {w.address for w in wallets}

            if victim_wallets:
                transfers = session.query(InvestigationTransfer).filter(
                    InvestigationTransfer.investigation_id == inv.id,
                    InvestigationTransfer.from_address.in_(victim_wallets)
                ).all()

                token_contracts = {
                    t.token_contract for t in transfers if t.token_contract
                }

                price_map = {}
                if token_contracts:
                    price_subq = session.query(
                        TokenPriceHistory.contract_address.label('contract_address'),
                        TokenPriceHistory.price.label('price'),
                        func.row_number().over(
                            partition_by=TokenPriceHistory.contract_address,
                            order_by=TokenPriceHistory.timestamp.desc()
                        ).label('rn')
                    ).filter(TokenPriceHistory.contract_address.in_(token_contracts)).subquery()

                    latest_prices = session.query(
                        price_subq.c.contract_address,
                        price_subq.c.price
                    ).filter(price_subq.c.rn == 1).all()

                    price_map = {row[0]: row[1] for row in latest_prices}

                estimated_total = 0.0
                for t in transfers:
                    if t.value is None:
                        continue
                    price = price_map.get(t.token_contract)
                    if price is None:
                        continue
                    estimated_total += float(t.value) * float(price)

                if estimated_total > 0:
                    estimated_loss_usd = round(estimated_total, 2)

            response_investigations.append({
                "id": inv.id,
                "name": inv.name,
                "status": inv.status,
                "incident_date": inv.incident_date.isoformat() if inv.incident_date else None,
                "reported_loss_usd": inv.reported_loss_usd,
                "estimated_loss_usd": estimated_loss_usd,
                "created_by": inv.created_by,
                "assigned_to": inv.assigned_to,
                "created_at": inv.created_at.isoformat() if inv.created_at else None,
                "wallet_count": len(inv.wallets),
                "token_count": len(inv.tokens)
            })

        return jsonify({
            "investigations": response_investigations
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
    from api.application.erc20models import Investigation, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID, Token
    
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


@api_bp.route("/investigations/<int:investigation_id>/graph", methods=['GET'])
def get_investigation_graph(investigation_id):
    """Get wallet flow graph and timeline for an investigation."""
    from api.application.erc20models import Investigation, InvestigationTransfer, CHAIN_ID_TO_TRIGRAM
    from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema
    
    session = g.db_session
    investigation = session.query(Investigation).filter_by(id=investigation_id).first()
    if not investigation:
        return jsonify({"error": "Investigation not found"}), 404
    
    wallet_set = {w.address.lower() for w in investigation.wallets}
    start_block = int(request.args.get('start_block', 1))
    end_block = int(request.args.get('end_block', 999999999))
    limit = int(request.args.get('limit', 500))
    include_external = request.args.get('include_external', 'true').lower() == 'true'
    
    transfers = session.query(InvestigationTransfer).filter_by(
        investigation_id=investigation_id
    ).all()
    if transfers:
        nodes = {}
        edges = []
        events = []
        min_ts = None
        max_ts = None
        edge_id = 0
        
        for t in transfers:
            from_addr = t.from_address
            to_addr = t.to_address
            ts = int(t.timestamp.timestamp()) if t.timestamp else None
            
            is_case_from = from_addr in wallet_set
            is_case_to = to_addr in wallet_set
            if not include_external and not (is_case_from and is_case_to):
                continue
            if include_external and not (is_case_from or is_case_to):
                continue
            
            if from_addr not in nodes:
                nodes[from_addr] = {
                    "id": from_addr,
                    "label": f"{from_addr[:6]}...{from_addr[-4:]}",
                    "is_case_wallet": is_case_from
                }
            if to_addr not in nodes:
                nodes[to_addr] = {
                    "id": to_addr,
                    "label": f"{to_addr[:6]}...{to_addr[-4:]}",
                    "is_case_wallet": is_case_to
                }
            
            edges.append({
                "id": edge_id,
                "from": from_addr,
                "to": to_addr,
                "value": t.value,
                "token": t.token_symbol,
                "chain": t.chain_code,
                "timestamp": ts,
                "hash": t.tx_hash,
                "blockNumber": t.block_number
            })
            edge_id += 1
            
            if ts:
                events.append({
                    "timestamp": ts,
                    "from": from_addr,
                    "to": to_addr,
                    "token": t.token_symbol,
                    "value": t.value,
                    "hash": t.tx_hash
                })
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts
        
        return jsonify({
            "nodes": list(nodes.values()),
            "edges": edges,
            "events": events,
            "stats": {
                "total_transfers": len(edges),
                "unique_wallets": len(nodes),
                "min_timestamp": min_ts,
                "max_timestamp": max_ts
            },
            "message": "Loaded from investigation transfers"
        }), 200
    
    tokens = [t for t in investigation.tokens if t.symbol]
    token_message = None
    if not tokens:
        chain_trigrams = {CHAIN_ID_TO_TRIGRAM.get(w.chain_id) for w in investigation.wallets if CHAIN_ID_TO_TRIGRAM.get(w.chain_id)}
        if chain_trigrams:
            fallback = session.query(Token).filter(Token.trigram.in_(list(chain_trigrams))).limit(5).all()
            tokens = [
                {
                    "symbol": t.symbol,
                    "chain_id": TRIGRAM_TO_CHAIN_ID.get(t.trigram, None)
                }
                for t in fallback
                if t.symbol and TRIGRAM_TO_CHAIN_ID.get(t.trigram, None)
            ]
            if tokens:
                token_message = "No investigation tokens set; using a small default token set for flow discovery"
        if not tokens:
            return jsonify({
                "nodes": [
                    {
                        "id": w.address,
                        "label": f"{w.address[:6]}...{w.address[-4:]}",
                        "role": w.role,
                        "is_case_wallet": True
                    }
                    for w in investigation.wallets
                ],
                "edges": [],
                "events": [],
                "stats": {
                    "total_transfers": 0,
                    "unique_wallets": len(wallet_set),
                    "min_timestamp": None,
                    "max_timestamp": None
                },
                "message": "No tokens tracked for this investigation"
            }), 200
    
    query = '''
        query ERC20TransferEvents($trigram: String!, $symbols: [String]!, $startBlock: Int!, $endBlock: Int!, $limit: Int) {
            erc20TransferEvents(trigram: $trigram, symbols: $symbols, startBlock: $startBlock, endBlock: $endBlock, limit: $limit) {
                edges {
                    node {
                        blockNumber
                        hash
                        tokenSymbol
                        fromContractAddress
                        toContractAddress
                        value
                        timestamp
                    }
                }
            }
        }
    '''
    
    nodes = {}
    edges = []
    events = []
    min_ts = None
    max_ts = None
    edge_id = 0
    
    for token in tokens:
        token_symbol = token.symbol if hasattr(token, 'symbol') else token.get('symbol')
        token_chain_id = token.chain_id if hasattr(token, 'chain_id') else token.get('chain_id')
        if not token_symbol or not token_chain_id:
            continue
        trigram = CHAIN_ID_TO_TRIGRAM.get(token_chain_id)
        if not trigram:
            continue
        
        result = schema.execute(
            query,
            variables={
                'trigram': trigram,
                'symbols': [token_symbol],
                'startBlock': start_block,
                'endBlock': end_block,
                'limit': limit
            },
            context={'session': session}
        )
        
        if result.errors or not result.data:
            continue
        
        transfers = result.data.get('erc20TransferEvents', {}).get('edges', [])
        for edge in transfers:
            tx = edge.get('node', {})
            from_addr = tx.get('fromContractAddress')
            to_addr = tx.get('toContractAddress')
            ts = tx.get('timestamp')
            if isinstance(ts, str):
                try:
                    ts = int(ts)
                except ValueError:
                    ts = None
            if not from_addr or not to_addr:
                continue
            
            from_lower = from_addr.lower()
            to_lower = to_addr.lower()
            is_case_from = from_lower in wallet_set
            is_case_to = to_lower in wallet_set
            
            if not include_external and not (is_case_from and is_case_to):
                continue
            if include_external and not (is_case_from or is_case_to):
                continue
            
            if from_addr not in nodes:
                nodes[from_addr] = {
                    "id": from_addr,
                    "label": f"{from_addr[:6]}...{from_addr[-4:]}",
                    "is_case_wallet": is_case_from
                }
            if to_addr not in nodes:
                nodes[to_addr] = {
                    "id": to_addr,
                    "label": f"{to_addr[:6]}...{to_addr[-4:]}",
                    "is_case_wallet": is_case_to
                }
            
            edges.append({
                "id": edge_id,
                "from": from_addr,
                "to": to_addr,
                "value": tx.get('value'),
                "token": tx.get('tokenSymbol'),
                "timestamp": ts,
                "hash": tx.get('hash'),
                "blockNumber": tx.get('blockNumber')
            })
            edge_id += 1
            
            if ts:
                events.append({
                    "timestamp": ts,
                    "from": from_addr,
                    "to": to_addr,
                    "token": tx.get('tokenSymbol'),
                    "value": tx.get('value'),
                    "hash": tx.get('hash')
                })
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts
    
    return jsonify({
        "nodes": list(nodes.values()),
        "edges": edges,
        "events": events,
        "stats": {
            "total_transfers": len(edges),
            "unique_wallets": len(nodes),
            "min_timestamp": min_ts,
            "max_timestamp": max_ts
        },
        "message": token_message
    }), 200


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


@api_bp.route("/investigations/<int:investigation_id>/sync_transfers", methods=['POST'])
def sync_investigation_transfers_endpoint(investigation_id):
    """Sync transfers for investigation wallets (address-based)."""
    from api.tasks.investigation_tasks import sync_investigation_transfers
    
    data = request.get_json() or {}
    chains = data.get('chains')
    task = sync_investigation_transfers.delay(investigation_id=investigation_id, chains=chains)
    
    return jsonify({
        "message": "Transfer sync started",
        "task_id": task.id,
        "investigation_id": investigation_id
    }), 202


@api_bp.route("/investigations/refresh_loss_data", methods=['POST'])
def refresh_investigation_loss_data():
    """Backfill token prices for all investigation transfers (for loss estimation)."""
    from api.tasks.investigation_tasks import backfill_token_prices_for_transfers

    data = request.get_json() or {}
    max_days = data.get('max_days', 120)

    task = backfill_token_prices_for_transfers.delay(max_days=max_days)
    return jsonify({
        "message": "Loss data refresh started",
        "task_id": task.id,
        "max_days": max_days
    }), 202


@api_bp.route("/investigations/<int:investigation_id>/tokens", methods=['POST'])
def add_investigation_tokens(investigation_id):
    """Add tokens to an investigation."""
    from api.application.erc20models import Investigation, InvestigationToken, TRIGRAM_TO_CHAIN_ID
    
    data = request.get_json() or {}
    tokens = data.get('tokens', [])
    if not tokens:
        return jsonify({"error": "tokens list is required"}), 400
    
    session = g.db_session
    investigation = session.query(Investigation).filter_by(id=investigation_id).first()
    if not investigation:
        return jsonify({"error": "Investigation not found"}), 404
    
    added = 0
    for token in tokens:
        symbol = token.get('symbol')
        contract = token.get('contract_address', '').lower()
        chain = (token.get('chain') or 'ETH').upper()
        chain_id = TRIGRAM_TO_CHAIN_ID.get(chain)
        if not symbol or not chain_id:
            continue
        
        existing = session.query(InvestigationToken).filter_by(
            investigation_id=investigation_id,
            contract_address=contract,
            chain_id=chain_id
        ).first()
        if existing:
            continue
        
        inv_token = InvestigationToken(
            investigation_id=investigation_id,
            contract_address=contract,
            chain_id=chain_id,
            symbol=symbol,
            stolen_amount=token.get('stolen_amount')
        )
        session.add(inv_token)
        added += 1
    
    session.commit()
    return jsonify({
        "message": "Tokens added",
        "investigation_id": investigation_id,
        "tokens_added": added
    }), 201


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


# ============================================================================
# CASE MANAGEMENT ENDPOINTS (External cases from DB)
# ============================================================================

@api_bp.route("/cases", methods=['POST'])
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

@api_bp.route("/cases", methods=['GET'])
def list_cases():
    """List all investigation cases from database."""
    from api.services.data_access import DataAccess
    from api.application.erc20models import (
        Investigation,
        InvestigationWallet,
        InvestigationTransfer,
        TokenPriceHistory,
        WalletLabel
    )
    from sqlalchemy import func
    
    try:
        session = g.db_session
        data = DataAccess(session)
        cases = data.get_cases()
        
        response_cases = []

        # Role labels for wallet categorization (fallback from InvestigationWallet.role)
        victim_roles = {'victim', 'theft_origin'}
        attacker_roles = {'attacker', 'hacker', 'scammer', 'exploiter', 'thief', 'suspect'}
        exchange_roles = {'exchange', 'cex', 'dex'}
        bridge_roles = {'bridge', 'cross_chain'}
        mixer_roles = {'mixer', 'tornado', 'tumbler', 'privacy'}
        
        # WalletLabel label_type values for cross-reference
        exchange_label_types = {'exchange', 'cex', 'dex', 'centralized_exchange', 'decentralized_exchange'}
        bridge_label_types = {'bridge', 'cross_chain', 'cross-chain'}
        mixer_label_types = {'mixer', 'tornado', 'tumbler', 'privacy', 'tornado_cash'}

        for c in cases:
            investigation = session.query(Investigation).filter(
                Investigation.name.ilike(f"%{c.id}%")
            ).first()
            investigation_id = investigation.id if investigation else None

            victim_wallet_count = 0
            attacker_wallet_count = 0
            exchange_wallet_count = 0
            bridge_wallet_count = 0
            mixer_wallet_count = 0
            estimated_loss_usd = None

            investigation_status = None
            investigation_wallet_count = 0
            investigation_token_count = 0
            investigation_reported_loss_usd = None

            if investigation:
                investigation_status = investigation.status
                investigation_wallet_count = len(investigation.wallets)
                investigation_token_count = len(investigation.tokens)
                investigation_reported_loss_usd = investigation.reported_loss_usd

            if investigation_id:
                wallets = session.query(InvestigationWallet).filter_by(
                    investigation_id=investigation_id
                ).all()
                
                # Collect all addresses in investigation
                all_addrs = {w.address.lower() for w in wallets if w.address}
                
                # Build sets by role labels from InvestigationWallet
                labeled_suspects = set()
                labeled_exchanges = set()
                labeled_bridges = set()
                labeled_mixers = set()
                labeled_victims = set()
                
                for w in wallets:
                    role = (w.role or '').lower()
                    addr = w.address.lower() if w.address else None
                    if not addr:
                        continue
                    if role in attacker_roles:
                        labeled_suspects.add(addr)
                    elif role in exchange_roles:
                        labeled_exchanges.add(addr)
                    elif role in bridge_roles:
                        labeled_bridges.add(addr)
                    elif role in mixer_roles:
                        labeled_mixers.add(addr)
                    elif role in victim_roles:
                        labeled_victims.add(addr)
                
                # Cross-reference with WalletLabel table for known entities (optional)
                if all_addrs:
                    try:
                        wallet_labels = session.query(WalletLabel).filter(
                            WalletLabel.address.in_(all_addrs)
                        ).all()
                        
                        for lbl in wallet_labels:
                            addr = lbl.address.lower()
                            lbl_type = (lbl.label_type or '').lower()
                            lbl_text = (lbl.label or '').lower()
                            
                            # Check label_type
                            if lbl_type in exchange_label_types or 'exchange' in lbl_text:
                                labeled_exchanges.add(addr)
                            elif lbl_type in bridge_label_types or 'bridge' in lbl_text:
                                labeled_bridges.add(addr)
                            elif lbl_type in mixer_label_types or 'tornado' in lbl_text or 'mixer' in lbl_text:
                                labeled_mixers.add(addr)
                    except Exception:
                        # WalletLabel table may not exist - rollback and skip
                        session.rollback()
                
                # Get all transfers for this investigation
                transfers = session.query(InvestigationTransfer).filter_by(
                    investigation_id=investigation_id
                ).all()
                
                # Build transfer graph to derive categories
                senders = set()  # addresses that send
                receivers = set()  # addresses that receive
                
                for t in transfers:
                    from_addr = (t.from_address or '').lower()
                    to_addr = (t.to_address or '').lower()
                    if from_addr:
                        senders.add(from_addr)
                    if to_addr:
                        receivers.add(to_addr)
                
                # Derive suspects: wallets that RECEIVE funds AND are in investigation
                # (excluding known exchanges/bridges/mixers)
                known_services = labeled_exchanges | labeled_bridges | labeled_mixers
                
                # If we have labeled suspects, use those as seed
                if labeled_suspects:
                    suspect_addrs = labeled_suspects
                else:
                    # Derive: addresses that receive but are NOT known services
                    # and are part of the investigation wallets
                    suspect_addrs = (receivers & all_addrs) - known_services - labeled_victims
                
                # Derive victims: addresses that SEND to suspects
                derived_victims = set()
                for t in transfers:
                    to_addr = (t.to_address or '').lower()
                    from_addr = (t.from_address or '').lower()
                    if to_addr in suspect_addrs and from_addr not in suspect_addrs:
                        derived_victims.add(from_addr)
                
                # Derive exchanges/bridges/mixers from transfers
                # = addresses that RECEIVE from suspects (outflow destinations)
                derived_exchanges = set()
                derived_bridges = set()
                derived_mixers = set()
                
                for t in transfers:
                    from_addr = (t.from_address or '').lower()
                    to_addr = (t.to_address or '').lower()
                    if from_addr in suspect_addrs and to_addr not in suspect_addrs:
                        # Outflow from suspect - check if known service
                        if to_addr in labeled_exchanges:
                            derived_exchanges.add(to_addr)
                        elif to_addr in labeled_bridges:
                            derived_bridges.add(to_addr)
                        elif to_addr in labeled_mixers:
                            derived_mixers.add(to_addr)
                
                # Final counts
                victim_wallet_count = len(derived_victims) if derived_victims else len(labeled_victims)
                attacker_wallet_count = len(suspect_addrs)
                exchange_wallet_count = len(derived_exchanges) if derived_exchanges else len(labeled_exchanges)
                bridge_wallet_count = len(derived_bridges) if derived_bridges else len(labeled_bridges)
                mixer_wallet_count = len(derived_mixers) if derived_mixers else len(labeled_mixers)
                
                # For loss calculation, use derived victims if available
                victim_wallets = derived_victims if derived_victims else labeled_victims
                if not victim_wallets and wallets:
                    # Fallback: use senders as potential victims
                    victim_wallets = senders & all_addrs

                if victim_wallets:
                    outgoing_transfers = [
                        t for t in transfers 
                        if (t.from_address or '').lower() in victim_wallets
                    ]

                    token_contracts = {
                        t.token_contract for t in outgoing_transfers if t.token_contract
                    }

                    price_map = {}
                    if token_contracts:
                        price_subq = session.query(
                            TokenPriceHistory.contract_address.label('contract_address'),
                            TokenPriceHistory.price.label('price'),
                            func.row_number().over(
                                partition_by=TokenPriceHistory.contract_address,
                                order_by=TokenPriceHistory.timestamp.desc()
                            ).label('rn')
                        ).filter(TokenPriceHistory.contract_address.in_(token_contracts)).subquery()

                        latest_prices = session.query(
                            price_subq.c.contract_address,
                            price_subq.c.price
                        ).filter(price_subq.c.rn == 1).all()

                        price_map = {row[0]: row[1] for row in latest_prices}

                    estimated_total = 0.0
                    for t in outgoing_transfers:
                        if t.value is None:
                            continue
                        price = price_map.get(t.token_contract)
                        if price is None:
                            continue
                        estimated_total += float(t.value) * float(price)

                    if estimated_total > 0:
                        estimated_loss_usd = round(estimated_total, 2)

            response_cases.append({
                "case_id": c.id,
                "title": c.title,
                "source": c.source,
                "status": c.status,
                "severity": c.severity,
                "date_reported": c.date_reported.isoformat() if c.date_reported else None,
                "summary": c.summary,
                "total_stolen_usd": c.total_stolen_usd,
                "estimated_loss_usd": estimated_loss_usd,
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

        return jsonify({
            "cases": response_cases,
            "total": len(cases)
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_bp.route("/cases/<case_id>", methods=['GET'])
def get_case(case_id):
    """Get detailed case information."""
    from api.services.data_access import DataAccess
    
    try:
        data = DataAccess(g.db_session)
        case = data.get_case(case_id)
        
        if not case:
            return jsonify({"error": f"Case not found: {case_id}"}), 404
        
        all_addresses = [{
            "address": w.address,
            "chains": [w.chain_code],
            "label": w.label,
            "role": w.role,
            "status": w.status,
            "type": "evm"
        } for w in case.wallets]
        
        return jsonify({
            "case_id": case.id,
            "title": case.title,
            "source": case.source,
            "status": case.status,
            "severity": case.severity,
            "date_reported": case.date_reported.isoformat() if case.date_reported else None,
            "summary": case.summary,
            "total_stolen_usd": case.total_stolen_usd,
            "victim_count": case.victim_count,
            "attack_vector": case.attack_vector,
            "notes": case.notes,
            "theft_addresses": all_addresses,
            "mixer_deposits": [{"protocol": m.mixer_protocol, "amount": m.amount, "chain": m.chain_code} for m in case.mixer_deposits],
            "bridge_activity": [{"from_chain": b.from_chain, "to_chain": b.to_chain, "amount_usd": b.amount_usd} for b in case.bridge_activities]
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_bp.route("/cases/<case_id>/import", methods=['POST'])
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
            return jsonify({
                "error": "Case already imported",
                "investigation_id": existing.id
            }), 409
        
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


@api_bp.route("/cases/theft-addresses", methods=['GET'])
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
        
        return jsonify({
            "addresses": addresses,
            "by_chain": by_chain,
            "total": len(addresses)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/chains", methods=['GET'])
def list_chains():
    """List all supported chains."""
    from api.services.data_access import DataAccess
    
    try:
        data = DataAccess(g.db_session)
        chains = data.get_chains()
        
        return jsonify({
            "chains": [{"trigram": c.code, "name": c.name, "chain_id": c.chain_id, "native_token": c.native_token, "is_active": c.is_active} for c in chains],
            "total": len(chains)
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/chains/<trigram>", methods=['GET'])
def get_chain(trigram):
    """Get chain details."""
    from api.services.data_access import DataAccess
    
    try:
        data = DataAccess(g.db_session)
        chain = data.get_chain(trigram.upper())
        
        if not chain:
            return jsonify({"error": f"Chain not found: {trigram}"}), 404
        
        return jsonify({
            "trigram": chain.code,
            "name": chain.name,
            "chain_id": chain.chain_id,
            "native_token": chain.native_token,
            "explorer_name": chain.explorer_name,
            "explorer_api_url": chain.explorer_api_url,
            "is_active": chain.is_active
        }), 200
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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


# ============================================================================
# REAL-TIME MONITORING ENDPOINTS
# ============================================================================

@api_bp.route("/monitor/suspects", methods=['GET'])
def get_suspect_wallets_for_monitoring():
    """
    Get all suspect wallets from investigations for monitoring.
    Returns wallets tagged as attacker/suspect with their last activity info.
    """
    from api.application.erc20models import (
        Investigation, InvestigationWallet, InvestigationTransfer, CHAIN_ID_TO_TRIGRAM
    )
    from sqlalchemy import func, desc
    
    session = g.db_session
    
    attacker_roles = {'attacker', 'hacker', 'scammer', 'exploiter', 'thief', 'suspect'}
    
    # Get all suspect wallets from all investigations
    wallets = session.query(InvestigationWallet).filter(
        func.lower(InvestigationWallet.role).in_(attacker_roles)
    ).all()
    
    result = []
    for w in wallets:
        # Get chain code from chain_id
        chain_code = CHAIN_ID_TO_TRIGRAM.get(w.chain_id, 'ETH')
        
        # Get investigation name
        investigation = session.query(Investigation).filter_by(id=w.investigation_id).first()
        inv_name = investigation.name if investigation else None
        
        # Get last outgoing transfer (movement out)
        last_out = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.from_address) == w.address.lower()
        ).order_by(desc(InvestigationTransfer.timestamp)).first()
        
        # Get last incoming transfer
        last_in = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.to_address) == w.address.lower()
        ).order_by(desc(InvestigationTransfer.timestamp)).first()
        
        # Count total outflows and their destinations
        outflows = session.query(InvestigationTransfer).filter(
            InvestigationTransfer.investigation_id == w.investigation_id,
            func.lower(InvestigationTransfer.from_address) == w.address.lower()
        ).all()
        
        total_out_value = sum(float(t.value or 0) for t in outflows)
        destinations = list(set(t.to_address for t in outflows if t.to_address))
        
        result.append({
            "address": w.address,
            "chain": chain_code,
            "role": w.role,
            "label": w.notes or '',
            "investigation_id": w.investigation_id,
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
    
    # Sort by last activity (most recent first)
    result.sort(key=lambda x: x.get('last_out_time') or '', reverse=True)
    
    return jsonify({
        "suspects": result,
        "total": len(result)
    }), 200


@api_bp.route("/monitor/wallets", methods=['GET'])
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
                "address": w.address,
                "chain": w.chain_code,
                "case_id": w.case_id,
                "label": w.label,
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


@api_bp.route("/monitor/wallets", methods=['POST'])
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


@api_bp.route("/monitor/wallets/<address>", methods=['DELETE'])
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


@api_bp.route("/monitor/cases/<case_id>/start", methods=['POST'])
def start_case_monitoring(case_id):
    """Start monitoring all addresses from a case."""
    from api.tasks.monitor_tasks import start_case_monitoring as start_task
    
    task = start_task.delay(case_id)
    
    return jsonify({
        "message": "Case monitoring started",
        "task_id": task.id,
        "case_id": case_id
    }), 202


@api_bp.route("/monitor/alerts", methods=['GET'])
def get_alerts():
    """Get recent alerts."""
    from api.services.wallet_monitor import WalletMonitorService
    
    chain = request.args.get('chain')
    case_id = request.args.get('case_id')
    alert_type = request.args.get('type')
    hours = int(request.args.get('hours', 24))
    limit = int(request.args.get('limit', 100))
    
    since = datetime.utcnow() - timedelta(hours=hours)
    
    monitor = WalletMonitorService(g.db_session)
    alerts = monitor.get_alerts(
        chain=chain,
        case_id=case_id,
        alert_type=alert_type,
        since=since,
        limit=limit
    )
    
    return jsonify({
        "alerts": [monitor.to_dict(a) for a in alerts],
        "total": len(alerts)
    }), 200


@api_bp.route("/monitor/stats", methods=['GET'])
def get_monitor_stats():
    """Get monitoring statistics."""
    from api.services.wallet_monitor import WalletMonitorService
    
    monitor = WalletMonitorService(g.db_session)
    stats = monitor.get_stats()
    
    return jsonify(stats), 200


@api_bp.route("/monitor/check", methods=['POST'])
def trigger_activity_check():
    """Trigger manual activity check on monitored wallets."""
    from api.tasks.monitor_tasks import check_wallet_activity
    
    data = request.get_json() or {}
    chain = data.get('chain')
    
    task = check_wallet_activity.delay(chain=chain)
    
    return jsonify({
        "message": "Activity check started",
        "task_id": task.id,
        "chain": chain or "all"
    }), 202


# ============================================================================
# FEATURE ENGINEERING ENDPOINTS
# ============================================================================

@api_bp.route("/features/<address>", methods=['GET'])
def get_wallet_features(address):
    """Extract features for a wallet address."""
    from api.services.feature_engineer import WalletFeatureEngineer
    
    chain = request.args.get('chain', 'ETH').upper()
    lookback_days = int(request.args.get('lookback_days', 90))
    
    try:
        engineer = WalletFeatureEngineer(session=g.db_session)
        features = engineer.extract_features(
            address=address,
            chain=chain,
            lookback_days=lookback_days
        )
        
        return jsonify({
            "address": address,
            "chain": chain,
            "lookback_days": lookback_days,
            "feature_count": len(features),
            "features": features
        }), 200
        
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_bp.route("/features/names", methods=['GET'])
def get_feature_names():
    """Get list of all feature names with categories."""
    from api.services.feature_engineer import WalletFeatureEngineer
    
    engineer = WalletFeatureEngineer()
    
    return jsonify({
        "feature_names": engineer.get_feature_names(),
        "feature_categories": engineer.get_feature_importance_groups(),
        "total_features": len(engineer.get_feature_names())
    }), 200


# ============================================================================
# NOTEBOOK EXECUTION ENDPOINTS
# ============================================================================

@api_bp.route("/notebooks", methods=['GET'])
def list_notebooks():
    """List available analysis notebooks."""
    from api.services.notebook_runner import get_notebook_runner
    
    try:
        runner = get_notebook_runner()
        notebooks = runner.list_available_notebooks()
        return jsonify({"notebooks": notebooks}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/notebooks/execute", methods=['POST'])
def execute_notebook():
    """Execute an analysis notebook."""
    from api.services.notebook_runner import get_notebook_runner
    from api.tasks.monitor_tasks import run_notebook_task
    
    data = request.get_json() or {}
    notebook_name = data.get('notebook')
    parameters = data.get('parameters', {})
    async_exec = data.get('async', True)
    
    if not notebook_name:
        return jsonify({"error": "Missing 'notebook' parameter"}), 400
    
    try:
        if async_exec:
            # Run async via Celery
            task = run_notebook_task.delay(notebook_name, parameters)
            return jsonify({
                "status": "queued",
                "task_id": task.id,
                "notebook": notebook_name
            }), 202
        else:
            # Run synchronously
            runner = get_notebook_runner()
            execution = runner.execute_notebook(notebook_name, parameters)
            return jsonify(execution.to_dict()), 200
            
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


@api_bp.route("/notebooks/executions", methods=['GET'])
def list_executions():
    """List notebook execution history."""
    from api.services.notebook_runner import get_notebook_runner
    
    limit = int(request.args.get('limit', 50))
    
    try:
        runner = get_notebook_runner()
        executions = runner.get_all_executions(limit=limit)
        return jsonify({
            "executions": [e.to_dict() for e in executions],
            "total": len(executions)
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/notebooks/executions/<job_id>", methods=['GET'])
def get_execution(job_id):
    """Get execution status by job ID."""
    from api.services.notebook_runner import get_notebook_runner
    
    try:
        runner = get_notebook_runner()
        execution = runner.get_execution(job_id)
        
        if not execution:
            return jsonify({"error": f"Execution {job_id} not found"}), 404
            
        return jsonify(execution.to_dict()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@api_bp.route("/notebooks/analyze", methods=['POST'])
def run_analysis():
    """Run a pre-defined analysis on addresses."""
    from api.services.notebook_runner import get_notebook_runner
    
    data = request.get_json() or {}
    analysis_type = data.get('analysis_type')
    addresses = data.get('addresses', [])
    chain = data.get('chain', 'ETH')
    case_id = data.get('case_id')
    
    if not analysis_type:
        return jsonify({"error": "Missing 'analysis_type' parameter"}), 400
    if not addresses:
        return jsonify({"error": "Missing 'addresses' parameter"}), 400
    
    try:
        runner = get_notebook_runner()
        execution = runner.execute_analysis(
            analysis_type=analysis_type,
            addresses=addresses,
            chain=chain,
            case_id=case_id,
            **{k: v for k, v in data.items() if k not in ['analysis_type', 'addresses', 'chain', 'case_id']}
        )
        return jsonify(execution.to_dict()), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500


def init_api_routes(app):
    app.register_blueprint(api_bp, url_prefix='/api')
