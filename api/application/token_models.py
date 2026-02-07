# api/application/token_models.py
"""
Token & ERC20 transfer models — tokens, price history, dynamic block/transfer event classes.
"""
import logging
from sqlalchemy import (
    Column, String, Integer, Float, BigInteger, TIMESTAMP, Date,
    ForeignKey, UniqueConstraint, Index, inspect
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, backref
from sqlalchemy.exc import ProgrammingError

from api.application.base import Base, erc20models_logger


class Token(Base):
    __tablename__ = 'token'
    id = Column(String)
    symbol = Column(String, nullable=False, index=True)
    name = Column(String, nullable=False)
    asset_platform_id = Column(String, nullable=False)
    contract_address = Column(String, nullable=False, primary_key=True)
    trigram = Column(String, nullable=False, index=True)
    history_tag = Column(Integer)
    transfert_erc20_tag = Column(Integer)
    price_history = relationship("TokenPriceHistory", backref="token")
    __table_args__ = (UniqueConstraint('symbol', 'asset_platform_id', name='token_uc'),)


class TokenPriceHistory(Base):
    __tablename__ = 'token_price_history'
    id = Column(Integer, primary_key=True)
    contract_address = Column(String, ForeignKey('token.contract_address'), nullable=False, index=True)
    date = Column(Date, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False)
    price = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)
    market_cap = Column(Float, nullable=False)
    source = Column(String, nullable=False)
    __table_args__ = (
        UniqueConstraint('contract_address', 'timestamp', 'price', name='token_price_history_uc'),
        Index('ix_tph_contract_date', 'contract_address', 'date'),
    )


class BlockTransferEvent(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)
    block_number = Column(BigInteger, nullable=False, index=True)
    hash = Column(String, nullable=False, unique=True, index=True)
    block_hash = Column(String, nullable=False, index=True)
    confirmations = Column(Integer, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False)
    type = Column(String)
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'block_transfer_event',
    }


class ERC20TransferEventBase(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)
    hash = Column(String, nullable=False, index=True)
    nonce = Column(Integer, nullable=False)
    from_contract_address = Column(String, nullable=False)
    to_contract_address = Column(String, nullable=False, index=True)
    value = Column(Float, nullable=False)
    transaction_index = Column(Integer, nullable=False)
    type = Column(String)
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'erc20_transfer_event',
    }

    @declared_attr
    def block_event_hash(cls):
        trigram = cls.__name__.split('ERC20TransferEvent')[0][-3:]
        return Column(String, ForeignKey(f'{trigram.lower()}_block_transfer_event.hash'))

    @declared_attr
    def block_event(cls):
        trigram = cls.__name__.split('ERC20TransferEvent')[0][-3:]
        block_event_class_name = f'{trigram.capitalize()}BlockTransferEvent'
        unique_backref_name = f'{cls.__name__.lower()}_backref'
        return relationship(block_event_class_name, backref=unique_backref_name)


# ── Dynamic Class Generators ──────────────────────────────

# Module-level registry for dynamically generated classes
_dynamic_classes = {}


def generate_block_transfer_event_classes(session):
    trigrams = session.query(Token.trigram).distinct().all()
    for trigram_tuple in trigrams:
        trigram = trigram_tuple[0]
        class_name = f"{trigram.capitalize()}BlockTransferEvent"
        if class_name not in globals():
            cls = type(class_name, (BlockTransferEvent,), {
                '__tablename__': f'{trigram.lower()}_block_transfer_event',
                '__mapper_args__': {'polymorphic_identity': trigram},
            })
            globals()[class_name] = cls
            _dynamic_classes[class_name] = cls
            erc20models_logger.info(f"{class_name} class has been added and {trigram.lower()}_block_transfer_event table has been created")
        else:
            erc20models_logger.info(f"{class_name} class already exists and {trigram.lower()}_block_transfer_event table already exists")


