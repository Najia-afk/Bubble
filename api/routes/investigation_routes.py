"""Investigation forensic case management endpoints."""

from flask import Blueprint, request, jsonify, g
from datetime import datetime, timezone
from sqlalchemy import func

investigation_bp = Blueprint('investigations', __name__)


@investigation_bp.route("/investigations", methods=['GET'])
def list_investigations():
    """List all investigations."""
    from api.application.erc20models import (
        Investigation, InvestigationWallet, InvestigationTransfer, TokenPriceHistory
    )

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

            victim_wallets = {w.address for w in wallets if (w.role or '').lower() in victim_roles}
            if not victim_wallets and wallets:
                victim_wallets = {w.address for w in wallets}

            if victim_wallets:
                transfers = session.query(InvestigationTransfer).filter(
                    InvestigationTransfer.investigation_id == inv.id,
                    InvestigationTransfer.from_address.in_(victim_wallets)
                ).all()

                token_contracts = {t.token_contract for t in transfers if t.token_contract}
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
                        price_subq.c.contract_address, price_subq.c.price
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

        return jsonify({"investigations": response_investigations}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@investigation_bp.route("/investigations", methods=['POST'])
def create_investigation():
    """Create a new investigation case."""
    from api.application.erc20models import (
        Investigation, InvestigationWallet, InvestigationToken, WalletScore, TRIGRAM_TO_CHAIN_ID, Base
    )

    data = request.get_json()
    if not data.get('name'):
        return jsonify({"error": "Missing required field: name"}), 400

    try:
        session = g.db_session

        Base.metadata.create_all(session.get_bind(), tables=[
            Investigation.__table__,
            InvestigationWallet.__table__,
            InvestigationToken.__table__,
            WalletScore.__table__
        ])

        incident_date = None
        if data.get('incident_date'):
            try:
                incident_date = datetime.fromisoformat(data['incident_date'].replace('Z', '+00:00'))
            except Exception:
                incident_date = datetime.now(timezone.utc)

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
        session.flush()

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


@investigation_bp.route("/investigations/<int:investigation_id>", methods=['GET'])
def get_investigation(investigation_id):
    """Get investigation details with all wallets and tokens."""
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
                    "id": w.id, "address": w.address, "chain_id": w.chain_id,
                    "chain": CHAIN_ID_TO_TRIGRAM.get(w.chain_id, 'UNKNOWN'),
                    "role": w.role, "depth": w.depth, "parent_address": w.parent_address,
                    "total_received": w.total_received, "total_sent": w.total_sent,
                    "is_flagged": w.is_flagged, "notes": w.notes
                }
                for w in investigation.wallets
            ],
            "tokens": [
                {
                    "id": t.id, "symbol": t.symbol,
                    "contract_address": t.contract_address, "chain_id": t.chain_id,
                    "chain": CHAIN_ID_TO_TRIGRAM.get(t.chain_id, 'UNKNOWN'),
                    "stolen_amount": t.stolen_amount
                }
                for t in investigation.tokens
            ]
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@investigation_bp.route("/investigations/<int:investigation_id>/graph", methods=['GET'])
def get_investigation_graph(investigation_id):
    """Get wallet flow graph and timeline for an investigation."""
    from api.application.erc20models import (
        Investigation, InvestigationTransfer, CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID, Token
    )
    from graphql_app.schemas.fetch_erc20_transfer_history_schema import schema

    session = g.db_session
    investigation = session.query(Investigation).filter_by(id=investigation_id).first()
    if not investigation:
        return jsonify({"error": "Investigation not found"}), 404

    wallet_set = {w.address.lower() for w in investigation.wallets}
    wallet_roles = {w.address.lower(): (w.role or 'related') for w in investigation.wallets}
    wallet_depths = {w.address.lower(): (w.depth or 0) for w in investigation.wallets}
    start_block = int(request.args.get('start_block', 1))
    end_block = int(request.args.get('end_block', 999999999))
    limit = int(request.args.get('limit', 500))
    include_external = request.args.get('include_external', 'true').lower() == 'true'

    # Options for big-data mode
    aggregate = request.args.get('aggregate', 'false').lower() == 'true'
    max_edges = int(request.args.get('max_edges', 10000))

    # Try from InvestigationTransfer records first (stream, don't load all)
    transfer_count = session.query(InvestigationTransfer).filter_by(
        investigation_id=investigation_id
    ).count()
    if transfer_count > 0:
        transfer_q = session.query(InvestigationTransfer).filter_by(
            investigation_id=investigation_id
        ).yield_per(500)

        nodes = {}
        edges = []
        events = []
        min_ts = None
        max_ts = None
        edge_id = 0
        # For big-data aggregation: (from, to, token, chain) → aggregated edge
        agg_edges = {} if aggregate else None

        for t in transfer_q:
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
                    "id": from_addr, "label": f"{from_addr[:6]}...{from_addr[-4:]}",
                    "is_case_wallet": is_case_from,
                    "role": wallet_roles.get(from_addr, 'external'),
                    "depth": wallet_depths.get(from_addr, -1)
                }
            if to_addr not in nodes:
                nodes[to_addr] = {
                    "id": to_addr, "label": f"{to_addr[:6]}...{to_addr[-4:]}",
                    "is_case_wallet": is_case_to,
                    "role": wallet_roles.get(to_addr, 'external'),
                    "depth": wallet_depths.get(to_addr, -1)
                }

            raw_val = t.value or 0
            decimals = t.token_decimals or 0
            if decimals > 0:
                # value was properly normalized at sync (value_raw / 10^decimals)
                normalised_val = raw_val
            else:
                # decimals=0 means API didn't report decimals;
                # value = raw amount, needs normalization
                if raw_val > 1e15:
                    normalised_val = raw_val / 1e18   # assume 18 (EVM default)
                else:
                    normalised_val = raw_val

            # Clamp absurd values (spam/scam tokens with inflated supplies)
            # Any single transfer > $1 quadrillion is data noise
            if abs(normalised_val) > 1e15:
                normalised_val = min(normalised_val, 1e15)

            if aggregate:
                key = (from_addr, to_addr, t.token_symbol or '', t.chain_code or '')
                if key not in agg_edges:
                    agg_edges[key] = {
                        "from": from_addr, "to": to_addr,
                        "value": 0, "token": t.token_symbol, "chain": t.chain_code,
                        "tx_count": 0, "min_ts": ts, "max_ts": ts,
                        "hash": t.tx_hash, "blockNumber": t.block_number,
                    }
                agg_edges[key]["value"] += normalised_val
                agg_edges[key]["tx_count"] += 1
                if ts:
                    if agg_edges[key]["min_ts"] is None or ts < agg_edges[key]["min_ts"]:
                        agg_edges[key]["min_ts"] = ts
                    if agg_edges[key]["max_ts"] is None or ts > agg_edges[key]["max_ts"]:
                        agg_edges[key]["max_ts"] = ts
            else:
                if edge_id < max_edges:
                    edges.append({
                        "id": edge_id, "from": from_addr, "to": to_addr,
                        "value": round(normalised_val, 6), "token": t.token_symbol,
                        "chain": t.chain_code, "timestamp": ts,
                        "hash": t.tx_hash, "blockNumber": t.block_number
                    })
                edge_id += 1

            if ts:
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts

        # Finalise aggregated edges
        if aggregate and agg_edges:
            for idx, (key, agg) in enumerate(agg_edges.items()):
                edges.append({
                    "id": idx, "from": agg["from"], "to": agg["to"],
                    "value": round(agg["value"], 6), "token": agg["token"],
                    "chain": agg["chain"], "timestamp": agg["max_ts"],
                    "hash": agg["hash"], "blockNumber": agg["blockNumber"],
                    "tx_count": agg["tx_count"],
                })
            edge_id = transfer_count  # report full count

        # Build lightweight events (only first 2000 for timeline)
        events = []
        if not aggregate:
            for e in edges[:2000]:
                if e.get("timestamp"):
                    events.append({
                        "timestamp": e["timestamp"], "from": e["from"], "to": e["to"],
                        "token": e["token"], "value": e["value"], "hash": e["hash"]
                    })

        return jsonify({
            "nodes": list(nodes.values()), "edges": edges, "events": events,
            "stats": {
                "total_transfers": edge_id, "unique_wallets": len(nodes),
                "min_timestamp": min_ts, "max_timestamp": max_ts,
                "aggregated": aggregate, "edges_returned": len(edges),
            },
            "message": "Loaded from investigation transfers" + (" (aggregated)" if aggregate else "")
        }), 200

    # Fallback: use GraphQL to query live data
    tokens = [t for t in investigation.tokens if t.symbol]
    token_message = None
    if not tokens:
        chain_trigrams = {CHAIN_ID_TO_TRIGRAM.get(w.chain_id) for w in investigation.wallets if CHAIN_ID_TO_TRIGRAM.get(w.chain_id)}
        if chain_trigrams:
            fallback = session.query(Token).filter(Token.trigram.in_(list(chain_trigrams))).limit(5).all()
            tokens = [
                {"symbol": t.symbol, "chain_id": TRIGRAM_TO_CHAIN_ID.get(t.trigram, None)}
                for t in fallback
                if t.symbol and TRIGRAM_TO_CHAIN_ID.get(t.trigram, None)
            ]
            if tokens:
                token_message = "No investigation tokens set; using a small default token set for flow discovery"
        if not tokens:
            return jsonify({
                "nodes": [
                    {"id": w.address, "label": f"{w.address[:6]}...{w.address[-4:]}", "role": w.role, "is_case_wallet": True}
                    for w in investigation.wallets
                ],
                "edges": [], "events": [],
                "stats": {"total_transfers": 0, "unique_wallets": len(wallet_set), "min_timestamp": None, "max_timestamp": None},
                "message": "No tokens tracked for this investigation"
            }), 200

    gql_query = '''
        query ERC20TransferEvents($trigram: String!, $symbols: [String]!, $startBlock: Int!, $endBlock: Int!, $limit: Int) {
            erc20TransferEvents(trigram: $trigram, symbols: $symbols, startBlock: $startBlock, endBlock: $endBlock, limit: $limit) {
                edges { node { blockNumber hash tokenSymbol fromContractAddress toContractAddress value timestamp } }
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
            gql_query,
            variables={'trigram': trigram, 'symbols': [token_symbol], 'startBlock': start_block, 'endBlock': end_block, 'limit': limit},
            context={'session': session}
        )

        if result.errors or not result.data:
            continue

        gql_transfers = result.data.get('erc20TransferEvents', {}).get('edges', [])
        for edge in gql_transfers:
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
                    "id": from_addr, "label": f"{from_addr[:6]}...{from_addr[-4:]}",
                    "is_case_wallet": is_case_from,
                    "role": wallet_roles.get(from_lower, 'external'),
                    "depth": wallet_depths.get(from_lower, -1),
                }
            if to_addr not in nodes:
                nodes[to_addr] = {
                    "id": to_addr, "label": f"{to_addr[:6]}...{to_addr[-4:]}",
                    "is_case_wallet": is_case_to,
                    "role": wallet_roles.get(to_lower, 'external'),
                    "depth": wallet_depths.get(to_lower, -1),
                }

            edges.append({
                "id": edge_id, "from": from_addr, "to": to_addr,
                "value": tx.get('value'), "token": tx.get('tokenSymbol'),
                "chain": trigram,
                "timestamp": ts, "hash": tx.get('hash'), "blockNumber": tx.get('blockNumber')
            })
            edge_id += 1

            if ts:
                events.append({
                    "timestamp": ts, "from": from_addr, "to": to_addr,
                    "token": tx.get('tokenSymbol'), "value": tx.get('value'), "hash": tx.get('hash')
                })
                if min_ts is None or ts < min_ts:
                    min_ts = ts
                if max_ts is None or ts > max_ts:
                    max_ts = ts

    return jsonify({
        "nodes": list(nodes.values()), "edges": edges, "events": events,
        "stats": {"total_transfers": len(edges), "unique_wallets": len(nodes), "min_timestamp": min_ts, "max_timestamp": max_ts},
        "message": token_message
    }), 200


@investigation_bp.route("/investigations/<int:investigation_id>/wallets", methods=['POST'])
def add_investigation_wallet(investigation_id):
    """Add a wallet to an investigation."""
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

        existing = session.query(InvestigationWallet).filter_by(
            investigation_id=investigation_id, address=data['address'].lower(), chain_id=chain_id
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

        return jsonify({"message": "Wallet added", "id": wallet.id, "address": wallet.address, "role": wallet.role}), 201

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500


@investigation_bp.route("/investigations/<int:investigation_id>/sync_transfers", methods=['POST'])
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


@investigation_bp.route("/investigations/refresh_loss_data", methods=['POST'])
def refresh_investigation_loss_data():
    """Backfill token prices for all investigation transfers."""
    from api.tasks.investigation_tasks import backfill_token_prices_for_transfers

    data = request.get_json() or {}
    max_days = data.get('max_days', 120)
    task = backfill_token_prices_for_transfers.delay(max_days=max_days)
    return jsonify({"message": "Loss data refresh started", "task_id": task.id, "max_days": max_days}), 202


@investigation_bp.route("/investigations/<int:investigation_id>/tokens", methods=['POST'])
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
            investigation_id=investigation_id, contract_address=contract, chain_id=chain_id
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
    return jsonify({"message": "Tokens added", "investigation_id": investigation_id, "tokens_added": added}), 201


@investigation_bp.route("/investigations/<int:investigation_id>/expand", methods=['POST'])
def trigger_investigation_expand(investigation_id):
    """Trigger auto-expansion of investigation."""
    from api.tasks.investigation_tasks import expand_investigation

    data = request.get_json() or {}
    max_depth = data.get('max_depth', 3)
    max_wallets = data.get('max_wallets', 100)

    task = expand_investigation.delay(
        investigation_id=investigation_id, max_depth=max_depth, max_wallets=max_wallets
    )

    return jsonify({
        "message": "Expansion task submitted",
        "task_id": task.id,
        "investigation_id": investigation_id,
        "max_depth": max_depth,
        "max_wallets": max_wallets
    }), 202


@investigation_bp.route("/investigations/<int:investigation_id>/investigate", methods=['POST'])
def trigger_full_investigation(investigation_id):
    """One-click investigate: sync transfers -> expand -> sync new wallets -> repeat."""
    from api.tasks.investigation_tasks import sync_and_expand

    data = request.get_json() or {}
    max_depth = data.get('max_depth', 3)
    max_wallets = data.get('max_wallets', 100)

    task = sync_and_expand.delay(
        investigation_id=investigation_id, max_depth=max_depth, max_wallets=max_wallets
    )

    return jsonify({
        "message": "Full investigation pipeline started (sync -> expand -> classify)",
        "task_id": task.id,
        "investigation_id": investigation_id,
        "max_depth": max_depth,
        "max_wallets": max_wallets
    }), 202


@investigation_bp.route("/investigations/<int:investigation_id>/classify", methods=['POST'])
def trigger_investigation_classify(investigation_id):
    """Run ML classification on all wallets in the investigation."""
    from api.tasks.investigation_tasks import classify_investigation_wallets

    task = classify_investigation_wallets.delay(investigation_id=investigation_id)
    return jsonify({"message": "Classification task submitted", "task_id": task.id, "investigation_id": investigation_id}), 202


@investigation_bp.route("/investigations/<int:investigation_id>/report", methods=['GET'])
def get_investigation_report(investigation_id):
    """Get a summary report for an investigation."""
    from api.tasks.investigation_tasks import generate_investigation_report

    result = generate_investigation_report(investigation_id)
    if result.get('status') == 'error':
        return jsonify(result), 404
    return jsonify(result), 200


@investigation_bp.route("/investigations/<int:investigation_id>/timeline", methods=['GET'])
def get_investigation_timeline(investigation_id):
    """Return vis.js-compatible timeline data."""
    from api.services.timeline_service import get_timeline_data

    session = g.db_session
    try:
        data = get_timeline_data(investigation_id, session)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@investigation_bp.route("/investigations/<int:investigation_id>/status", methods=['PUT'])
def update_investigation_status(investigation_id):
    """Update investigation status."""
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
        investigation.updated_at = datetime.now(timezone.utc)
        if new_status == 'closed':
            investigation.closed_at = datetime.now(timezone.utc)

        session.commit()
        return jsonify({"message": "Status updated", "id": investigation_id, "status": new_status}), 200

    except Exception as e:
        session.rollback()
        return jsonify({"error": str(e)}), 500
