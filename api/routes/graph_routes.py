"""Graph data & dashboard statistics endpoints."""

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func, inspect as sa_inspect

graph_bp = Blueprint('graph', __name__)


@graph_bp.route("/graph/transfers", methods=['GET'])
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

            if from_addr not in wallets:
                wallets[from_addr] = {
                    'id': from_addr,
                    'label': f"{from_addr[:6]}...{from_addr[-4:]}",
                    'out_count': 0, 'in_count': 0,
                    'out_volume': 0, 'in_volume': 0
                }
            wallets[from_addr]['out_count'] += 1
            wallets[from_addr]['out_volume'] += value

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


@graph_bp.route("/stats/dashboard", methods=['GET'])
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

        chains = data.get_chain_codes()

        try:
            token_count = session.query(Token).count()
        except Exception:
            session.rollback()
            token_count = 0

        stats = {
            'tokens': token_count,
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

        try:
            all_cases = data.get_cases()
            stats['total_cases'] = len(all_cases)
            stats['active_cases'] = len([c for c in all_cases if c.status == 'active'])
            stats['investigating_cases'] = len([c for c in all_cases if c.status == 'investigating'])
            total_loss = sum(c.total_stolen_usd or 0 for c in all_cases)
            stats['estimated_loss_usd'] = total_loss
        except Exception:
            pass

        try:
            stats['total_investigations'] = session.query(Investigation).count()
            stats['investigation_wallets'] = session.query(InvestigationWallet).count()
            stats['investigation_transfers'] = session.query(InvestigationTransfer).count()
        except Exception:
            pass

        try:
            tokens = session.query(Token).limit(10).all()
        except Exception:
            session.rollback()
            tokens = []

        all_wallets = set()
        total_transfers = 0

        for token in tokens:
            try:
                from api.application.erc20models import get_transfer_event_class

                cls = get_transfer_event_class(token.symbol, token.trigram)
                if cls is None:
                    continue

                inspector = sa_inspect(session.get_bind())
                if cls.__tablename__ not in inspector.get_table_names():
                    continue

                count = session.query(func.count(cls.id)).scalar() or 0
                total_transfers += min(count, 10000)

                from_addrs = session.query(cls.from_contract_address).distinct().limit(1000).all()
                to_addrs = session.query(cls.to_contract_address).distinct().limit(1000).all()
                all_wallets.update([r[0] for r in from_addrs if r[0]])
                all_wallets.update([r[0] for r in to_addrs if r[0]])

            except Exception:
                continue

        stats['transfers'] = total_transfers
        stats['wallets'] = len(all_wallets)

        return jsonify(stats), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500
