#fetch_last_token_price_history_schema.py
import graphene
import logging
from graphene_sqlalchemy import SQLAlchemyObjectType
from sqlalchemy.sql.expression import or_
from api.application.erc20models import Token, TokenPriceHistory
from utils.logging_config import setup_logging
from graphql import GraphQLError

# Initialize logging for this module
last_schema_logger = setup_logging('graphql_operations.log', log_level=logging.INFO)

class TokenWithPriceHistoryType(graphene.ObjectType):
    id = graphene.ID()
    symbol = graphene.String()
    contract_address = graphene.String()
    date = graphene.DateTime()
    price = graphene.Float()
    volume = graphene.Float()
    market_cap = graphene.Float()
    source = graphene.String()

class Query(graphene.ObjectType):
    last_token_price_history = graphene.Field(
        graphene.List(TokenWithPriceHistoryType),
        symbols=graphene.List(graphene.String, required=True),
        limit=graphene.Int(default_value=1)
    )

    def resolve_last_token_price_history(self, info, symbols, limit):
        session = info.context.get('session')
        if not session:
            last_schema_logger.error("Database session not found in Flask's global context")
            raise GraphQLError("Database session not found")

        results = []
        for symbol in symbols:
            token_info = session.query(
                Token.symbol,
                TokenPriceHistory.date,
                TokenPriceHistory.price,
                TokenPriceHistory.volume,
                TokenPriceHistory.market_cap,
                TokenPriceHistory.source
            ).join(TokenPriceHistory, Token.contract_address == TokenPriceHistory.contract_address
            ).filter(Token.symbol == symbol
            ).order_by(TokenPriceHistory.date.desc()
            ).limit(limit).all()

            # Convert query results into TokenWithPriceHistoryType instances
            for info in token_info:
                result = TokenWithPriceHistoryType(
                    symbol=info[0],
                    date=info[1],
                    price=info[2],
                    volume=info[3],
                    market_cap=info[4],
                    source=info[5],
                )
                results.append(result)

        return results


schema = graphene.Schema(query=Query)
