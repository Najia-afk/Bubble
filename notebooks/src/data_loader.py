"""
DataLoader — Connects to Bubble PostgreSQL and loads investigation data into DataFrames.

Usage in notebook:
    from notebooks.src.data_loader import DataLoader
    loader = DataLoader()
    transfers_df = loader.get_transfers(investigation_id=1)
    wallets_df = loader.get_wallets(investigation_id=1)
"""
import os
import sys
import pandas as pd
from typing import Optional

# Add project root to path for imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class DataLoader:
    """
    Loads investigation data from PostgreSQL into Pandas DataFrames.
    Works both inside Docker (uses env vars) and locally (uses .env file).
    """

    def __init__(self, db_url: str = None):
        """
        Args:
            db_url: SQLAlchemy database URL. If None, reads from env or .env file.
        """
        self._db_url = db_url or self._resolve_db_url()
        self._session_factory = None

    def _resolve_db_url(self) -> str:
        """Resolve DB URL from environment.
        Priority: DATABASE_URL env > individual POSTGRES_* env vars > .env file > default localhost.
        """
        url = os.environ.get('DATABASE_URL')
        if url:
            return url

        # Build from individual POSTGRES_* env vars (works inside Docker)
        pg_host = os.environ.get('POSTGRES_HOST')
        if pg_host:
            pg_user = os.environ.get('POSTGRES_USER', 'bubble_user')
            pg_pass = os.environ.get('POSTGRES_PASSWORD', 'bubble_password')
            pg_db = os.environ.get('POSTGRES_DB', 'bubble_db')
            pg_port = os.environ.get('POSTGRES_PORT', '5432')
            return f'postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}'

        # Try loading from .env
        env_path = os.path.join(PROJECT_ROOT, '.env')
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('DATABASE_URL='):
                        return line.split('=', 1)[1].strip('"').strip("'")

        # Default local setup (host machine with Docker postgres port-forwarded)
        return 'postgresql://bubble_user:bubble_password@localhost:5432/bubble_db'

    @property
    def session(self):
        if self._session_factory is None:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            engine = create_engine(self._db_url)
            self._session_factory = sessionmaker(bind=engine)
        return self._session_factory()

    def get_transfers(self, investigation_id: int) -> pd.DataFrame:
        """Load all transfers for an investigation as a DataFrame."""
        from api.queries.investigation_queries import get_all_transfers_dataframe
        sess = self.session
        try:
            data = get_all_transfers_dataframe(sess, investigation_id)
            df = pd.DataFrame(data)
            if not df.empty and 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        finally:
            sess.close()

    def get_wallets(self, investigation_id: int) -> pd.DataFrame:
        """Load all wallets for an investigation as a DataFrame."""
        from api.queries.investigation_queries import get_wallets_dataframe
        sess = self.session
        try:
            data = get_wallets_dataframe(sess, investigation_id)
            return pd.DataFrame(data)
        finally:
            sess.close()

    def get_edges(self, investigation_id: int) -> pd.DataFrame:
        """Load aggregated transfer edges as a DataFrame."""
        from api.queries.investigation_queries import get_transfer_edges
        sess = self.session
        try:
            data = get_transfer_edges(sess, investigation_id)
            df = pd.DataFrame(data)
            if not df.empty:
                df['first_tx'] = pd.to_datetime(df['first_tx'])
                df['last_tx'] = pd.to_datetime(df['last_tx'])
            return df
        finally:
            sess.close()

    def get_wallet_scores(self, chain_id: int = None) -> pd.DataFrame:
        """Load all wallet classification scores."""
        from api.queries.wallet_queries import get_all_scores
        sess = self.session
        try:
            scores = get_all_scores(sess, chain_id)
            return pd.DataFrame([{
                'address': s.address,
                'chain_id': s.chain_id,
                'predicted_type': s.predicted_type,
                'confidence': s.confidence,
                'cluster_id': s.cluster_id,
                'is_anomaly': s.is_anomaly,
                'anomaly_score': s.anomaly_score,
                'tx_count': s.feature_tx_count,
                'unique_counterparties': s.feature_unique_counterparties,
                'avg_tx_value': s.feature_avg_tx_value,
                'max_tx_value': s.feature_max_tx_value,
                'in_out_ratio': s.feature_in_out_ratio,
                'model_version': s.model_version,
            } for s in scores])
        finally:
            sess.close()

    def get_known_entities(self) -> pd.DataFrame:
        """Load all known mixers, bridges, exchanges for reference."""
        from api.queries.investigation_queries import load_known_addresses
        sess = self.session
        try:
            mixers, bridges, exchanges = load_known_addresses(sess)
            rows = []
            for addr, m in mixers.items():
                rows.append({'address': addr, 'type': 'mixer', 'name': getattr(m, 'name', '') or getattr(m, 'protocol', '')})
            for addr, b in bridges.items():
                rows.append({'address': addr, 'type': 'bridge', 'name': getattr(b, 'name', '') or getattr(b, 'protocol', '')})
            for addr, e in exchanges.items():
                rows.append({'address': addr, 'type': 'exchange', 'name': getattr(e, 'name_tag', '') or getattr(e, 'label', '')})
            return pd.DataFrame(rows)
        finally:
            sess.close()

    def run_sql(self, query: str, params: dict = None) -> pd.DataFrame:
        """Run arbitrary SQL query and return DataFrame."""
        from sqlalchemy import create_engine
        engine = create_engine(self._db_url)
        return pd.read_sql(query, engine, params=params)
