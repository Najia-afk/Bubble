# =============================================================================
# Bubble - Core Database Models
# All entities loaded from DB, initialized from CSV on first run
# =============================================================================

from datetime import datetime
from sqlalchemy import (
    Column, String, Integer, Float, Boolean, Text, JSON, TIMESTAMP,
    ForeignKey, BigInteger, UniqueConstraint, Enum
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
import enum

Base = declarative_base()


# =============================================================================
# ENUMS
# =============================================================================

class CaseStatus(enum.Enum):
    ACTIVE = "active"
    MONITORING = "monitoring"
    CLOSED = "closed"
    ARCHIVED = "archived"


class CaseSeverity(enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WalletRole(enum.Enum):
    THEFT_ORIGIN = "theft_origin"
    ATTACKER = "attacker"
    MIXER = "mixer"
    BRIDGE = "bridge"
    EXCHANGE = "exchange"
    VICTIM = "victim"
    RELATED = "related"


class AlertType(enum.Enum):
    INCOMING = "incoming"
    OUTGOING = "outgoing"
    MIXER = "mixer"
    BRIDGE = "bridge"
    LARGE_TRANSFER = "large_transfer"
    NEW_ACTIVITY = "new_activity"


# =============================================================================
# CHAIN CONFIGURATION
# =============================================================================

class Chain(Base):
    """Blockchain configuration - loaded from chains.csv"""
    __tablename__ = 'chain'

    code = Column(String(10), primary_key=True)  # ETH, POL, BSC, etc.
    name = Column(String(50), nullable=False)
    chain_id = Column(Integer, nullable=False, unique=True)
    native_token = Column(String(10), nullable=False)
    native_decimals = Column(Integer, default=18)
    explorer_name = Column(String(50))
    explorer_api_url = Column(String(255))
    explorer_api_key_env = Column(String(50))
    explorer_rate_limit = Column(Integer, default=5)
    block_time_seconds = Column(Float, default=12.0)
    confirmations_required = Column(Integer, default=12)
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    # Relationships
    mixers = relationship("Mixer", back_populates="chain")
    bridges = relationship("Bridge", back_populates="chain")
    wallets = relationship("MonitoredWallet", back_populates="chain")
    alerts = relationship("Alert", back_populates="chain")


# =============================================================================
# KNOWN ADDRESSES (MIXERS, BRIDGES)
# =============================================================================

class Mixer(Base):
    """Known mixer/tumbler addresses - loaded from mixers.csv"""
    __tablename__ = 'mixer'

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False, index=True)
    chain_code = Column(String(10), ForeignKey('chain.code'), nullable=False)
    protocol = Column(String(50), nullable=False)  # tornado_cash, railgun, etc.
    name = Column(String(100))  # "Tornado Cash 0.1 ETH"
    pool_size = Column(String(20))  # "0.1 ETH", "10 ETH"
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    chain = relationship("Chain", back_populates="mixers")

    __table_args__ = (
        UniqueConstraint('address', 'chain_code', name='mixer_unique'),
    )


class Bridge(Base):
    """Known bridge addresses - loaded from bridges.csv"""
    __tablename__ = 'bridge'

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False, index=True)
    chain_code = Column(String(10), ForeignKey('chain.code'), nullable=False)
    protocol = Column(String(50), nullable=False)  # stargate, wormhole, etc.
    name = Column(String(100))
    direction = Column(String(50))  # "ETH->ARB", "multi"
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    chain = relationship("Chain", back_populates="bridges")

    __table_args__ = (
        UniqueConstraint('address', 'chain_code', name='bridge_unique'),
    )


# =============================================================================
# INVESTIGATION CASES
# =============================================================================

class Case(Base):
    """Investigation case - loaded from cases.csv"""
    __tablename__ = 'investigation_case'

    id = Column(String(50), primary_key=True)  # CASE-2026-001
    title = Column(String(255), nullable=False)
    source = Column(String(50), nullable=False)  # osint, community, internal
    status = Column(String(20), default='active')
    severity = Column(String(20), default='medium')
    date_reported = Column(TIMESTAMP)
    date_incident = Column(TIMESTAMP)
    summary = Column(Text)
    total_stolen_usd = Column(Float)
    victim_count = Column(String(20))  # Can be "100+" etc.
    attack_vector = Column(String(100))
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    wallets = relationship("CaseWallet", back_populates="case", cascade="all, delete-orphan")
    mixer_deposits = relationship("CaseMixerDeposit", back_populates="case", cascade="all, delete-orphan")
    bridge_activities = relationship("CaseBridgeActivity", back_populates="case", cascade="all, delete-orphan")


class CaseWallet(Base):
    """Wallet linked to a case - loaded from case_wallets.csv"""
    __tablename__ = 'case_wallet'

    id = Column(Integer, primary_key=True)
    case_id = Column(String(50), ForeignKey('investigation_case.id', ondelete='CASCADE'), nullable=False)
    address = Column(String(66), nullable=False, index=True)
    chain_code = Column(String(10), nullable=False)
    label = Column(String(100))
    role = Column(String(30), default='related')  # theft_origin, attacker, etc.
    first_seen = Column(TIMESTAMP)
    status = Column(String(20))  # active, dormant, cashed_out
    balance_usd = Column(Float)
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    case = relationship("Case", back_populates="wallets")

    __table_args__ = (
        UniqueConstraint('case_id', 'address', 'chain_code', name='case_wallet_unique'),
    )


