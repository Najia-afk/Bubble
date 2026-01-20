#erc20models.py
import logging
import os
from sqlalchemy import Column, Date, Float, String, TIMESTAMP, Integer, ForeignKey, BigInteger, UniqueConstraint, Index, inspect
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import relationship, backref
from sqlalchemy.exc import ProgrammingError, IntegrityError
from utils.logging_config import setup_logging

erc20models_logger = setup_logging('erc20models.log')

Base = declarative_base()

class Token(Base):
    __tablename__ = 'token'
    id = Column(String)
    symbol = Column(String, nullable=False, index=True)  # Added index for faster queries on symbol
    name = Column(String, nullable=False)
    asset_platform_id = Column(String, nullable=False)
    contract_address = Column(String, nullable=False, primary_key=True)
    trigram = Column(String, nullable=False, index=True)  # Added index for faster queries on trigram
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
    __table_args__ = (UniqueConstraint('contract_address', 'timestamp', 'price', name='token_price_history_uc'),)  # Composite unique constraint

class BlockTransferEvent(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)
    block_number = Column(BigInteger, nullable=False, index=True)  # Added index for block_number
    hash = Column(String, nullable=False, unique=True, index=True)  # Ensuring hash uniqueness
    block_hash = Column(String, nullable=False, index=True)
    confirmations = Column(Integer, nullable=False)
    timestamp = Column(TIMESTAMP, nullable=False)
    # Polymorphic configuration
    type = Column(String)
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'block_transfer_event',
    }  # Ensuring uniqueness for the combination

# Use abstract base class for ERC20TransferEvent with blockchain trigram
class ERC20TransferEventBase(Base):
    __abstract__ = True
    id = Column(Integer, primary_key=True)
    hash = Column(String, nullable=False, index=True)
    nonce = Column(Integer, nullable=False)
    from_contract_address = Column(String, nullable=False)
    to_contract_address = Column(String, nullable=False, index=True)
    value = Column(Float, nullable=False)
    transaction_index = Column(Integer, nullable=False)
    # Polymorphic configuration
    type = Column(String)
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'erc20_transfer_event',
    }
    @declared_attr
    def block_event_hash(cls):
        trigram = cls.__name__.split('ERC20TransferEvent')[0][-3:]  # Extracts 'Pol' from 'GhstPolyERC20TransferEvent'
        return Column(String, ForeignKey(f'{trigram.lower()}_block_transfer_event.hash'))

    @declared_attr
    def block_event(cls):
        trigram = cls.__name__.split('ERC20TransferEvent')[0][-3:]
        block_event_class_name = f'{trigram.capitalize()}BlockTransferEvent'
        # Generate a unique backref name using the class name to avoid conflicts
        unique_backref_name = f'{cls.__name__.lower()}_backref'
        return relationship(block_event_class_name, backref=backref(unique_backref_name, cascade="all, delete-orphan"))

def generate_block_transfer_event_classes(session):
    trigrams = session.query(Token.trigram).distinct().all()
    for trigram_tuple in trigrams:
        trigram = trigram_tuple[0]  # Unpacking the tuple
        class_name = f"{trigram.capitalize()}BlockTransferEvent"
        if class_name not in globals():
            globals()[class_name] = type(class_name, (BlockTransferEvent,), {
                '__tablename__': f'{trigram.lower()}_block_transfer_event',
                '__mapper_args__': {'polymorphic_identity': trigram},
            })
            erc20models_logger.info(f"{class_name} class has been added and {trigram.lower()}_block_transfer_event table has been created")
        else:
            erc20models_logger.info(f"{class_name} class already exists and {trigram.lower()}_block_transfer_event table already exists")



def generate_erc20_classes(session):
    token_trigrams = session.query(Token.symbol, Token.trigram).distinct().all()
    for symbol, trigram in token_trigrams:
        block_class_name = f"{trigram.capitalize()}BlockTransferEvent"
        block_class = globals().get(block_class_name)

        class_name = f'{symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent'
        
        if class_name not in globals():  # Check if class already exists
            # Check if the block class exists before proceeding
            if block_class is None:
                erc20models_logger.error(f"Block class {block_class_name} not found for {class_name}.")
                continue  # Skip to the next iteration

            # Dynamically create the ERC20TransferEvent class if not exists
            globals()[class_name] = type(class_name, (ERC20TransferEventBase,), {
                '__tablename__': f'{symbol.lower()}_{trigram.lower()}_erc20_transfer_event',
                'block_event_hash': Column(String, ForeignKey(f'{trigram.lower()}_block_transfer_event.hash'), nullable=False, index=True),
                'block_event': relationship(block_class_name, backref=backref(f'{class_name.lower()}_backref', cascade="all, delete-orphan")),
                '__mapper_args__': {'polymorphic_identity': f'{symbol}_{trigram}'},
            })
            erc20models_logger.info(f"{class_name} has been added and {symbol.lower()}_{trigram.lower()}_erc20_transfer_event table has been created")
        else:
            erc20models_logger.info(f"{class_name} already exists.")


