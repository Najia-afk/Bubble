from graphene_sqlalchemy import SQLAlchemyObjectType
import graphene
from api.application.erc20models import Token

class TokenType(SQLAlchemyObjectType):
    class Meta:
        model = Token