class CaseMixerDeposit(Base):
    """Mixer deposit in a case - loaded from case_mixer_deposits.csv"""
    __tablename__ = 'case_mixer_deposit'

    id = Column(Integer, primary_key=True)
    case_id = Column(String(50), ForeignKey('investigation_case.id', ondelete='CASCADE'), nullable=False)
    mixer_protocol = Column(String(50), nullable=False)
    chain_code = Column(String(10), nullable=False)
    amount = Column(String(50))  # "330 ETH"
    usd_value = Column(Float)
    tx_hash = Column(String(66))
    timestamp = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    case = relationship("Case", back_populates="mixer_deposits")


class CaseBridgeActivity(Base):
    """Bridge activity in a case - loaded from case_bridge_activities.csv"""
    __tablename__ = 'case_bridge_activity'

    id = Column(Integer, primary_key=True)
    case_id = Column(String(50), ForeignKey('investigation_case.id', ondelete='CASCADE'), nullable=False)
    from_chain = Column(String(10), nullable=False)
    to_chain = Column(String(10), nullable=False)
    bridge_protocol = Column(String(50))
    amount_usd = Column(Float)
    tx_hash = Column(String(66))
    timestamp = Column(TIMESTAMP)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    case = relationship("Case", back_populates="bridge_activities")


# =============================================================================
# WALLET MONITORING
# =============================================================================

class MonitoredWallet(Base):
    """Wallet under active monitoring"""
    __tablename__ = 'monitored_wallet'

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False, index=True)
    chain_code = Column(String(10), ForeignKey('chain.code'), nullable=False)
    case_id = Column(String(50), ForeignKey('investigation_case.id'), nullable=True)
    label = Column(String(100))
    role = Column(String(30))
    is_active = Column(Boolean, default=True)
    added_at = Column(TIMESTAMP, default=datetime.utcnow)
    last_activity = Column(TIMESTAMP)
    last_checked = Column(TIMESTAMP)
    alert_count = Column(Integer, default=0)
    total_in_usd = Column(Float, default=0.0)
    total_out_usd = Column(Float, default=0.0)

    chain = relationship("Chain", back_populates="wallets")
    alerts = relationship("Alert", back_populates="wallet")

    __table_args__ = (
        UniqueConstraint('address', 'chain_code', name='monitored_wallet_unique'),
    )


class Alert(Base):
    """Alert generated from wallet activity"""
    __tablename__ = 'alert'

    id = Column(Integer, primary_key=True)
    wallet_id = Column(Integer, ForeignKey('monitored_wallet.id'), nullable=False)
    chain_code = Column(String(10), ForeignKey('chain.code'), nullable=False)
    alert_type = Column(String(30), nullable=False)
    amount = Column(Float)
    token = Column(String(20))
    counterparty = Column(String(66))
    tx_hash = Column(String(66), index=True)
    risk_score = Column(Float, default=0.0)
    is_read = Column(Boolean, default=False)
    notes = Column(Text)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow)

    wallet = relationship("MonitoredWallet", back_populates="alerts")
    chain = relationship("Chain", back_populates="alerts")


# =============================================================================
# WALLET LABELS & TAGS
# =============================================================================

class LabelCategory(Base):
    """Label categories for wallet classification - loaded from label_categories.csv"""
    __tablename__ = 'label_category'

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True)
    description = Column(String(255))
    risk_level = Column(String(20))  # low, medium, high, critical
    color = Column(String(7))  # Hex color
    priority = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    labels = relationship("WalletTag", back_populates="category")


class WalletTag(Base):
    """Tag/label assigned to a wallet address"""
    __tablename__ = 'wallet_tag'

    id = Column(Integer, primary_key=True)
    address = Column(String(66), nullable=False, index=True)
    chain_code = Column(String(10), nullable=False)
    tag = Column(String(100), nullable=False)  # "potential_hacker", "exchange_binance"
    category_id = Column(Integer, ForeignKey('label_category.id'), nullable=True)
    source = Column(String(30), default='manual')  # manual, api, ml
    confidence = Column(Float, default=1.0)
    is_verified = Column(Boolean, default=False)
    verified_by = Column(String(100))
    verified_at = Column(TIMESTAMP)
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    category = relationship("LabelCategory", back_populates="labels")

    __table_args__ = (
        UniqueConstraint('address', 'chain_code', 'tag', name='wallet_tag_unique'),
    )


# =============================================================================
# RPC ENDPOINTS
# =============================================================================

class RpcEndpoint(Base):
    """RPC endpoints for chains - loaded from rpc_endpoints.csv"""
    __tablename__ = 'rpc_endpoint'

    id = Column(Integer, primary_key=True)
    chain_code = Column(String(10), ForeignKey('chain.code'), nullable=False)
    url = Column(String(255), nullable=False)
    provider = Column(String(50))  # alchemy, infura, ankr
    priority = Column(Integer, default=0)  # Higher = preferred
    is_active = Column(Boolean, default=True)
    requires_key = Column(Boolean, default=False)
    key_env_var = Column(String(50))  # e.g., ALCHEMY_API_KEY
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
