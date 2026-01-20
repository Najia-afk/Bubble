# fetch_erc20_transfer_history_schema.py
import graphene
import logging
import base64
from sqlalchemy.orm import Session
from graphene_sqlalchemy import SQLAlchemyObjectType
from flask import g
from api.application.erc20models import Token, Base  # Ensure Base is imported from erc20models
import api.application.erc20models as erc20models  # For dynamic table creation functions
from api.application.erc20models import get_transfer_event_class, get_block_transfer_event_class
from utils.logging_config import setup_logging
from graphql import GraphQLError

erc20_transfer_logger = setup_logging('erc20_transfer_history_schema.log', log_level=logging.INFO)


class ERC20TransferEventQuery(graphene.ObjectType):
    block_number = graphene.Int()
    hash = graphene.String()
    confirmations = graphene.Int()
    timestamp = graphene.String()
    transaction_index = graphene.Int()  # Assuming it's numeric
    from_contract_address = graphene.String()
    to_contract_address = graphene.String()
    value = graphene.Float()
    token_symbol = graphene.String()


class ERC20TransferEventEdge(graphene.ObjectType):
    node = graphene.Field(ERC20TransferEventQuery)
    cursor = graphene.String(description="Cursor for pagination")

class PageInfo(graphene.ObjectType):
    endCursor = graphene.String(description="Cursor to the last item in edges")
    hasNextPage = graphene.Boolean(description="Indicates if there are more items") 

class ERC20TransferEventConnection(graphene.ObjectType):
    pageInfo = graphene.Field(PageInfo, description="Information about pagination")
    edges = graphene.List(ERC20TransferEventEdge, description="List of edges")



class Query(graphene.ObjectType):
    erc20_transfer_events = graphene.Field(
        ERC20TransferEventConnection,
        trigram=graphene.String(required=True),
        symbols=graphene.List(graphene.String, required=True),
        startBlock=graphene.Int(required=True),
        endBlock=graphene.Int(required=True),
        after=graphene.String(default_value=None, description="Cursor for the next fetch"),
        limit=graphene.Int(default_value=10000, description="Number of items to fetch")
    )

    def resolve_erc20_transfer_events(self, info, trigram, symbols, startBlock, endBlock, after=None, limit=100000):
        session = info.context.get('session')
        if not session:
            erc20_transfer_logger.error("Database session not found")
            raise GraphQLError("Database session not found")

        connection = ERC20TransferEventConnection(pageInfo=PageInfo(hasNextPage=False, endCursor=None), edges=[])
        all_results = []
        for symbol in symbols:
            DynamicERC20TransferEvent = get_transfer_event_class(symbol, trigram)
            BlockEventClass = get_block_transfer_event_class(trigram)
            if not DynamicERC20TransferEvent or not BlockEventClass:
                erc20_transfer_logger.warning(f"No dynamic class found for {symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent or {trigram.capitalize()}BlockTransferEvent not found.")
                continue  # Skip to the next symbol

            query = session.query(
                BlockEventClass.block_number,
                DynamicERC20TransferEvent.hash.label("hash"),
                DynamicERC20TransferEvent.transaction_index,
                DynamicERC20TransferEvent.from_contract_address,
                DynamicERC20TransferEvent.to_contract_address,
                DynamicERC20TransferEvent.value,
                BlockEventClass.confirmations,
                BlockEventClass.timestamp
                
            ).join(
                BlockEventClass, DynamicERC20TransferEvent.block_event_hash == BlockEventClass.hash
            ).filter(
                BlockEventClass.block_number >= startBlock, BlockEventClass.block_number <= endBlock
            ).order_by(BlockEventClass.block_number.asc())

            if after:
                after_block_number = base64.b64decode(after).decode("utf-8")
                query = query.filter(BlockEventClass.block_number > after_block_number)

            query = query.order_by(BlockEventClass.block_number.asc()).limit(limit + 1)
            items = query.all()

            edges = [
                ERC20TransferEventEdge(
                    node=ERC20TransferEventQuery(
                        block_number=item.block_number,
                        hash=item.hash,
                        token_symbol=symbol,
                        transaction_index=item.transaction_index,
                        from_contract_address=item.from_contract_address,
                        to_contract_address=item.to_contract_address,
                        value=item.value,
                        confirmations=item.confirmations,
                        timestamp=str(item.timestamp)
                    ),
                    cursor=base64.b64encode(str(item.block_number).encode("utf-8")).decode("utf-8")
                ) for item in items[:limit]
            ]
            hasNextPage = len(items) > limit
            endCursor = edges[-1].cursor if edges else None

            # Build the connection object for each symbol's results
            symbol_connection = ERC20TransferEventConnection(
                pageInfo=PageInfo(hasNextPage=hasNextPage, endCursor=endCursor),
            edges=edges
            )
        
            # Aggregate connections per symbol
            connection.edges.extend(symbol_connection.edges)
            connection.pageInfo.hasNextPage |= symbol_connection.pageInfo.hasNextPage
            connection.pageInfo.endCursor = symbol_connection.pageInfo.endCursor if symbol_connection.pageInfo.hasNextPage else connection.pageInfo.endCursor

        return connection


schema = graphene.Schema(query=Query)

