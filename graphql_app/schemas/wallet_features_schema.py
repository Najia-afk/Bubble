# wallet_features_schema.py
"""
GraphQL schema for wallet feature extraction.
Pure SQLAlchemy ORM — zero raw SQL.
"""
import graphene
import logging
from sqlalchemy import func, case, or_, and_, distinct
from graphql import GraphQLError
from api.application.erc20models import InvestigationTransfer
from utils.logging_config import setup_logging

wallet_features_logger = setup_logging('wallet_features_schema.log', log_level=logging.INFO)


class WalletFeatureType(graphene.ObjectType):
    """Aggregate transaction features for a single wallet address."""
    address = graphene.String(description="Wallet address (lowercase)")
    tx_count = graphene.Int(description="Total transaction count (in + out)")
    unique_counterparties = graphene.Int(description="Unique senders + receivers")
    avg_tx_value = graphene.Float(description="Average outgoing transaction value")
    max_tx_value = graphene.Float(description="Maximum outgoing transaction value")
    in_out_ratio = graphene.Float(description="Ratio of incoming to outgoing transactions")
    total_volume = graphene.Float(description="Total volume (in + out)")
    out_count = graphene.Int(description="Outgoing transaction count")
    in_count = graphene.Int(description="Incoming transaction count")
    unique_senders = graphene.Int(description="Unique sender addresses")
    unique_receivers = graphene.Int(description="Unique receiver addresses")


class WalletFeaturesBatchResult(graphene.ObjectType):
    """Result of a batch wallet feature extraction."""
    total_requested = graphene.Int(description="Number of addresses requested")
    total_found = graphene.Int(description="Number of addresses with features")
    features = graphene.List(WalletFeatureType, description="Feature vectors per wallet")


def _build_single_wallet_features(session, addr_lower, investigation_id=None):
    """Build features for a single wallet using pure SQLAlchemy ORM."""
    T = InvestigationTransfer

    is_sender = func.lower(T.from_address) == addr_lower
    is_receiver = func.lower(T.to_address) == addr_lower

    base_filter = or_(is_sender, is_receiver)
    if investigation_id:
        base_filter = and_(base_filter, T.investigation_id == investigation_id)

    row = session.query(
        func.sum(case((is_sender, 1), else_=0)).label('out_count'),
        func.sum(case((is_receiver, 1), else_=0)).label('in_count'),
        func.count(distinct(case((is_sender, T.to_address)))).label('unique_to'),
        func.count(distinct(case((is_receiver, T.from_address)))).label('unique_from'),
        func.avg(case((is_sender, func.coalesce(T.value, 0)))).label('avg_out_value'),
        func.max(case((is_sender, func.coalesce(T.value, 0)))).label('max_out_value'),
        func.sum(case((is_sender, func.coalesce(T.value, 0)), else_=0)).label('total_out'),
        func.sum(case((is_receiver, func.coalesce(T.value, 0)), else_=0)).label('total_in'),
    ).filter(base_filter).first()

    if row is None:
        return None

    out_count = int(row.out_count or 0)
    in_count = int(row.in_count or 0)

    if out_count + in_count == 0:
        return None

    return WalletFeatureType(
        address=addr_lower,
        tx_count=out_count + in_count,
        unique_counterparties=int(row.unique_to or 0) + int(row.unique_from or 0),
        avg_tx_value=float(row.avg_out_value or 0),
        max_tx_value=float(row.max_out_value or 0),
        in_out_ratio=(in_count / out_count) if out_count > 0 else 1.0,
        total_volume=float(row.total_out or 0) + float(row.total_in or 0),
        out_count=out_count,
        in_count=in_count,
        unique_senders=int(row.unique_from or 0),
        unique_receivers=int(row.unique_to or 0),
    )


