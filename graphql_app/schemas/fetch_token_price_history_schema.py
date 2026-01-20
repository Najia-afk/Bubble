#fetch_token_price_history_schema.py
import graphene
import logging
from graphene_sqlalchemy import SQLAlchemyObjectType
from sqlalchemy.sql.expression import or_
from api.application.erc20models import Token, TokenPriceHistory
from utils.logging_config import setup_logging
from graphql import GraphQLError

# Initialize logging for this module
price_schema_logger = setup_logging('graphql_operations.log', log_level=logging.INFO)

class TokenPriceEntry(graphene.ObjectType):
    symbol = graphene.String()
    contract_address = graphene.String()
    Date = graphene.DateTime()
    timestamp = graphene.DateTime()
    price = graphene.Float()
    volume = graphene.Float()
    market_cap = graphene.Float()
    source = graphene.String()

class Query(graphene.ObjectType):
    token_price_history = graphene.Field(
        graphene.List(TokenPriceEntry),
        symbols=graphene.List(graphene.String, required=True),
        start_date=graphene.DateTime(),
        end_date=graphene.DateTime(),
        limit=graphene.Int(default_value=1)
    )

    def resolve_token_price_history(self, info, symbols, start_date, end_date, limit):
        session = info.context.get('session')
        if not session:
            price_schema_logger.error("Database session not found in Flask's global context")
            raise GraphQLError("Database session not found")

        query = session.query(
            Token.symbol,
            TokenPriceHistory.contract_address,
            TokenPriceHistory.timestamp,
            TokenPriceHistory.price,
            TokenPriceHistory.volume,
            TokenPriceHistory.market_cap,
            TokenPriceHistory.source
        ).join(TokenPriceHistory, Token.contract_address == TokenPriceHistory.contract_address
        ).filter(
            Token.symbol.in_(symbols),
            TokenPriceHistory.date >= start_date,
            TokenPriceHistory.date <= end_date
        ).order_by(TokenPriceHistory.timestamp.desc()
        ).limit(limit)

        results = [
            TokenPriceEntry(
                symbol=entry[0],
                contract_address=entry[1],
                timestamp=entry[2],
                price=entry[3],
                volume=entry[4],
                market_cap=entry[5],
                source=entry[6]
            ) for entry in query.all()
        ]

        return results


schema = graphene.Schema(query=Query)
