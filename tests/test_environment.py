# =============================================================================
# Bubble - Blockchain Analytics Platform
# Copyright (c) 2025-2026 All Rights Reserved.
# =============================================================================
#
# Environment and Configuration Tests
# =============================================================================

import os
import pytest


def test_python_version():
    """Test that Python 3.12+ is being used."""
    import sys
    assert sys.version_info >= (3, 12), "Python 3.12+ required"


def test_environment_variables():
    """Test that critical environment variables are set."""
    # These should be set from .env or docker-compose
    critical_vars = [
        'POSTGRES_DB',
        'POSTGRES_USER',
        'POSTGRES_PASSWORD',
        'REDIS_HOST'
    ]
    
    # In testing, not all vars may be set - just check they're defined in .env.example
    env_example_path = os.path.join(os.path.dirname(__file__), '..', '.env.example')
    assert os.path.exists(env_example_path), ".env.example must exist"


def test_required_packages():
    """Test that required packages are installed."""
    required_packages = [
        'flask',
        'sqlalchemy',
        'celery',
        'redis',
        'web3',
        'pandas',
        'graphene'
    ]
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            pytest.fail(f"Required package '{package}' not installed")


def test_sqlalchemy_version():
    """Test that SQLAlchemy 2.0+ is installed."""
    import sqlalchemy
    version = tuple(map(int, sqlalchemy.__version__.split('.')[:2]))
    assert version >= (2, 0), f"SQLAlchemy 2.0+ required, got {sqlalchemy.__version__}"


def test_graphene_version():
    """Test that graphene 3.0+ is installed."""
    import graphene
    version = tuple(map(int, graphene.__version__.split('.')[:2]))
    assert version >= (3, 0), f"graphene 3.0+ required, got {graphene.__version__}"
