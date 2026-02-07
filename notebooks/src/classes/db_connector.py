"""
Database Connector for Bubble PostgreSQL Database
Provides SQLAlchemy ORM-based access to transfer data and wallet features.
Pure ORM — zero raw SQL.
"""
import os
import pandas as pd
from sqlalchemy import create_engine, func, inspect as sa_inspect
from sqlalchemy.orm import sessionmaker
from typing import Optional, List, Dict


class DatabaseConnector:
    """
    PostgreSQL database connector for Bubble analytics.
    Uses SQLAlchemy ORM models exclusively — zero raw SQL.
    """
    
    def __init__(self, connection_string: str = None):
        """
        Initialize database connection.
        
        Parameters:
        -----------
        connection_string : str, optional
            PostgreSQL connection string. If not provided, uses environment variables.
        """
        if connection_string is None:
            # Build from environment variables (Docker)
            host = os.getenv('DATABASE_HOST', 'db')
            port = os.getenv('DATABASE_PORT', '5432')
            user = os.getenv('DATABASE_USER', 'bubbleuser')
            password = os.getenv('DATABASE_PASSWORD', 'bubblepassword')
            database = os.getenv('DATABASE_NAME', 'bubbledb')
            connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
        
        self.connection_string = connection_string
        self.engine = create_engine(connection_string)
        self.SessionFactory = sessionmaker(bind=self.engine)
        
        print(f"Connected to database")
    
    def get_session(self):
        """Get a new database session."""
        return self.SessionFactory()
    
    def get_table_names(self) -> List[str]:
        """Get list of all tables in the database using SQLAlchemy inspector."""
        inspector = sa_inspect(self.engine)
        return sorted(inspector.get_table_names())
    
    def get_transfer_data(self, chain: str = 'POL', token: str = 'ghst', 
                          limit: int = 100000) -> pd.DataFrame:
        """
        Get ERC20 transfer data for analysis using dynamic ORM classes.
        
        Parameters:
        -----------
        chain : str
            Chain trigram (POL, ETH, BSC, BASE)
        token : str
            Token symbol
        limit : int
            Maximum rows to return
            
        Returns:
        --------
        pd.DataFrame
            Transfer data
        """
        from api.application.erc20models import get_transfer_event_class
        
        cls = get_transfer_event_class(token, chain)
        if cls is None:
            print(f"No ORM class for {token}/{chain}")
            return pd.DataFrame()
        
        try:
            session = self.get_session()
            query = session.query(
                cls.block_number,
                cls.hash,
                cls.from_contract_address.label('from_address'),
                cls.to_contract_address.label('to_address'),
                cls.value,
                cls.token_symbol,
                cls.timestamp,
            ).order_by(cls.block_number.desc()).limit(limit)
            
            df = pd.read_sql(query.statement, session.get_bind())
            session.close()
            print(f"Loaded {len(df):,} transfers from {cls.__tablename__}")
            return df
        except Exception as e:
            print(f"Error loading transfers: {e}")
            return pd.DataFrame()
    
    def get_wallet_scores(self, limit: int = 10000) -> pd.DataFrame:
        """
        Get existing wallet scores/classifications using ORM.
        
        Parameters:
        -----------
        limit : int
            Maximum rows to return
            
        Returns:
        --------
        pd.DataFrame
            Wallet score data
        """
        from api.application.erc20models import WalletScore
        
        try:
            session = self.get_session()
            query = session.query(
                WalletScore.address,
                WalletScore.chain_id,
                WalletScore.predicted_type,
                WalletScore.confidence,
                WalletScore.is_anomaly,
                WalletScore.feature_tx_count,
                WalletScore.feature_unique_counterparties,
                WalletScore.feature_avg_tx_value,
                WalletScore.feature_max_tx_value,
                WalletScore.feature_in_out_ratio,
                WalletScore.feature_total_volume,
                WalletScore.scored_at,
            ).order_by(WalletScore.scored_at.desc()).limit(limit)
            
            df = pd.read_sql(query.statement, session.get_bind())
            session.close()
            print(f"Loaded {len(df):,} wallet scores")
            return df
        except Exception as e:
            print(f"Error loading wallet scores: {e}")
            return pd.DataFrame()
    
    def get_wallet_labels(self, limit: int = 10000) -> pd.DataFrame:
        """
        Get known wallet labels for supervised learning using ORM.
        
        Parameters:
        -----------
        limit : int
            Maximum rows to return
            
        Returns:
        --------
        pd.DataFrame
            Wallet labels
        """
        from api.application.erc20models import WalletLabel
        
        try:
            session = self.get_session()
            query = session.query(
                WalletLabel.address,
                WalletLabel.label,
                WalletLabel.label_type,
                WalletLabel.chain_id,
                WalletLabel.source,
                WalletLabel.confidence,
                WalletLabel.created_at,
            ).order_by(WalletLabel.created_at.desc()).limit(limit)
            
            df = pd.read_sql(query.statement, session.get_bind())
            session.close()
            print(f"Loaded {len(df):,} wallet labels")
            return df
        except Exception as e:
            print(f"Error loading wallet labels: {e}")
            return pd.DataFrame()
    
    def get_investigations(self) -> pd.DataFrame:
        """Get all investigations using ORM."""
        from api.application.erc20models import Investigation
        
        try:
            session = self.get_session()
            query = session.query(
                Investigation.id,
                Investigation.name,
                Investigation.status,
                Investigation.incident_date,
                Investigation.reported_loss_usd,
                Investigation.created_at,
                Investigation.closed_at,
            ).order_by(Investigation.created_at.desc())
            
            df = pd.read_sql(query.statement, session.get_bind())
            session.close()
            print(f"Loaded {len(df):,} investigations")
            return df
        except Exception as e:
            print(f"Error loading investigations: {e}")
            return pd.DataFrame()
    
    def summary(self) -> Dict:
        """Get database summary statistics using ORM."""
        from api.application.erc20models import WalletScore, WalletLabel, Investigation
        
        tables = self.get_table_names()
        
        stats = {
            'tables': len(tables),
            'table_list': tables
        }
        
        session = self.get_session()
        
        # Count rows in key tables — pure ORM
        model_map = {
            'wallet_score': WalletScore,
            'wallet_label': WalletLabel,
            'investigation': Investigation,
        }
        for table_key, model_cls in model_map.items():
            if table_key in tables:
                try:
                    stats[f'{table_key}_count'] = session.query(func.count(model_cls.id)).scalar()
                except Exception:
                    stats[f'{table_key}_count'] = 0
        
        return stats
