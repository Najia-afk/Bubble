from graphene_sqlalchemy import SQLAlchemyObjectType
from api.application.erc20models import Base, ERC20TransferEventBase, BlockTransferEvent  # Ensure correct import paths
from sqlalchemy.orm import Session
import graphene
import sys
from api.application.erc20models import generate_block_transfer_event_classes, generate_erc20_classes, adjust_erc20_transfer_event_relationships
from utils.database import get_db_session

class CustomSQLAlchemyObjectType(SQLAlchemyObjectType):
    """
    This base class ensures all dynamically created types have the interfaces needed.
    """
    class Meta:
        abstract = True

def generate_erc20_and_block_transfer_event_types():
    session: Session = get_db_session()
    generate_block_transfer_event_classes(session)
    generate_erc20_classes(session)
    adjust_erc20_transfer_event_relationships()

    # Dynamically create ERC20TransferEvent types
    for name, cls in globals().items():
        if isinstance(cls, type) and issubclass(cls, ERC20TransferEventBase) and cls is not ERC20TransferEventBase:
            DynamicTypeMeta = {'model': cls, 'interfaces': (graphene.relay.Node,)}
            dynamic_type = type(f"{name}Type", (CustomSQLAlchemyObjectType,), {'Meta': DynamicTypeMeta})
            setattr(sys.modules[__name__], f"{name}Type", dynamic_type)

    # Dynamically create BlockTransferEvent types for each trigram
    for trigram in session.query(BlockTransferEvent.trigram).distinct():
        trigram_specific_class_name = f"{trigram}BlockTransferEvent"
        trigram_specific_class = globals().get(trigram_specific_class_name)
        if trigram_specific_class:
            BlockTransferEventTypeMeta = {'model': trigram_specific_class, 'interfaces': (graphene.relay.Node,)}
            block_transfer_event_type = type(f"{trigram_specific_class_name}Type", (CustomSQLAlchemyObjectType,), {'Meta': BlockTransferEventTypeMeta})
            setattr(sys.modules[__name__], f"{trigram_specific_class_name}Type", block_transfer_event_type)

generate_erc20_and_block_transfer_event_types()
