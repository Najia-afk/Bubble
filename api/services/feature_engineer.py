"""
Enhanced Feature Engineering for Wallet Classification.
PhD-level feature extraction with 50+ behavioral and statistical features.
"""
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from collections import defaultdict
import logging
from scipy import stats
from sqlalchemy import text

logger = logging.getLogger(__name__)


class WalletFeatureEngineer:
    """
    Advanced feature engineering for wallet behavior analysis.
    Extracts 50+ features across multiple categories:
    - Transaction patterns
    - Temporal behavior
    - Network/graph features
    - Value distribution
    - Counterparty analysis
    - Risk indicators
    """
    
    FEATURE_CATEGORIES = {
        'transaction': [
            'tx_count_total', 'tx_count_in', 'tx_count_out',
            'tx_ratio_in_out', 'tx_frequency_daily', 'tx_frequency_hourly'
        ],
        'value': [
            'total_volume', 'volume_in', 'volume_out', 'volume_net',
            'avg_tx_value', 'median_tx_value', 'max_tx_value', 'min_tx_value',
            'std_tx_value', 'value_skewness', 'value_kurtosis',
            'large_tx_count', 'small_tx_count', 'round_number_ratio'
        ],
        'temporal': [
            'active_days', 'first_seen_days_ago', 'last_seen_days_ago',
            'activity_span_days', 'avg_time_between_tx',
            'weekend_tx_ratio', 'night_tx_ratio',
            'burst_activity_score', 'regularity_score'
        ],
        'network': [
            'unique_counterparties', 'unique_senders', 'unique_receivers',
            'counterparty_concentration', 'top_counterparty_ratio',
            'self_transfer_count', 'contract_interaction_ratio'
        ],
        'risk': [
            'mixer_interaction_count', 'bridge_interaction_count',
            'exchange_interaction_count', 'new_wallet_interaction_ratio',
            'high_risk_counterparty_count', 'dust_attack_indicator',
            'wash_trading_score', 'layering_score'
        ],
        'behavioral': [
            'consolidation_pattern', 'distribution_pattern',
            'dormancy_reactivation', 'velocity_change_rate',
            'behavioral_entropy', 'predictability_score'
        ]
    }
    
    def __init__(self, session=None):
        self.session = session
        self.known_exchanges = set()
        self.known_mixers = set()
        self.known_bridges = set()
        self._load_known_addresses()
    
    def _load_known_addresses(self):
        """Load known labeled addresses for feature computation."""
        if not self.session:
            return
        
        try:
            from api.application.erc20models import WalletLabel
            
            labels = self.session.query(WalletLabel).filter(
                WalletLabel.is_trusted == True
            ).all()
            
            for label in labels:
                addr = label.address.lower()
                if label.label_type == 'exchange':
                    self.known_exchanges.add(addr)
                elif label.label_type == 'mixer':
                    self.known_mixers.add(addr)
                elif label.label_type == 'bridge':
                    self.known_bridges.add(addr)
            
            logger.info(f"Loaded {len(self.known_exchanges)} exchanges, "
                       f"{len(self.known_mixers)} mixers, {len(self.known_bridges)} bridges")
        except Exception as e:
            logger.warning(f"Could not load known addresses: {e}")
    
    def extract_features(
        self,
        address: str,
        chain: str,
        token_tables: List[str] = None,
        lookback_days: int = 90
    ) -> Dict[str, float]:
        """
        Extract all features for a wallet.
        
        Args:
            address: Wallet address
            chain: Chain trigram (ETH, POL, etc.)
            token_tables: List of token transfer tables to query
            lookback_days: How far back to analyze
            
        Returns:
            Dictionary of feature_name -> value
        """
        if not self.session:
            raise ValueError("Session required for feature extraction")
        
        address = address.lower()
        
        # Discover token tables if not provided
        if not token_tables:
            token_tables = self._discover_tables(chain)
        
        if not token_tables:
            logger.warning(f"No transfer tables found for chain {chain}")
            return self._empty_features()
        
        # Fetch raw transaction data
        transactions = self._fetch_transactions(address, token_tables, lookback_days)
        
        if not transactions:
            return self._empty_features()
        
        # Convert to DataFrame for analysis
        df = pd.DataFrame(transactions)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['value'] = df['value'].astype(float) / 1e18  # Normalize from wei
        
        # Extract feature categories
        features = {}
        features.update(self._extract_transaction_features(df, address))
        features.update(self._extract_value_features(df, address))
        features.update(self._extract_temporal_features(df))
        features.update(self._extract_network_features(df, address))
        features.update(self._extract_risk_features(df, address))
        features.update(self._extract_behavioral_features(df, address))
        
        return features
    
    def _discover_tables(self, chain: str) -> List[str]:
        """Discover available transfer tables for a chain."""
        try:
            query = text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_name LIKE :pattern
            """)
            result = self.session.execute(
                query, 
                {'pattern': f'%_{chain.lower()}_erc20_transfer_event'}
            ).fetchall()
            return [r[0] for r in result]
        except Exception as e:
            logger.error(f"Table discovery failed: {e}")
            return []
    
    def _fetch_transactions(
        self, 
        address: str, 
        tables: List[str], 
        lookback_days: int
    ) -> List[Dict]:
        """Fetch transactions from multiple tables."""
        transactions = []
        cutoff = datetime.utcnow() - timedelta(days=lookback_days)
        
        for table in tables:
            try:
                # Outgoing
                out_query = text(f"""
                    SELECT 'out' as direction, 
                           to_contract_address as counterparty,
                           value, timestamp, hash
                    FROM {table}
                    WHERE LOWER(from_contract_address) = :addr
                    AND timestamp >= :cutoff
                """)
                out_result = self.session.execute(
                    out_query, 
                    {'addr': address, 'cutoff': cutoff}
                ).fetchall()
                
                for row in out_result:
                    transactions.append({
                        'direction': 'out',
                        'counterparty': row[1],
                        'value': row[2],
                        'timestamp': row[3],
                        'hash': row[4]
                    })
                
                # Incoming
                in_query = text(f"""
                    SELECT 'in' as direction,
                           from_contract_address as counterparty,
                           value, timestamp, hash
                    FROM {table}
                    WHERE LOWER(to_contract_address) = :addr
                    AND timestamp >= :cutoff
                """)
                in_result = self.session.execute(
                    in_query,
                    {'addr': address, 'cutoff': cutoff}
                ).fetchall()
                
                for row in in_result:
                    transactions.append({
                        'direction': 'in',
                        'counterparty': row[1],
                        'value': row[2],
                        'timestamp': row[3],
                        'hash': row[4]
                    })
                    
            except Exception as e:
                logger.debug(f"Error fetching from {table}: {e}")
                continue
        
        return transactions
    
    def _extract_transaction_features(self, df: pd.DataFrame, address: str) -> Dict[str, float]:
        """Extract transaction count and frequency features."""
        features = {}
        
        out_df = df[df['direction'] == 'out']
        in_df = df[df['direction'] == 'in']
        
        features['tx_count_total'] = len(df)
        features['tx_count_in'] = len(in_df)
        features['tx_count_out'] = len(out_df)
        features['tx_ratio_in_out'] = len(in_df) / max(len(out_df), 1)
        
        # Frequency
        if len(df) > 1:
            time_span = (df['timestamp'].max() - df['timestamp'].min()).days + 1
            features['tx_frequency_daily'] = len(df) / max(time_span, 1)
            features['tx_frequency_hourly'] = len(df) / max(time_span * 24, 1)
        else:
            features['tx_frequency_daily'] = 0
            features['tx_frequency_hourly'] = 0
        
        return features
    
    def _extract_value_features(self, df: pd.DataFrame, address: str) -> Dict[str, float]:
        """Extract value distribution features."""
        features = {}
        
        out_df = df[df['direction'] == 'out']
        in_df = df[df['direction'] == 'in']
        
        features['total_volume'] = df['value'].sum()
        features['volume_in'] = in_df['value'].sum()
        features['volume_out'] = out_df['value'].sum()
        features['volume_net'] = features['volume_in'] - features['volume_out']
        
        if len(df) > 0:
            features['avg_tx_value'] = df['value'].mean()
            features['median_tx_value'] = df['value'].median()
            features['max_tx_value'] = df['value'].max()
            features['min_tx_value'] = df['value'].min()
            features['std_tx_value'] = df['value'].std() if len(df) > 1 else 0
            
            # Distribution shape
            if len(df) > 2:
                features['value_skewness'] = df['value'].skew()
                features['value_kurtosis'] = df['value'].kurtosis()
            else:
                features['value_skewness'] = 0
                features['value_kurtosis'] = 0
            
            # Transaction size categories
            large_threshold = df['value'].quantile(0.9) if len(df) > 10 else 1000
            features['large_tx_count'] = len(df[df['value'] > large_threshold])
            features['small_tx_count'] = len(df[df['value'] < 1])  # < 1 token
            
            # Round number detection (potential wash trading indicator)
            round_values = df['value'].apply(lambda x: x == int(x) or x % 10 == 0)
            features['round_number_ratio'] = round_values.sum() / len(df)
        else:
            for key in ['avg_tx_value', 'median_tx_value', 'max_tx_value', 'min_tx_value',
                       'std_tx_value', 'value_skewness', 'value_kurtosis',
                       'large_tx_count', 'small_tx_count', 'round_number_ratio']:
                features[key] = 0
        
        return features
    
    def _extract_temporal_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Extract time-based behavioral features."""
        features = {}
        
        if len(df) == 0:
            return {k: 0 for k in ['active_days', 'first_seen_days_ago', 'last_seen_days_ago',
                                   'activity_span_days', 'avg_time_between_tx',
                                   'weekend_tx_ratio', 'night_tx_ratio',
                                   'burst_activity_score', 'regularity_score']}
        
        now = datetime.utcnow()
        
        features['first_seen_days_ago'] = (now - df['timestamp'].min()).days
        features['last_seen_days_ago'] = (now - df['timestamp'].max()).days
        features['activity_span_days'] = (df['timestamp'].max() - df['timestamp'].min()).days
        features['active_days'] = df['timestamp'].dt.date.nunique()
        
        # Time between transactions
        if len(df) > 1:
            df_sorted = df.sort_values('timestamp')
            time_diffs = df_sorted['timestamp'].diff().dropna()
            features['avg_time_between_tx'] = time_diffs.mean().total_seconds() / 3600  # hours
        else:
            features['avg_time_between_tx'] = 0
        
        # Weekend activity
        df['is_weekend'] = df['timestamp'].dt.dayofweek >= 5
        features['weekend_tx_ratio'] = df['is_weekend'].sum() / len(df)
        
        # Night activity (00:00 - 06:00 UTC)
        df['hour'] = df['timestamp'].dt.hour
        features['night_tx_ratio'] = len(df[(df['hour'] >= 0) & (df['hour'] < 6)]) / len(df)
        
        # Burst activity (many tx in short time)
        if len(df) > 5:
            df_sorted = df.sort_values('timestamp')
            time_diffs = df_sorted['timestamp'].diff().dt.total_seconds().dropna()
            burst_threshold = 60  # 1 minute
            features['burst_activity_score'] = (time_diffs < burst_threshold).sum() / len(time_diffs)
        else:
            features['burst_activity_score'] = 0
        
        # Regularity score (entropy of hour distribution)
        hour_counts = df['hour'].value_counts(normalize=True)
        features['regularity_score'] = stats.entropy(hour_counts) if len(hour_counts) > 1 else 0
        
        return features
    
    def _extract_network_features(self, df: pd.DataFrame, address: str) -> Dict[str, float]:
        """Extract network/graph features."""
        features = {}
        
        if len(df) == 0:
            return {k: 0 for k in ['unique_counterparties', 'unique_senders', 'unique_receivers',
                                   'counterparty_concentration', 'top_counterparty_ratio',
                                   'self_transfer_count', 'contract_interaction_ratio']}
        
        out_df = df[df['direction'] == 'out']
        in_df = df[df['direction'] == 'in']
        
        all_counterparties = df['counterparty'].dropna().str.lower()
        features['unique_counterparties'] = all_counterparties.nunique()
        features['unique_senders'] = in_df['counterparty'].dropna().str.lower().nunique()
        features['unique_receivers'] = out_df['counterparty'].dropna().str.lower().nunique()
        
        # Counterparty concentration (Herfindahl index)
        if len(all_counterparties) > 0:
            cp_counts = all_counterparties.value_counts(normalize=True)
            features['counterparty_concentration'] = (cp_counts ** 2).sum()
            features['top_counterparty_ratio'] = cp_counts.iloc[0] if len(cp_counts) > 0 else 0
        else:
            features['counterparty_concentration'] = 0
            features['top_counterparty_ratio'] = 0
        
        # Self transfers
        features['self_transfer_count'] = len(df[df['counterparty'].str.lower() == address])
        
        # Contract interactions (addresses starting with specific patterns or in known lists)
        # Simplified: assume addresses in known lists are contracts
        contract_addrs = self.known_exchanges | self.known_mixers | self.known_bridges
        contract_txs = df[df['counterparty'].str.lower().isin(contract_addrs)]
        features['contract_interaction_ratio'] = len(contract_txs) / len(df)
        
        return features
    
    def _extract_risk_features(self, df: pd.DataFrame, address: str) -> Dict[str, float]:
        """Extract risk indicator features."""
        features = {}
        
        if len(df) == 0:
            return {k: 0 for k in ['mixer_interaction_count', 'bridge_interaction_count',
                                   'exchange_interaction_count', 'new_wallet_interaction_ratio',
                                   'high_risk_counterparty_count', 'dust_attack_indicator',
                                   'wash_trading_score', 'layering_score']}
        
        counterparties = df['counterparty'].dropna().str.lower()
        
        # Interactions with known entities
        features['mixer_interaction_count'] = counterparties.isin(self.known_mixers).sum()
        features['bridge_interaction_count'] = counterparties.isin(self.known_bridges).sum()
        features['exchange_interaction_count'] = counterparties.isin(self.known_exchanges).sum()
        
        # High risk = mixers
        features['high_risk_counterparty_count'] = features['mixer_interaction_count']
        
        # New wallet interactions (would need additional data)
        features['new_wallet_interaction_ratio'] = 0  # Placeholder
        
        # Dust attack indicator (many very small incoming tx)
        in_df = df[df['direction'] == 'in']
        if len(in_df) > 0:
            dust_threshold = 0.001  # Very small amounts
            dust_txs = in_df[in_df['value'] < dust_threshold]
            features['dust_attack_indicator'] = len(dust_txs) / len(in_df)
        else:
            features['dust_attack_indicator'] = 0
        
        # Wash trading score (circular patterns)
        # Simplified: check for back-and-forth with same counterparty
        cp_in = set(df[df['direction'] == 'in']['counterparty'].dropna().str.lower())
        cp_out = set(df[df['direction'] == 'out']['counterparty'].dropna().str.lower())
        circular = cp_in & cp_out
        features['wash_trading_score'] = len(circular) / max(len(cp_in | cp_out), 1)
        
        # Layering score (rapid redistribution pattern)
        # Check if incoming immediately followed by outgoing
        if len(df) > 2:
            df_sorted = df.sort_values('timestamp')
            direction_changes = (df_sorted['direction'] != df_sorted['direction'].shift()).sum()
            features['layering_score'] = direction_changes / len(df)
        else:
            features['layering_score'] = 0
        
        return features
    
    def _extract_behavioral_features(self, df: pd.DataFrame, address: str) -> Dict[str, float]:
        """Extract high-level behavioral pattern features."""
        features = {}
        
        if len(df) == 0:
            return {k: 0 for k in ['consolidation_pattern', 'distribution_pattern',
                                   'dormancy_reactivation', 'velocity_change_rate',
                                   'behavioral_entropy', 'predictability_score']}
        
        out_df = df[df['direction'] == 'out']
        in_df = df[df['direction'] == 'in']
        
        # Consolidation: many in, few out (collecting funds)
        if len(out_df) > 0:
            features['consolidation_pattern'] = len(in_df) / len(out_df)
        else:
            features['consolidation_pattern'] = len(in_df)
        
        # Distribution: few in, many out (distributing funds)
        if len(in_df) > 0:
            features['distribution_pattern'] = len(out_df) / len(in_df)
        else:
            features['distribution_pattern'] = len(out_df)
        
        # Dormancy and reactivation (gaps in activity)
        if len(df) > 1:
            df_sorted = df.sort_values('timestamp')
            time_diffs = df_sorted['timestamp'].diff().dt.days.dropna()
            long_gaps = (time_diffs > 30).sum()  # Gaps > 30 days
            features['dormancy_reactivation'] = long_gaps
        else:
            features['dormancy_reactivation'] = 0
        
        # Velocity change rate
        if len(df) > 10:
            df_sorted = df.sort_values('timestamp')
            df_sorted['period'] = pd.cut(range(len(df_sorted)), bins=5, labels=False)
            period_counts = df_sorted.groupby('period').size()
            features['velocity_change_rate'] = period_counts.std() / max(period_counts.mean(), 1)
        else:
            features['velocity_change_rate'] = 0
        
        # Behavioral entropy (unpredictability)
        if len(df) > 1:
            # Combine multiple behavioral signals
            signals = [
                df['direction'].value_counts(normalize=True),
                df['timestamp'].dt.hour.value_counts(normalize=True),
            ]
            entropies = [stats.entropy(s) for s in signals if len(s) > 1]
            features['behavioral_entropy'] = np.mean(entropies) if entropies else 0
        else:
            features['behavioral_entropy'] = 0
        
        # Predictability (inverse of entropy)
        features['predictability_score'] = 1 / (1 + features['behavioral_entropy'])
        
        return features
    
    def _empty_features(self) -> Dict[str, float]:
        """Return empty feature dictionary with all features set to 0."""
        features = {}
        for category_features in self.FEATURE_CATEGORIES.values():
            for feature in category_features:
                features[feature] = 0.0
        return features
    
    def get_feature_names(self) -> List[str]:
        """Get list of all feature names."""
        names = []
        for category_features in self.FEATURE_CATEGORIES.values():
            names.extend(category_features)
        return names
    
    def get_feature_importance_groups(self) -> Dict[str, List[str]]:
        """Get features grouped by category for interpretability."""
        return self.FEATURE_CATEGORIES.copy()
