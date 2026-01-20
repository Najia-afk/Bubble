# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================
#
# Database Model Tests
# =============================================================================

import pytest
from sqlalchemy import inspect
from utils.database import get_session_factory
from api.application.erc20models import Token, TokenPriceHistory, Base


@pytest.fixture
def db_session():
    """Create a database session for testing."""
    SessionFactory = get_session_factory()
    session = SessionFactory()
    yield session
    session.close()


def test_token_model_structure():
    """Test that Token model has correct columns."""
    mapper = inspect(Token)
    column_names = [col.key for col in mapper.columns]
    
    required_columns = ['id', 'symbol', 'contract_address', 'asset_platform_id', 'name']
    for col in required_columns:
        assert col in column_names, f"Token model missing column: {col}"


def test_token_price_history_model_structure():
    """Test that TokenPriceHistory model has correct columns."""
    mapper = inspect(TokenPriceHistory)
    column_names = [col.key for col in mapper.columns]
    
    required_columns = ['id', 'contract_address', 'timestamp', 'price']
    for col in required_columns:
        assert col in column_names, f"TokenPriceHistory model missing column: {col}"


def test_sqlalchemy_base_registry():
    """Test that SQLAlchemy Base registry is accessible (SQLAlchemy 2.0)."""
    assert hasattr(Base, 'registry'), "Base.registry not found (SQLAlchemy 2.0 required)"
    assert hasattr(Base.registry, 'mappers'), "Base.registry.mappers not found"


@pytest.mark.ghst
def test_ghst_token_creation(db_session):
    """Test creating GHST token in database."""
    contract_address = '0x385Eeac5cB85A38A9a07A70c73e0a3271CfB54A7'
    
    # Check if GHST already exists by contract_address (primary key)
    existing = db_session.query(Token).filter_by(
        contract_address=contract_address
    ).first()
    
    if existing:
        # Token already exists from another test, just verify it
        assert existing.symbol.upper() == 'GHST'  # Case-insensitive check
        assert existing.asset_platform_id == 'polygon-pos'
        assert existing.contract_address == contract_address
    else:
        # Create new GHST token
        ghst = Token(
            id='aavegotchi',
            symbol='GHST',
            name='Aavegotchi',
            asset_platform_id='polygon-pos',
            contract_address=contract_address,
            trigram='POL',  # Polygon trigram (matches complete_dataflow test)
            history_tag=1,
            transfert_erc20_tag=1
        )
        db_session.add(ghst)
        db_session.commit()
        
        # Verify
        created = db_session.query(Token).filter_by(contract_address=contract_address).first()
        assert created is not None
        assert created.symbol == 'GHST'
        assert created.contract_address == contract_address
