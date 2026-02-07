# combined_schema.py
"""
Combined GraphQL schema merging all domain schemas.
This is the single entry point for the /graphql endpoint.
"""
import graphene

from graphql_app.schemas.fetch_erc20_transfer_history_schema import Query as ERC20TransferQuery
from graphql_app.schemas.fetch_token_price_history_schema import Query as TokenPriceQuery
from graphql_app.schemas.fetch_last_token_price_history_schema import Query as LastTokenPriceQuery
from graphql_app.schemas.wallet_features_schema import Query as WalletFeaturesQuery
from graphql_app.schemas.wallet_labels_schema import Query as WalletLabelsQuery


class CombinedQuery(
    ERC20TransferQuery,
    TokenPriceQuery,
    LastTokenPriceQuery,
    WalletFeaturesQuery,
    WalletLabelsQuery,
    graphene.ObjectType,
):
    """All Bubble GraphQL queries — unified schema."""
    pass


combined_schema = graphene.Schema(query=CombinedQuery)
