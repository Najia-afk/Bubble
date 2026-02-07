# api/application/investigation_models.py
"""
Investigation models — forensic case management entities.
"""
from sqlalchemy import Column, String, Integer, Float, BigInteger, Boolean, Text, TIMESTAMP, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from api.application.base import Base


class Investigation(Base):
    """Forensic investigation case — tracks hack/fraud incidents"""
    __tablename__ = 'investigation'

    id = Column(Integer, primary_key=True)
    name = Column(String(200), nullable=False)
    description = Column(Text)
    status = Column(String(20), default='open')
    incident_date = Column(TIMESTAMP)
    reported_loss_usd = Column(Float)
    created_by = Column(String(100))
    assigned_to = Column(String(100))
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = Column(TIMESTAMP)
    notes = Column(Text)

    wallets = relationship("InvestigationWallet", back_populates="investigation", cascade="all, delete-orphan")
    tokens = relationship("InvestigationToken", back_populates="investigation", cascade="all, delete-orphan")
    transfers = relationship("InvestigationTransfer", back_populates="investigation", cascade="all, delete-orphan")


class InvestigationWallet(Base):
    """Wallets linked to an investigation"""
    __tablename__ = 'investigation_wallet'

    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey('investigation.id', ondelete='CASCADE'), nullable=False, index=True)
    address = Column(String(42), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, default=1)
    role = Column(String(30), nullable=False, default='related')
    depth = Column(Integer, default=0)
    parent_address = Column(String(42))
    discovered_at = Column(TIMESTAMP, default=datetime.utcnow)
    last_activity = Column(TIMESTAMP)
    total_received = Column(Float, default=0.0)
    total_sent = Column(Float, default=0.0)
    is_flagged = Column(Boolean, default=False)
    notes = Column(Text)

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
    stolen_amount = Column(Float)

    investigation = relationship("Investigation", back_populates="tokens")

    __table_args__ = (
        UniqueConstraint('investigation_id', 'contract_address', 'chain_id', name='investigation_token_unique'),
    )


class InvestigationTransfer(Base):
    """Token transfers involving investigation wallets."""
    __tablename__ = 'investigation_transfer'

    id = Column(Integer, primary_key=True)
    investigation_id = Column(Integer, ForeignKey('investigation.id', ondelete='CASCADE'), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, default=1)
    chain_code = Column(String(10), nullable=False)
    tx_hash = Column(String(66), nullable=False, index=True)
    block_number = Column(BigInteger)
    timestamp = Column(TIMESTAMP, index=True)
    from_address = Column(String(42), nullable=False, index=True)
    to_address = Column(String(42), nullable=False, index=True)
    token_symbol = Column(String(64))
    token_contract = Column(String(42))
    value = Column(Float)
    value_raw = Column(String(78))
    token_decimals = Column(Integer)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    investigation = relationship("Investigation", back_populates="transfers")

    __table_args__ = (
        UniqueConstraint(
            'investigation_id', 'chain_id', 'tx_hash', 'from_address', 'to_address', 'token_contract',
            name='investigation_transfer_unique'
        ),
        Index('ix_inv_transfer_from_addr', 'from_address'),
        Index('ix_inv_transfer_to_addr', 'to_address'),
        Index('ix_inv_transfer_inv_from', 'investigation_id', 'from_address'),
        Index('ix_inv_transfer_inv_to', 'investigation_id', 'to_address'),
    )