def _build_batch_wallet_features(session, addr_list, investigation_id=None):
    """Build features for many wallets using pure SQLAlchemy ORM — single query."""
    T = InvestigationTransfer

    # We need to identify which addresses each row belongs to.
    # Strategy: query all transfers involving ANY of our addresses,
    # then aggregate in Python. This avoids CTE/UNNEST and stays pure ORM.
    from_filter = func.lower(T.from_address).in_(addr_list)
    to_filter = func.lower(T.to_address).in_(addr_list)
    base_filter = or_(from_filter, to_filter)
    if investigation_id:
        base_filter = and_(base_filter, T.investigation_id == investigation_id)

    # Fetch only needed columns for efficiency
    rows = session.query(
        T.from_address,
        T.to_address,
        func.coalesce(T.value, 0).label('value'),
    ).filter(base_filter).all()

    # Build per-wallet aggregates in Python
    addr_set = set(addr_list)
    wallet_data = {}  # addr -> {out_count, in_count, out_values, senders, receivers, total_out, total_in}

    for from_addr, to_addr, value in rows:
        from_lower = from_addr.lower() if from_addr else ''
        to_lower = to_addr.lower() if to_addr else ''
        val = float(value or 0)

        # Sender side
        if from_lower in addr_set:
            if from_lower not in wallet_data:
                wallet_data[from_lower] = {
                    'out_count': 0, 'in_count': 0, 'out_values': [],
                    'senders': set(), 'receivers': set(), 'total_out': 0.0, 'total_in': 0.0
                }
            d = wallet_data[from_lower]
            d['out_count'] += 1
            d['out_values'].append(val)
            d['total_out'] += val
            if to_addr:
                d['receivers'].add(to_lower)

        # Receiver side
        if to_lower in addr_set:
            if to_lower not in wallet_data:
                wallet_data[to_lower] = {
                    'out_count': 0, 'in_count': 0, 'out_values': [],
                    'senders': set(), 'receivers': set(), 'total_out': 0.0, 'total_in': 0.0
                }
            d = wallet_data[to_lower]
            d['in_count'] += 1
            d['total_in'] += val
            if from_addr:
                d['senders'].add(from_lower)

    # Convert to WalletFeatureType
    features = []
    for addr, d in wallet_data.items():
        out_count = d['out_count']
        in_count = d['in_count']
        if out_count + in_count == 0:
            continue
        out_values = d['out_values']
        features.append(WalletFeatureType(
            address=addr,
            tx_count=out_count + in_count,
            unique_counterparties=len(d['receivers']) + len(d['senders']),
            avg_tx_value=(sum(out_values) / len(out_values)) if out_values else 0,
            max_tx_value=max(out_values) if out_values else 0,
            in_out_ratio=(in_count / out_count) if out_count > 0 else 1.0,
            total_volume=d['total_out'] + d['total_in'],
            out_count=out_count,
            in_count=in_count,
            unique_senders=len(d['senders']),
            unique_receivers=len(d['receivers']),
        ))

    return features


class Query(graphene.ObjectType):
    """Wallet feature queries for ML pipeline and analytics."""

    wallet_features = graphene.Field(
        WalletFeatureType,
        address=graphene.String(required=True, description="Wallet address"),
        investigation_id=graphene.Int(description="Optional investigation filter"),
        description="Extract aggregate transaction features for a single wallet"
    )

    wallet_features_batch = graphene.Field(
        WalletFeaturesBatchResult,
        addresses=graphene.List(graphene.String, required=True, description="List of wallet addresses"),
        investigation_id=graphene.Int(description="Optional investigation filter"),
        description="Extract features for many wallets in a single optimized query"
    )

    def resolve_wallet_features(self, info, address, investigation_id=None):
        session = info.context.get('session')
        if not session:
            raise GraphQLError("Database session not found")
        try:
            return _build_single_wallet_features(session, address.lower(), investigation_id)
        except Exception as e:
            wallet_features_logger.error(f"Feature extraction failed for {address}: {e}")
            raise GraphQLError(f"Feature extraction failed: {e}")

    def resolve_wallet_features_batch(self, info, addresses, investigation_id=None):
        session = info.context.get('session')
        if not session:
            raise GraphQLError("Database session not found")
        if not addresses:
            return WalletFeaturesBatchResult(total_requested=0, total_found=0, features=[])

        addr_list = [a.lower() for a in addresses]
        wallet_features_logger.info(f"Batch feature extraction for {len(addr_list)} wallets")

        try:
            features = _build_batch_wallet_features(session, addr_list, investigation_id)
            wallet_features_logger.info(f"Batch features: {len(features)}/{len(addr_list)} wallets found")
            return WalletFeaturesBatchResult(
                total_requested=len(addr_list),
                total_found=len(features),
                features=features
            )
        except Exception as e:
            wallet_features_logger.error(f"Batch feature extraction failed: {e}")
            raise GraphQLError(f"Batch feature extraction failed: {e}")


schema = graphene.Schema(query=Query)