def adjust_erc20_transfer_event_relationships():
    # Iterate through all dynamically created ERC20TransferEvent classes
    for name, cls in globals().items():
        # Ensure cls is a subclass of ERC20TransferEventBase but not ERC20TransferEventBase itself
        if isinstance(cls, type) and issubclass(cls, ERC20TransferEventBase) and cls is not ERC20TransferEventBase:
            # Extract trigram from class name, assuming naming convention like "ETHBlockTransferEvent"
            trigram_part = name.split('ERC20TransferEvent')[0]  # This assumes class names like "EthERC20TransferEvent"
            trigram = trigram_part[-3:]  # Adjust based on your naming convention

            # Attempt to find the corresponding BlockTransferEvent class for the trigram
            block_event_class_name = f"{trigram}BlockTransferEvent"
            block_event_class = globals().get(block_event_class_name)

            if block_event_class:
                # Establish the dynamic relationship if the block event class exists
                setattr(cls, 'block_event', relationship(
                    block_event_class_name,
                    primaryjoin=f"{cls.__name__}.block_event_hash=={block_event_class_name}.hash",
                    backref="erc20_transfers",
                    cascade="all, delete-orphan"
                ))
                erc20models_logger.info(f"Relationship between {block_event_class_name} and {name} has been established.")
            else:
                # If the corresponding block event class is not found, log a warning
                erc20models_logger.info(f"Warning: BlockTransferEvent class {block_event_class_name} not found for {name}. Relationship not established.")

# After all classes have been defined and before Base.metadata.create_all() is called

def apply_dynamic_unique_constraints():
    # Iterate through all tables defined in Base.metadata
    for table_name, table in Base.metadata.tables.items():
        # Apply unique constraint to ERC20TransferEvent tables
        if table_name.endswith('_erc20_transfer_event'):
            # Define the unique constraint for this table
            constraint = UniqueConstraint('hash', 'from_contract_address', 'to_contract_address', 'value', name=f'{table_name}_unique')
            # Append the constraint to the table
            table.append_constraint(constraint)
            
        
        # Apply unique constraint to BlockTransferEvent tables if needed
        if table_name.endswith('_block_transfer_event'):
            # Define the unique constraint for this table
            constraint = UniqueConstraint('block_number', 'hash', name=f'{table_name}_unique')
            # Append the constraint to the table
            table.append_constraint(constraint)
        
        erc20models_logger.info(f"Unique constraints for table {table_name} has been added.")


def apply_dynamic_indexes(session):
    # Use reflection to load information about existing tables and indexes
    metadata = Base.metadata
    metadata.reflect(session.get_bind())
    inspector = inspect(session.get_bind())

    for table_name, table in metadata.tables.items():
        # Retrieve existing index names for the table
        existing_indexes = [index['name'] for index in inspector.get_indexes(table_name)]
        erc20models_logger.info(f"exsting indexes {existing_indexes} for {table_name}")
        # Define and create indexes if they don't exist
        indexes_to_create = [
            ('block_hash_idx', ['block_number', 'hash']) if table_name.endswith('_block_transfer_event') else None,
            ('from_to_idx', ['from_contract_address', 'to_contract_address']) if table_name.endswith('_erc20_transfer_event') else None,
            ('hash_from_to_idx', ['hash','from_contract_address', 'to_contract_address']) if table_name.endswith('_erc20_transfer_event') else None,
        ]
        erc20models_logger.info(f"indexes to create {indexes_to_create} for {table_name}")
        for index_name_suffix, columns in filter(None, indexes_to_create):
            index_name = f'{table_name}_{index_name_suffix}'
            if index_name not in existing_indexes:
                try:
                    # Construct and create the index
                    index = Index(index_name, *[table.c[column] for column in columns])
                    index.create(session.get_bind())
                    erc20models_logger.info(f"Index {index_name} created for {table_name}")
                except ProgrammingError as e:
                    erc20models_logger.error(f"Failed to create index {index_name} for {table_name}: {e}")

# Helper functions to retrieve dynamic class definitions
def get_transfer_event_class(symbol, trigram):
    class_name = f"{symbol.capitalize()}{trigram.capitalize()}ERC20TransferEvent"
    return globals().get(class_name, None)

def get_block_transfer_event_class(trigram):
    class_name = f"{trigram.capitalize()}BlockTransferEvent"
    return globals().get(class_name, None)
        


