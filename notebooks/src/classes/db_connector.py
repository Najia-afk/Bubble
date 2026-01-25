"""
Database Connector for Bubble PostgreSQL Database
Provides SQLAlchemy-based access to transfer data and wallet features.
"""
import os
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from typing import Optional, List, Dict


class DatabaseConnector:
    """
    PostgreSQL database connector for Bubble analytics.
    Uses SQLAlchemy to connect to the main Bubble database.
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
        
        print(f"✅ Connected to database: {host if 'host' in dir() else 'configured'}")
    
    def get_session(self):
        """Get a new database session."""
        return self.SessionFactory()
    
    def execute_query(self, query: str, params: dict = None) -> pd.DataFrame:
        """
        Execute a SQL query and return results as DataFrame.
        
        Parameters:
        -----------
        query : str
            SQL query string
        params : dict, optional
            Query parameters
            
        Returns:
        --------
        pd.DataFrame
            Query results
        """
        with self.engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=params)
    
    def get_table_names(self) -> List[str]:
        """Get list of all tables in the database."""
        query = """
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public'
            ORDER BY table_name
        """
        df = self.execute_query(query)
        return df['table_name'].tolist()
    
    def get_transfer_data(self, chain: str = 'POL', token: str = 'ghst', 
                          limit: int = 100000) -> pd.DataFrame:
        """
        Get ERC20 transfer data for analysis.
        
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
        table_name = f"{chain.lower()}_{token.lower()}_erc20_transfer_history"
        
        query = f"""
            SELECT 
                block_number,
                hash,
                from_contract_address as from_address,
                to_contract_address as to_address,
                value,
                token_symbol,
                timestamp
            FROM {table_name}
            ORDER BY block_number DESC
            LIMIT :limit
        """
        
        try:
            df = self.execute_query(query, {'limit': limit})
            print(f"✅ Loaded {len(df):,} transfers from {table_name}")
            return df
        except Exception as e:
            print(f"⚠️ Error loading transfers: {e}")
            return pd.DataFrame()
    
    def get_wallet_scores(self, limit: int = 10000) -> pd.DataFrame:
        """
        Get existing wallet scores/classifications.
        
        Parameters:
        -----------
        limit : int
            Maximum rows to return
            
        Returns:
        --------
        pd.DataFrame
            Wallet score data
        """
        query = """
            SELECT 
                address,
                chain_id,
                predicted_type,
                confidence,
                is_anomaly,
                feature_tx_count,
                feature_unique_counterparties,
                feature_avg_tx_value,
                feature_max_tx_value,
                feature_in_out_ratio,
                feature_total_volume,
                scored_at
            FROM wallet_score
            ORDER BY scored_at DESC
            LIMIT :limit
        """
        
        try:
            df = self.execute_query(query, {'limit': limit})
            print(f"✅ Loaded {len(df):,} wallet scores")
            return df
        except Exception as e:
            print(f"⚠️ Error loading wallet scores: {e}")
            return pd.DataFrame()
    
    def get_wallet_labels(self, limit: int = 10000) -> pd.DataFrame:
        """
        Get known wallet labels for supervised learning.
        
        Parameters:
        -----------
        limit : int
            Maximum rows to return
            
        Returns:
        --------
        pd.DataFrame
            Wallet labels
        """
        query = """
            SELECT 
                address,
                label,
                label_type,
                chain_id,
                source,
                confidence,
                created_at
            FROM wallet_label
            ORDER BY created_at DESC
            LIMIT :limit
        """
        
        try:
            df = self.execute_query(query, {'limit': limit})
            print(f"✅ Loaded {len(df):,} wallet labels")
            return df
        except Exception as e:
            print(f"⚠️ Error loading wallet labels: {e}")
            return pd.DataFrame()
    
    def get_investigations(self) -> pd.DataFrame:
        """Get all investigations."""
        query = """
            SELECT 
                id, name, status, incident_date,
                reported_loss_usd, created_at, closed_at
            FROM investigation
            ORDER BY created_at DESC
        """
        
        try:
            df = self.execute_query(query)
            print(f"✅ Loaded {len(df):,} investigations")
            return df
        except Exception as e:
            print(f"⚠️ Error loading investigations: {e}")
            return pd.DataFrame()
    
    def summary(self) -> Dict:
        """Get database summary statistics."""
        tables = self.get_table_names()
        
        stats = {
            'tables': len(tables),
            'table_list': tables
        }
        
        # Count rows in key tables
        for table in ['wallet_score', 'wallet_label', 'investigation']:
            if table in tables:
                try:
                    count_df = self.execute_query(f"SELECT COUNT(*) as cnt FROM {table}")
                    stats[f'{table}_count'] = count_df['cnt'].iloc[0]
                except:
                    stats[f'{table}_count'] = 0
        
        return stats
