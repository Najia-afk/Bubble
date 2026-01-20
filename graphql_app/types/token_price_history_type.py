#token_price_history_type.py
from graphene_sqlalchemy import SQLAlchemyObjectType
import graphene
from api.application.erc20models import TokenPriceHistory

class TokenPriceHistoryType(SQLAlchemyObjectType):
    class Meta:
        model = TokenPriceHistory
