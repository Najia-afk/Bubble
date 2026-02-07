# wallet_labels_schema.py
"""
GraphQL schema for wallet label queries and mutations.
Used by ML pipeline, classification, and investigation tooling.
"""
import graphene
import logging
from datetime import datetime
from sqlalchemy import func
from graphql import GraphQLError
from api.application.erc20models import WalletLabel, InvestigationWallet, CHAIN_ID_TO_TRIGRAM
from utils.logging_config import setup_logging

wallet_labels_logger = setup_logging('wallet_labels_schema.log', log_level=logging.INFO)


class WalletLabelType(graphene.ObjectType):
    """A wallet label record."""
    id = graphene.Int()
    address = graphene.String()
    chain_id = graphene.Int()
    chain_trigram = graphene.String()
    label = graphene.String()
    label_type = graphene.String()
    name_tag = graphene.String()
    source = graphene.String()
    confidence = graphene.Float()
    is_trusted = graphene.Boolean()
    created_at = graphene.DateTime()


class LabelDistributionEntry(graphene.ObjectType):
    """Distribution statistics for a label type."""
    label_type = graphene.String()
    count = graphene.Int()
    avg_confidence = graphene.Float()


class WalletLabelsResult(graphene.ObjectType):
    """Result for validated labels query."""
    total = graphene.Int()
    labels = graphene.List(WalletLabelType)
    distribution = graphene.List(LabelDistributionEntry)


class InvestigationWalletType(graphene.ObjectType):
    """A wallet linked to an investigation (with role/classification)."""
    address = graphene.String()
    chain_id = graphene.Int()
    investigation_id = graphene.Int()
    role = graphene.String()
    depth = graphene.Int()
    total_received = graphene.Float()
    total_sent = graphene.Float()
    is_flagged = graphene.Boolean()


class Query(graphene.ObjectType):
    """Wallet label and classification queries."""

    # Validated labels for ML training
    validated_labels = graphene.Field(
        WalletLabelsResult,
        min_confidence=graphene.Float(default_value=0.8, description="Minimum confidence threshold"),
        chain=graphene.String(description="Optional chain trigram filter (ETH, POL, BSC, etc.)"),
        label_type=graphene.String(description="Optional label type filter"),
        source=graphene.String(description="Optional source filter (api, manual, ml, inv_classify)"),
        limit=graphene.Int(default_value=10000, description="Max results"),
        description="Get validated wallet labels for ML training"
    )

    # Investigation wallets with classifications
    investigation_wallets = graphene.List(
        InvestigationWalletType,
        investigation_id=graphene.Int(description="Filter by investigation"),
        role=graphene.String(description="Filter by role (attacker, exchange, etc.)"),
        description="Get classified wallets from investigations"
    )

    def resolve_validated_labels(self, info, min_confidence=0.8, chain=None, label_type=None, source=None, limit=10000):
        session = info.context.get('session')
        if not session:
            raise GraphQLError("Database session not found")

        try:
            query = session.query(WalletLabel).filter(
                WalletLabel.confidence >= min_confidence
            )
            if chain:
                from api.application.erc20models import TRIGRAM_TO_CHAIN_ID
                chain_id = TRIGRAM_TO_CHAIN_ID.get(chain.upper())
                if chain_id:
                    query = query.filter(WalletLabel.chain_id == chain_id)
            if label_type:
                query = query.filter(WalletLabel.label_type == label_type)
            if source:
                query = query.filter(WalletLabel.source == source)

            query = query.limit(limit)
            records = query.all()

            labels = [
                WalletLabelType(
                    id=r.id,
                    address=r.address,
                    chain_id=r.chain_id,
                    chain_trigram=CHAIN_ID_TO_TRIGRAM.get(r.chain_id, 'UNK'),
                    label=r.label,
                    label_type=r.label_type,
                    name_tag=r.name_tag,
                    source=r.source,
                    confidence=r.confidence,
                    is_trusted=r.is_trusted,
                    created_at=r.created_at,
                )
                for r in records
            ]

            # Distribution stats
            dist_query = session.query(
                WalletLabel.label_type,
                func.count(WalletLabel.id),
                func.avg(WalletLabel.confidence)
            ).filter(
                WalletLabel.confidence >= min_confidence
            ).group_by(WalletLabel.label_type).order_by(func.count(WalletLabel.id).desc())

            distribution = [
                LabelDistributionEntry(
                    label_type=row[0] or 'unknown',
                    count=row[1],
                    avg_confidence=round(float(row[2] or 0), 4)
                )
                for row in dist_query.all()
            ]

            return WalletLabelsResult(
                total=len(labels),
                labels=labels,
                distribution=distribution,
            )

        except Exception as e:
            wallet_labels_logger.error(f"Validated labels query failed: {e}")
            raise GraphQLError(f"Query failed: {e}")

    def resolve_investigation_wallets(self, info, investigation_id=None, role=None):
        session = info.context.get('session')
        if not session:
            raise GraphQLError("Database session not found")

        try:
            query = session.query(InvestigationWallet)
            if investigation_id:
                query = query.filter(InvestigationWallet.investigation_id == investigation_id)
            if role:
                query = query.filter(InvestigationWallet.role == role)

            records = query.all()

            return [
                InvestigationWalletType(
                    address=r.address,
                    chain_id=r.chain_id,
                    investigation_id=r.investigation_id,
                    role=r.role,
                    depth=r.depth,
                    total_received=r.total_received,
                    total_sent=r.total_sent,
                    is_flagged=r.is_flagged,
                )
                for r in records
            ]

        except Exception as e:
            wallet_labels_logger.error(f"Investigation wallets query failed: {e}")
            raise GraphQLError(f"Query failed: {e}")


schema = graphene.Schema(query=Query)