def generate_erc20_classes(session):
    token_trigrams = session.query(Token.symbol, Token.trigram).distinct().all()
    for symbol, trigram in token_trigrams:
        block_class_name = f"{trigram.capitalize()}BlockTransferEvent"
        block_class = globals().get(block_class_name)

        class_name = f'{symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent'

        if class_name not in globals():
            if block_class is None:
                erc20models_logger.error(f"Block class {block_class_name} not found for {class_name}.")
                continue

            cls = type(class_name, (ERC20TransferEventBase,), {
                '__tablename__': f'{symbol.lower()}_{trigram.lower()}_erc20_transfer_event',
                'block_event_hash': Column(String, ForeignKey(f'{trigram.lower()}_block_transfer_event.hash'), nullable=False, index=True),
                'block_event': relationship(block_class_name, backref=f'{class_name.lower()}_backref'),
                '__mapper_args__': {'polymorphic_identity': f'{symbol}_{trigram}'},
            })
            globals()[class_name] = cls
            _dynamic_classes[class_name] = cls
            erc20models_logger.info(f"{class_name} has been added and {symbol.lower()}_{trigram.lower()}_erc20_transfer_event table has been created")
        else:
            erc20models_logger.info(f"{class_name} already exists.")


def adjust_erc20_transfer_event_relationships():
    for name, cls in globals().items():
        if isinstance(cls, type) and issubclass(cls, ERC20TransferEventBase) and cls is not ERC20TransferEventBase:
            trigram_part = name.split('ERC20TransferEvent')[0]
            trigram = trigram_part[-3:]

            block_event_class_name = f"{trigram}BlockTransferEvent"
            block_event_class = globals().get(block_event_class_name)

            if block_event_class:
                setattr(cls, 'block_event', relationship(
                    block_event_class_name,
                    primaryjoin=f"{cls.__name__}.block_event_hash=={block_event_class_name}.hash",
                    backref="erc20_transfers",
                    cascade="all, delete-orphan"
                ))
                erc20models_logger.info(f"Relationship between {block_event_class_name} and {name} has been established.")
            else:
                erc20models_logger.info(f"Warning: BlockTransferEvent class {block_event_class_name} not found for {name}. Relationship not established.")


def apply_dynamic_unique_constraints():
    for table_name, table in Base.metadata.tables.items():
        if table_name.endswith('_erc20_transfer_event'):
            constraint = UniqueConstraint('hash', 'from_contract_address', 'to_contract_address', 'value', name=f'{table_name}_unique')
            table.append_constraint(constraint)

        if table_name.endswith('_block_transfer_event'):
            constraint = UniqueConstraint('block_number', 'hash', name=f'{table_name}_unique')
            table.append_constraint(constraint)

        erc20models_logger.info(f"Unique constraints for table {table_name} has been added.")


def apply_dynamic_indexes(session):
    metadata = Base.metadata
    metadata.reflect(session.get_bind())
    inspector = inspect(session.get_bind())

    for table_name, table in metadata.tables.items():
        existing_indexes = [index['name'] for index in inspector.get_indexes(table_name)]
        erc20models_logger.info(f"exsting indexes {existing_indexes} for {table_name}")

        indexes_to_create = [
            ('block_hash_idx', ['block_number', 'hash']) if table_name.endswith('_block_transfer_event') else None,
            ('from_to_idx', ['from_contract_address', 'to_contract_address']) if table_name.endswith('_erc20_transfer_event') else None,
            ('hash_from_to_idx', ['hash', 'from_contract_address', 'to_contract_address']) if table_name.endswith('_erc20_transfer_event') else None,
        ]
        erc20models_logger.info(f"indexes to create {indexes_to_create} for {table_name}")

        for index_name_suffix, columns in filter(None, indexes_to_create):
            index_name = f'{table_name}_{index_name_suffix}'
            if index_name not in existing_indexes:
                try:
                    index = Index(index_name, *[table.c[column] for column in columns])
                    index.create(session.get_bind())
                    erc20models_logger.info(f"Index {index_name} created for {table_name}")
                except ProgrammingError as e:
                    erc20models_logger.error(f"Failed to create index {index_name} for {table_name}: {e}")


# ── Helper Functions ──────────────────────────────────────

def get_transfer_event_class(symbol, trigram):
    class_name = f"{symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent"
    return globals().get(class_name, None)


def get_block_transfer_event_class(trigram):
    class_name = f"{trigram.capitalize()}BlockTransferEvent"
    return globals().get(class_name, None)
