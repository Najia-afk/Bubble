"""
Wallet Feature Extractor for Bubble Analytics
Extracts behavioral features from transfer data for clustering and classification.
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Optional, Tuple
from tqdm import tqdm


class WalletFeatureExtractor:
    """
    Extracts behavioral features from wallet transfer data.
    Features are designed for clustering and anomaly detection.
    """
    
    # Feature names for consistency
    FEATURE_COLUMNS = [
        'tx_count',
        'unique_counterparties',
        'avg_tx_value',
        'median_tx_value',
        'max_tx_value',
        'min_tx_value',
        'std_tx_value',
        'total_volume',
        'in_count',
        'out_count',
        'in_volume',
        'out_volume',
        'in_out_ratio',
        'volume_ratio',
        'avg_in_value',
        'avg_out_value',
        'unique_in_counterparties',
        'unique_out_counterparties',
        'counterparty_concentration',
        'value_entropy',
        'activity_span_days',
        'avg_txs_per_day',
        'large_tx_ratio',
        'round_number_ratio'
    ]
    
    def __init__(self, transfers_df: pd.DataFrame):
        """
        Initialize with transfer data.
        
        Parameters:
        -----------
        transfers_df : pd.DataFrame
            Transfer data with columns: from_address, to_address, value, timestamp
        """
        self.transfers = transfers_df.copy()
        
        # Normalize value to token units (assuming 18 decimals)
        if 'value' in self.transfers.columns:
            self.transfers['value_normalized'] = self.transfers['value'].astype(float) / 1e18
        
        # Parse timestamp if needed
        if 'timestamp' in self.transfers.columns and not pd.api.types.is_datetime64_any_dtype(self.transfers['timestamp']):
            self.transfers['timestamp'] = pd.to_datetime(self.transfers['timestamp'])
        
        print(f"✅ Initialized with {len(self.transfers):,} transfers")
    
    def _calculate_entropy(self, values: pd.Series) -> float:
        """Calculate Shannon entropy of value distribution."""
        if len(values) == 0:
            return 0.0
        
        # Bin values into categories
        try:
            bins = pd.qcut(values, q=10, duplicates='drop')
            probs = bins.value_counts(normalize=True)
            entropy = -np.sum(probs * np.log2(probs + 1e-10))
            return entropy
        except:
            return 0.0
    
    def _is_round_number(self, value: float) -> bool:
        """Check if value is a round number (likely manual transfer)."""
        if value == 0:
            return False
        # Check if value is round to 1, 10, 100, 1000, etc.
        for decimals in [0, 1, 2]:
            rounded = round(value, decimals)
            if abs(value - rounded) < 1e-6:
                return True
        return False
    
    def extract_features_for_wallet(self, address: str) -> Dict:
        """
        Extract all features for a single wallet.
        
        Parameters:
        -----------
        address : str
            Wallet address
            
        Returns:
        --------
        Dict
            Feature dictionary
        """
        address = address.lower()
        
        # Get incoming and outgoing transactions
        incoming = self.transfers[self.transfers['to_address'].str.lower() == address]
        outgoing = self.transfers[self.transfers['from_address'].str.lower() == address]
        
        all_txs = pd.concat([
            incoming.assign(direction='in'),
            outgoing.assign(direction='out')
        ])
        
        if len(all_txs) == 0:
            return {col: 0 for col in self.FEATURE_COLUMNS}
        
        values = all_txs['value_normalized']
        
        # Basic counts
        tx_count = len(all_txs)
        in_count = len(incoming)
        out_count = len(outgoing)
        
        # Counterparties
        in_counterparties = set(incoming['from_address'].str.lower().unique())
        out_counterparties = set(outgoing['to_address'].str.lower().unique())
        all_counterparties = in_counterparties | out_counterparties
        
        # Volumes
        in_volume = incoming['value_normalized'].sum() if len(incoming) > 0 else 0
        out_volume = outgoing['value_normalized'].sum() if len(outgoing) > 0 else 0
        total_volume = in_volume + out_volume
        
        # Ratios
        in_out_ratio = in_count / max(out_count, 1)
        volume_ratio = in_volume / max(out_volume, 1e-10)
        
        # Value statistics
        avg_tx_value = values.mean() if len(values) > 0 else 0
        median_tx_value = values.median() if len(values) > 0 else 0
        max_tx_value = values.max() if len(values) > 0 else 0
        min_tx_value = values.min() if len(values) > 0 else 0
        std_tx_value = values.std() if len(values) > 1 else 0
        
        # Direction-specific averages
        avg_in_value = incoming['value_normalized'].mean() if len(incoming) > 0 else 0
        avg_out_value = outgoing['value_normalized'].mean() if len(outgoing) > 0 else 0
        
        # Concentration (how concentrated are transactions with top counterparties)
        if len(all_counterparties) > 0:
            counterparty_txs = pd.concat([
                incoming['from_address'].str.lower(),
                outgoing['to_address'].str.lower()
            ]).value_counts()
            top_5_ratio = counterparty_txs.head(5).sum() / tx_count
            counterparty_concentration = top_5_ratio
        else:
            counterparty_concentration = 0
        
        # Value entropy
        value_entropy = self._calculate_entropy(values)
        
        # Time-based features
        if 'timestamp' in all_txs.columns and len(all_txs) > 1:
            timestamps = pd.to_datetime(all_txs['timestamp'])
            activity_span_days = (timestamps.max() - timestamps.min()).days + 1
            avg_txs_per_day = tx_count / max(activity_span_days, 1)
        else:
            activity_span_days = 1
            avg_txs_per_day = tx_count
        
        # Large transaction ratio (> 1000 tokens)
        large_tx_ratio = (values > 1000).sum() / max(tx_count, 1)
        
        # Round number ratio
        round_number_ratio = values.apply(self._is_round_number).sum() / max(tx_count, 1)
        
        return {
            'tx_count': tx_count,
            'unique_counterparties': len(all_counterparties),
            'avg_tx_value': avg_tx_value,
            'median_tx_value': median_tx_value,
            'max_tx_value': max_tx_value,
            'min_tx_value': min_tx_value,
            'std_tx_value': std_tx_value,
            'total_volume': total_volume,
            'in_count': in_count,
            'out_count': out_count,
            'in_volume': in_volume,
            'out_volume': out_volume,
            'in_out_ratio': in_out_ratio,
            'volume_ratio': volume_ratio,
            'avg_in_value': avg_in_value,
            'avg_out_value': avg_out_value,
            'unique_in_counterparties': len(in_counterparties),
            'unique_out_counterparties': len(out_counterparties),
            'counterparty_concentration': counterparty_concentration,
            'value_entropy': value_entropy,
            'activity_span_days': activity_span_days,
            'avg_txs_per_day': avg_txs_per_day,
            'large_tx_ratio': large_tx_ratio,
            'round_number_ratio': round_number_ratio
        }
    
    def extract_all_features(self, min_tx_count: int = 5) -> pd.DataFrame:
        """
        Extract features for all wallets in the transfer data.
        
        Parameters:
        -----------
        min_tx_count : int
            Minimum number of transactions for a wallet to be included
            
        Returns:
        --------
        pd.DataFrame
            Features for all qualifying wallets
        """
        # Get all unique addresses
        from_addresses = set(self.transfers['from_address'].str.lower().unique())
        to_addresses = set(self.transfers['to_address'].str.lower().unique())
        all_addresses = from_addresses | to_addresses
        
        print(f"📊 Found {len(all_addresses):,} unique wallets")
        
        # Extract features for each wallet
        features_list = []
        
        for address in tqdm(all_addresses, desc="Extracting features"):
            features = self.extract_features_for_wallet(address)
            
            # Filter by minimum tx count
            if features['tx_count'] >= min_tx_count:
                features['address'] = address
                features_list.append(features)
        
        df = pd.DataFrame(features_list)
        
        if len(df) > 0:
            # Move address to first column
            cols = ['address'] + [c for c in df.columns if c != 'address']
            df = df[cols]
        
        print(f"✅ Extracted features for {len(df):,} wallets (min {min_tx_count} txs)")
        return df
    
    def normalize_features(self, df: pd.DataFrame, 
                           method: str = 'standard') -> Tuple[pd.DataFrame, Dict]:
        """
        Normalize features for clustering.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Feature DataFrame
        method : str
            'standard' (z-score) or 'minmax'
            
        Returns:
        --------
        Tuple[pd.DataFrame, Dict]
            Normalized DataFrame and scaler parameters
        """
        from sklearn.preprocessing import StandardScaler, MinMaxScaler
        
        numeric_cols = [c for c in self.FEATURE_COLUMNS if c in df.columns]
        
        if method == 'standard':
            scaler = StandardScaler()
        else:
            scaler = MinMaxScaler()
        
        df_normalized = df.copy()
        df_normalized[numeric_cols] = scaler.fit_transform(df[numeric_cols])
        
        scaler_params = {
            'method': method,
            'mean': scaler.mean_ if hasattr(scaler, 'mean_') else None,
            'scale': scaler.scale_ if hasattr(scaler, 'scale_') else None,
            'feature_names': numeric_cols
        }
        
        print(f"✅ Normalized {len(numeric_cols)} features using {method} scaling")
        return df_normalized, scaler_params
