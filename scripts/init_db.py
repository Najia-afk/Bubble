# =============================================================================
# Bubble - Database Initialization Script
# Loads CSV data into PostgreSQL on first run
# =============================================================================

import csv
import os
import logging
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from api.application.models import (
    Base, Chain, Mixer, Bridge, Case, CaseWallet, 
    CaseMixerDeposit, CaseBridgeActivity, LabelCategory, RpcEndpoint
)

logger = logging.getLogger(__name__)


class DatabaseInitializer:
    """Initialize database with CSV data."""
    
    def __init__(self, db_url: str = None):
        if db_url:
            self.db_url = db_url
        else:
            # Build from environment variables
            host = os.getenv('POSTGRES_HOST', 'postgres')
            port = os.getenv('POSTGRES_PORT', '5432')
            db = os.getenv('POSTGRES_DB', 'bubble_db')
            user = os.getenv('POSTGRES_USER', 'bubble_user')
            password = os.getenv('POSTGRES_PASSWORD', 'bubble_password_change_me')
            self.db_url = f'postgresql://{user}:{password}@{host}:{port}/{db}'
        
        self.engine = create_engine(self.db_url)
        self.Session = sessionmaker(bind=self.engine)
        self.data_dir = self._get_data_dir()
    
    def _get_data_dir(self) -> Path:
        """Get path to CSV data directory."""
        # From scripts/ go to parent (Bubble)
        base = Path(__file__).parent.parent
        data_dir = base / 'config' / 'data'
        if data_dir.exists():
            return data_dir
        # Docker path
        docker_dir = Path('/app/config/data')
        if docker_dir.exists():
            return docker_dir
        raise FileNotFoundError("CSV data directory not found")
    
    def init_all(self, force: bool = False):
        """Initialize all tables with CSV data."""
        # Create tables - checkfirst handles existing tables
        Base.metadata.create_all(self.engine, checkfirst=True)
        logger.info("Database tables created")
        
        session = self.Session()
        try:
            # Check if already initialized
            if not force and session.query(Chain).count() > 0:
                logger.info("Database already initialized, skipping")
                return
            
            # Load in order (respect foreign keys)
            self._load_chains(session)
            self._load_label_categories(session)
            self._load_mixers(session)
            self._load_bridges(session)
            self._load_rpc_endpoints(session)
            self._load_cases(session)
            self._load_case_wallets(session)
            self._load_case_mixer_deposits(session)
            self._load_case_bridge_activities(session)
            
            session.commit()
            logger.info("Database initialization complete")
            
        except Exception as e:
            session.rollback()
            logger.error(f"Database initialization failed: {e}")
            raise
        finally:
            session.close()
    
    def _read_csv(self, filename: str) -> list:
        """Read CSV file and return list of dicts."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            logger.warning(f"CSV file not found: {filename}")
            return []
        
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            return list(reader)
    
    def _parse_bool(self, value: str) -> bool:
        """Parse boolean from CSV string."""
        return value.lower() in ('true', '1', 'yes', 't')
    
    def _parse_float(self, value: str) -> float:
        """Parse float from CSV string, return None if empty."""
        if not value or value.strip() == '':
            return None
        return float(value)
    
    def _parse_int(self, value: str) -> int:
        """Parse int from CSV string, return None if empty."""
        if not value or value.strip() == '':
            return None
        return int(value)
    
    def _parse_date(self, value: str) -> datetime:
        """Parse date from CSV string."""
        if not value or value.strip() == '':
            return None
        return datetime.strptime(value.strip(), '%Y-%m-%d')
    
    def _load_chains(self, session):
        """Load chains from CSV."""
        rows = self._read_csv('chains.csv')
        for row in rows:
            chain = Chain(
                code=row['code'],
                name=row['name'],
                chain_id=int(row['chain_id']),
                native_token=row['native_token'],
                native_decimals=int(row['native_decimals']),
                explorer_name=row['explorer_name'],
                explorer_api_url=row['explorer_api_url'],
                explorer_api_key_env=row['explorer_api_key_env'],
                explorer_rate_limit=int(row['explorer_rate_limit']),
                block_time_seconds=float(row['block_time_seconds']),
                confirmations_required=int(row['confirmations_required']),
                is_active=self._parse_bool(row['is_active'])
            )
            session.merge(chain)
        logger.info(f"Loaded {len(rows)} chains")
    
    def _load_label_categories(self, session):
        """Load label categories from CSV."""
        rows = self._read_csv('label_categories.csv')
        for i, row in enumerate(rows, 1):
            cat = LabelCategory(
                id=i,
                name=row['name'],
                description=row['description'],
                risk_level=row['risk_level'],
                color=row['color'],
                priority=int(row['priority'])
            )
            session.merge(cat)
        logger.info(f"Loaded {len(rows)} label categories")
    
    def _load_mixers(self, session):
        """Load mixers from CSV."""
        rows = self._read_csv('mixers.csv')
        for row in rows:
            mixer = Mixer(
                address=row['address'].lower(),
                chain_code=row['chain_code'],
                protocol=row['protocol'],
                name=row['name'],
                pool_size=row['pool_size'],
                is_active=self._parse_bool(row['is_active'])
            )
            session.add(mixer)
        logger.info(f"Loaded {len(rows)} mixers")
    
    def _load_bridges(self, session):
        """Load bridges from CSV."""
        rows = self._read_csv('bridges.csv')
        for row in rows:
            bridge = Bridge(
                address=row['address'].lower(),
                chain_code=row['chain_code'],
                protocol=row['protocol'],
                name=row['name'],
                direction=row['direction'],
                is_active=self._parse_bool(row['is_active'])
            )
            session.add(bridge)
        logger.info(f"Loaded {len(rows)} bridges")
    
    def _load_rpc_endpoints(self, session):
        """Load RPC endpoints from CSV."""
        rows = self._read_csv('rpc_endpoints.csv')
        for row in rows:
            endpoint = RpcEndpoint(
                chain_code=row['chain_code'],
                url=row['url'],
                provider=row['provider'],
                priority=int(row['priority']),
                is_active=self._parse_bool(row['is_active']),
                requires_key=self._parse_bool(row['requires_key']),
                key_env_var=row['key_env_var'] or None
            )
            session.add(endpoint)
        logger.info(f"Loaded {len(rows)} RPC endpoints")
    
    def _load_cases(self, session):
        """Load cases from CSV."""
        rows = self._read_csv('cases.csv')
        for row in rows:
            case = Case(
                id=row['id'],
                title=row['title'],
                source=row['source'],
                status=row['status'],
                severity=row['severity'],
                date_reported=self._parse_date(row['date_reported']),
                summary=row['summary'],
                total_stolen_usd=self._parse_float(row['total_stolen_usd']),
                victim_count=row['victim_count'] or None,
                attack_vector=row['attack_vector'] or None,
                notes=row['notes'] or None
            )
            session.merge(case)
        logger.info(f"Loaded {len(rows)} cases")
    
    def _load_case_wallets(self, session):
        """Load case wallets from CSV."""
        rows = self._read_csv('case_wallets.csv')
        for row in rows:
            wallet = CaseWallet(
                case_id=row['case_id'],
                address=row['address'].lower(),
                chain_code=row['chain_code'],
                label=row['label'],
                role=row['role'],
                first_seen=self._parse_date(row['first_seen']),
                status=row['status'] or None,
                balance_usd=self._parse_float(row['balance_usd']),
                notes=row['notes'] or None
            )
            session.add(wallet)
        logger.info(f"Loaded {len(rows)} case wallets")
    
    def _load_case_mixer_deposits(self, session):
        """Load case mixer deposits from CSV."""
        rows = self._read_csv('case_mixer_deposits.csv')
        for row in rows:
            deposit = CaseMixerDeposit(
                case_id=row['case_id'],
                mixer_protocol=row['mixer_protocol'],
                chain_code=row['chain_code'],
                amount=row['amount'],
                usd_value=self._parse_float(row['usd_value']),
                tx_hash=row['tx_hash'] or None,
                timestamp=self._parse_date(row['timestamp'])
            )
            session.add(deposit)
        logger.info(f"Loaded {len(rows)} mixer deposits")
    
    def _load_case_bridge_activities(self, session):
        """Load case bridge activities from CSV."""
        rows = self._read_csv('case_bridge_activities.csv')
        for row in rows:
            activity = CaseBridgeActivity(
                case_id=row['case_id'],
                from_chain=row['from_chain'],
                to_chain=row['to_chain'],
                bridge_protocol=row['bridge_protocol'] or None,
                amount_usd=self._parse_float(row['amount_usd']),
                tx_hash=row['tx_hash'] or None,
                timestamp=self._parse_date(row['timestamp'])
            )
            session.add(activity)
        logger.info(f"Loaded {len(rows)} bridge activities")


def init_database(force: bool = False):
    """Initialize database with CSV data."""
    initializer = DatabaseInitializer()
    initializer.init_all(force=force)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    init_database()
