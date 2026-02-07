# api/application/label_models.py
"""
Label system models — wallet labels, label types, known bridges.
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, TIMESTAMP, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from datetime import datetime

from api.application.base import Base


class LabelType(Base):
    """Predefined label types for wallet classification"""
    __tablename__ = 'label_type'

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False, unique=True, index=True)
    description = Column(String(255))
    color = Column(String(7), default='#808080')
    priority = Column(Integer, default=0)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    wallet_labels = relationship("WalletLabel", back_populates="label_type_rel")


class WalletLabel(Base):
    """Labels assigned to wallet addresses (from API import or manual)"""
    __tablename__ = 'wallet_label'

    id = Column(Integer, primary_key=True)
    address = Column(String(42), nullable=False, index=True)
    chain_id = Column(Integer, nullable=False, index=True)
    label = Column(String(100), nullable=False, index=True)
    label_type = Column(String(50), ForeignKey('label_type.name'), nullable=True, index=True)
    name_tag = Column(String(255))
    source = Column(String(20), nullable=False, default='manual')
    confidence = Column(Float, default=1.0)
    is_trusted = Column(Boolean, default=False)
    validated_by = Column(String(100))
    validated_at = Column(TIMESTAMP)
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

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
    protocol = Column(String(50), nullable=False)
    direction = Column(String(20))
    name = Column(String(100))
    is_active = Column(Boolean, default=True)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('address', 'chain_id', name='known_bridge_unique'),
    )
