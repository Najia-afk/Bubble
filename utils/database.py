from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import scoped_session
from sqlalchemy import create_engine
import logging
import os
from utils.logging_config import setup_logging
from config.settings import Config

db_session_logger = setup_logging('bubbledb_connection_log')

# Global engine for reuse
_engine = None

def get_engine():
    """Get or create database engine"""
    global _engine
    if _engine is None:
        try:
            # Use environment variables for credentials
            db_url = Config.SQLALCHEMY_DATABASE_URI
            _engine = create_engine(
                db_url,
                pool_size=10,
                max_overflow=20,
                pool_pre_ping=True,
                pool_recycle=3600
            )
            db_session_logger.info(f"Database engine created successfully")
        except Exception as e:
            db_session_logger.error(f"Error while creating database engine: {e}")
            raise
    return _engine


def get_db_session():
    """Get a new database session"""
    try:
        engine = get_engine()
        Session = sessionmaker(bind=engine)
        return Session()
    except Exception as e:
        db_session_logger.error(f"Error while creating SQLAlchemy session: {e}")
        raise


def get_session_factory():
    """Get a scoped session factory"""
    try:
        engine = get_engine()
        session_factory = sessionmaker(bind=engine)
        SessionFactory = scoped_session(session_factory)
        return SessionFactory
    except Exception as e:
        db_session_logger.error(f"Error while creating SQLAlchemy session factory: {e}")
        raise

#psql -h localhost -p 5432 -d  bubbledb -U admbubble_db