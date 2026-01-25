#erc20models.py
import logging
import os
from sqlalchemy import Column, Date, Float, String, TIMESTAMP, Integer, ForeignKey, BigInteger, UniqueConstraint, Index, inspect, Boolean, Text
from sqlalchemy.ext.declarative import declarative_base, declared_attr
from sqlalchemy.orm import relationship, backref
from sqlalchemy.exc import ProgrammingError, IntegrityError
from utils.logging_config import setup_logging
from datetime import datetime

erc20models_logger = setup_logging('erc20models.log')

Base = declarative_base()


# ============================================================================
# LABEL SYSTEM MODELS
# ============================================================================

class LabelType(Base):
    """Predefined label types for wallet classification"""
    __tablename__ = 'label_type'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True, index=True)  # e.g., 'exchange', 'bridge', 'mixer'
    description = Column(String(255))
    color = Column(String(7), default='#808080')  # Hex color for UI display
    priority = Column(Integer, default=0)  # Higher priority labels shown first
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Relationship to wallet labels
    wallet_labels = relationship("WalletLabel", back_populates="label_type_rel")


class WalletLabel(Base):
    """Labels assigned to wallet addresses (from API import or manual)"""
    __tablename__ = 'wallet_label'
    
    id = Column(Integer, primary_key=True)
    address = Column(String(42), nullable=False, index=True)  # Ethereum address
    chain_id = Column(Integer, nullable=False, index=True)  # 1=ETH, 56=BSC, 137=POL, 8453=BASE
    label = Column(String(100), nullable=False, index=True)  # e.g., 'Binance 14', 'Polygon Bridge'
    label_type = Column(String(50), ForeignKey('label_type.name'), nullable=True, index=True)  # e.g., 'exchange', 'bridge'
    name_tag = Column(String(255))  # Human readable name from etherscan
    source = Column(String(20), nullable=False, default='manual')  # 'api', 'manual', 'ml'
    confidence = Column(Float, default=1.0)  # ML confidence score (1.0 for manual/api)
    is_trusted = Column(Boolean, default=False)  # Validated by analyst
    validated_by = Column(String(100))  # Username who validated
    validated_at = Column(TIMESTAMP)
    notes = Column(Text)  # Analyst notes
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship
    label_type_rel = relationship("LabelType", back_populates="wallet_labels")
    
    __table_args__ = (
        UniqueConstraint('address', 'chain_id', 'label', name='wallet_label_unique'),
        Index('ix_wallet_label_address_chain', 'address', 'chain_id'),
    )


class KnownBridge(Base):
    """Known bridge contract addresses for cross-chain tracking"""
    __tablename__ = 'known_bridge'
    
    id = Column(Integer, primary_key=True)
    address = Column(String(42), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, index=True)
    protocol = Column(String(50), nullable=False)  # e.g., 'polygon_bridge', 'wormhole', 'stargate'
    direction = Column(String(20))  # e.g., 'ETH→POL', 'multi'
    name = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('address', 'chain_id', name='known_bridge_unique'),
    )


# Chain ID mapping helper
CHAIN_ID_TO_TRIGRAM = {
    1: 'ETH',
    56: 'BSC',
    137: 'POL',
    8453: 'BASE',
}

TRIGRAM_TO_CHAIN_ID = {v: k for k, v in CHAIN_ID_TO_TRIGRAM.items()}


# ============================================================================
# INVESTIGATION MODELS (Forensic Case Management)
# ============================================================================

class Investigation(Base):
    """Forensic investigation case - tracks hack/fraud incidents"""
    __tablename__ = 'investigation'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(20), default='open')  # 'open', 'in_progress', 'closed', 'archived'
    incident_date = Column(TIMESTAMP)  # When the hack/fraud occurred
    reported_loss_usd = Column(Float)  # Estimated loss in USD
    created_by = Column(String(100))
    assigned_to = Column(String(100))
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(TIMESTAMP)
    notes = Column(Text)
    
    # Relationships
    wallets = relationship("InvestigationWallet", back_populates="investigation", cascade="all, delete-orphan")
    tokens = relationship("InvestigationToken", back_populates="investigation", cascade="all, delete-orphan")


class InvestigationWallet(Base):
    """Wallets linked to an investigation"""
    __tablename__ = 'investigation_wallet'
    
    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey('investigation.id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(42), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, default=1)
    role = Column(String(30), nullable=False, default='related')  # 'victim', 'attacker', 'related', 'exchange', 'bridge'
    depth = Column(Integer, default=0)  # How many hops from original victim (0 = victim wallet)
    parent_address = Column(String(42))  # Which wallet this was traced from
    discovered_at = Column(TIMESTAMP, default=datetime.utcnow)
    last_activity = Column(TIMESTAMP)
    total_received = Column(Float, default=0.0)
    total_sent = Column(Float, default=0.0)
    is_flagged = Column(Boolean, default=False)  # Analyst flagged as important
    notes = Column(Text)
    
    # Relationship
    investigation = relationship("Investigation", back_populates="wallets")
    
    __table_args__ = (
        UniqueConstraint('investigation_id', 'address', 'chain_id', name='investigation_wallet_unique'),
        Index('ix_inv_wallet_address', 'address'),
    )


class InvestigationToken(Base):
    """Tokens being tracked in an investigation"""
    __tablename__ = 'investigation_token'
    
    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey('investigation.id', ondelete='CASCADE'), nullable=False, index=True)
    contract_address = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=False, default=1)
    symbol = Column(String(20))
    stolen_amount = Column(Float)  # Amount stolen of this token
    
    # Relationship
    investigation = relationship("Investigation", back_populates="tokens")
    
    __table_args__ = (
        UniqueConstraint('investigation_id', 'contract_address', 'chain_id', name='investigation_token_unique'),
    )


# ============================================================================
# WALLET SCORING (ML Classification Results)
# ============================================================================

class WalletScore(Base):
    """ML-generated wallet classification scores"""
    __tablename__ = 'wallet_score'
    
    id = Column(Integer, primary_key=True)
    address = Column(String(42), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, default=1)
    
    # Classification scores (0-1 probability for each type)
    score_exchange = Column(Float, default=0.0)
    score_bridge = Column(Float, default=0.0)
    score_mixer = Column(Float, default=0.0)
    score_defi = Column(Float, default=0.0)
    score_whale = Column(Float, default=0.0)
    score_bot = Column(Float, default=0.0)
    
    # Best prediction
    predicted_type = Column(String(30))  # Highest scoring type
    confidence = Column(Float)  # Score of predicted type
    
    # Clustering info
    cluster_id = Column(Integer)  # K-means cluster assignment
    is_anomaly = Column(Boolean, default=False)  # DBSCAN outlier detection
    anomaly_score = Column(Float)  # Distance from cluster center
    
    # Feature values used for scoring (for explainability)
    feature_tx_count = Column(Integer)
    feature_unique_counterparties = Column(Integer)
    feature_avg_tx_value = Column(Float)
    feature_max_tx_value = Column(Float)
    feature_in_out_ratio = Column(Float)  # incoming/outgoing tx ratio
    feature_active_days = Column(Integer)
    
    # Metadata
    model_version = Column(String(50))
    scored_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('address', 'chain_id', name='wallet_score_unique'),
        Index('ix_wallet_score_address', 'address'),
    )


# ============================================================================
# AUDIT TRAIL (AI Regulation Compliance)
# ============================================================================

class AuditLog(Base):
    """
    Audit trail for all system actions.
    Required for AI regulation compliance (EU AI Act, etc.)
    """
    __tablename__ = 'audit_log'
    
    id = Column(Integer, primary_key=True)
    
    # Timestamp (first for sorting)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow)
    
    # Action metadata
    action_type = Column(String(50), nullable=False)  # classification, investigation, validation, model, label, alert, report
    action_subtype = Column(String(50))  # create, update, delete, predict, explain
    
    # Actor information
    user_id = Column(String(100))  # User who performed action
    user_role = Column(String(50))  # analyst, admin, system
    ip_address = Column(String(45))  # IPv4/IPv6
    
    # Target information (wallet)
    wallet_address = Column(String(42))  # For wallet-related actions
    chain_id = Column(Integer)
    
    # Context
    investigation_id = Column(Integer, ForeignKey('investigation.id'), nullable=True)
    
    # Classification result
    predicted_type = Column(String(50))  # exchange, bridge, mixer, whale, etc.
    confidence = Column(Float)  # Confidence score 0-1
    
    # Model information (for ML decisions)
    model_version = Column(String(50))
    mlflow_run_id = Column(String(100))  # MLflow run ID
    
    # SHAP explanation (for explainability)
    shap_values = Column(JSON)  # SHAP feature contributions
    
    # Validation status
    validation_status = Column(String(20), default='pending')  # pending, confirmed, rejected
    validated_by = Column(String(100))
    validated_at = Column(TIMESTAMP)
    
    # Notes
    notes = Column(Text)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    
    __table_args__ = (
        Index('ix_audit_log_action_type', 'action_type'),
        Index('ix_audit_log_timestamp', 'timestamp'),
        Index('ix_audit_log_investigation', 'investigation_id'),
        Index('ix_audit_log_wallet', 'wallet_address'),
    )


class ModelMetadata(Base):
    """
    Model metadata and configuration for production models.
    Tracks model lifecycle and governance.
    """
    __tablename__ = 'model_metadata'
    
    id = Column(Integer, primary_key=True)
    
    # Model identification
    model_name = Column(String(100), nullable=False)
    version = Column(String(50), nullable=False)
    model_type = Column(String(50))  # xgboost, random_forest, etc.
    mlflow_run_id = Column(String(100))  # MLflow run ID
    
    # Status
    is_production = Column(Boolean, default=False)
    is_validated = Column(Boolean, default=False)
    
    # Performance metrics
    accuracy = Column(Float)
    f1_score = Column(Float)
    precision = Column(Float)
    recall = Column(Float)
    roc_auc = Column(Float)
    
    # Training info
    n_samples = Column(Integer)
    n_features = Column(Integer)
    feature_names = Column(JSON)  # List of features used
    hyperparameters = Column(JSON)  # Model hyperparameters
    
    # SHAP feature importance
    shap_importance = Column(JSON)  # Feature importance from SHAP
    
    # Decision threshold
    threshold = Column(Float, default=0.5)
    
    # Governance
    approved_by = Column(String(100))
    approved_at = Column(TIMESTAMP)
    review_notes = Column(Text)
    
    # Drift monitoring
    last_drift_check = Column(TIMESTAMP)
    drift_detected = Column(Boolean, default=False)
    drift_score = Column(Float)
    
    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('model_name', 'version', name='model_metadata_unique'),
        Index('ix_model_metadata_production', 'model_name', 'is_production'),
    )


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
        return relationship(block_event_class_name, backref=unique_backref_name)

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
                'block_event': relationship(block_class_name, backref=f'{class_name.lower()}_backref'),
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
        


