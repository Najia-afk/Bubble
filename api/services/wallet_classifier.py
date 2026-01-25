# api/services/wallet_classifier.py
"""
Wallet Classification Service
Uses clustering and heuristics to classify unknown wallet addresses.
Suggests labels based on transaction patterns and behavior.
"""
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from sqlalchemy import text, func
from sklearn.preprocessing import StandardScaler
from sklearn.cluster import KMeans, DBSCAN
import pickle
import os

from utils.database import get_session_factory
from utils.logging_config import setup_logging
from api.application.erc20models import (
    WalletLabel, WalletScore, KnownBridge, 
    CHAIN_ID_TO_TRIGRAM, TRIGRAM_TO_CHAIN_ID, Base
)

logger = setup_logging('wallet_classifier.log')

# Cluster to label type mapping (trained from known labels)
CLUSTER_LABEL_MAP = {
    0: ('normal', 0.5),      # Regular user wallet
    1: ('whale', 0.7),       # High volume trader
    2: ('exchange', 0.6),    # Exchange-like behavior
    3: ('bot', 0.65),        # MEV/trading bot
    4: ('bridge', 0.6),      # Bridge-like behavior
    5: ('defi', 0.55),       # DeFi protocol user
}

# Feature thresholds for heuristic classification
EXCHANGE_THRESHOLDS = {
    'min_unique_counterparties': 100,
    'min_tx_count': 500,
    'in_out_ratio_range': (0.8, 1.2),  # Roughly balanced
}

BRIDGE_THRESHOLDS = {
    'min_tx_count': 50,
    'high_avg_value': 1000,  # High average tx value
    'in_out_ratio_range': (0.9, 1.1),  # Very balanced
}

WHALE_THRESHOLDS = {
    'min_total_volume': 100000,
    'min_max_tx_value': 10000,
}

BOT_THRESHOLDS = {
    'min_tx_count': 1000,
    'max_unique_counterparties_ratio': 0.1,  # Few unique addresses relative to tx count
}


class WalletClassifier:
    """
    Classifies wallets based on transaction patterns.
    Uses both ML clustering and rule-based heuristics.
    """
    
    MODEL_VERSION = "1.0.0"
    
    def __init__(self):
        self.session_factory = get_session_factory()
        self.scaler = StandardScaler()
        self.kmeans = None
        self.dbscan = None
        self._load_or_init_models()
    
    def _load_or_init_models(self):
        """Load pre-trained models or initialize new ones"""
        model_path = os.path.join(os.path.dirname(__file__), 'models')
        kmeans_path = os.path.join(model_path, 'wallet_kmeans.pkl')
        scaler_path = os.path.join(model_path, 'wallet_scaler.pkl')
        
        if os.path.exists(kmeans_path) and os.path.exists(scaler_path):
            try:
                with open(kmeans_path, 'rb') as f:
                    self.kmeans = pickle.load(f)
                with open(scaler_path, 'rb') as f:
                    self.scaler = pickle.load(f)
                logger.info("Loaded pre-trained wallet classifier models")
            except Exception as e:
                logger.warning(f"Could not load models: {e}. Will use heuristics only.")
                self.kmeans = None
        else:
            logger.info("No pre-trained models found. Using heuristics-only mode.")
            self.kmeans = None
    
    def extract_features(self, address: str, chain_trigram: str, session=None) -> Optional[Dict]:
        """
        Extract features for a wallet address from transfer data.
        
        Returns dict with:
        - tx_count: Total number of transactions
        - unique_counterparties: Number of unique addresses interacted with
        - avg_tx_value: Average transaction value
        - max_tx_value: Maximum single transaction value
        - total_volume: Total volume (in + out)
        - in_out_ratio: Ratio of incoming to outgoing transactions
        - active_days: Number of unique days with activity
        - first_seen: First transaction timestamp
        - last_seen: Last transaction timestamp
        """
        close_session = False
        if session is None:
            session = self.session_factory()
            close_session = True
        
        try:
            chain_id = TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1)
            
            # Try to get features from all token transfer tables
            # Start with common tokens (GHST on POL)
            features = self._extract_features_from_tables(address, chain_trigram, session)
            
            if features is None:
                return None
            
            features['chain_id'] = chain_id
            features['chain_trigram'] = chain_trigram
            
            return features
            
        except Exception as e:
            logger.error(f"Error extracting features for {address}: {e}")
            return None
        finally:
            if close_session:
                session.close()
    
    def _extract_features_from_tables(self, address: str, chain_trigram: str, session) -> Optional[Dict]:
        """Extract features by querying transfer event tables"""
        address_lower = address.lower()
        
        # Find transfer tables for this chain
        query = text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_name LIKE :pattern
        """)
        result = session.execute(query, {'pattern': f'%_{chain_trigram.lower()}_erc20_transfer_event'})
        tables = [row[0] for row in result.fetchall()]
        
        if not tables:
            logger.debug(f"No transfer tables found for chain {chain_trigram}")
            return None
        
        # Aggregate features across all token tables
        total_tx_in = 0
        total_tx_out = 0
        total_value_in = 0.0
        total_value_out = 0.0
        max_value = 0.0
        counterparties = set()
        timestamps = []
        
        for table_name in tables:
            try:
                # Incoming transactions
                in_query = text(f"""
                    SELECT COUNT(*), COALESCE(SUM(value), 0), COALESCE(MAX(value), 0),
                           array_agg(DISTINCT from_contract_address)
                    FROM {table_name}
                    WHERE LOWER(to_contract_address) = :addr
                """)
                in_result = session.execute(in_query, {'addr': address_lower}).fetchone()
                
                if in_result and in_result[0]:
                    total_tx_in += in_result[0]
                    total_value_in += float(in_result[1] or 0) / 1e18
                    max_value = max(max_value, float(in_result[2] or 0) / 1e18)
                    if in_result[3]:
                        counterparties.update([a.lower() for a in in_result[3] if a])
                
                # Outgoing transactions
                out_query = text(f"""
                    SELECT COUNT(*), COALESCE(SUM(value), 0), COALESCE(MAX(value), 0),
                           array_agg(DISTINCT to_contract_address)
                    FROM {table_name}
                    WHERE LOWER(from_contract_address) = :addr
                """)
                out_result = session.execute(out_query, {'addr': address_lower}).fetchone()
                
                if out_result and out_result[0]:
                    total_tx_out += out_result[0]
                    total_value_out += float(out_result[1] or 0) / 1e18
                    max_value = max(max_value, float(out_result[2] or 0) / 1e18)
                    if out_result[3]:
                        counterparties.update([a.lower() for a in out_result[3] if a])
                
            except Exception as e:
                logger.debug(f"Error querying table {table_name}: {e}")
                continue
        
        total_tx = total_tx_in + total_tx_out
        if total_tx == 0:
            return None
        
        total_volume = total_value_in + total_value_out
        avg_value = total_volume / total_tx if total_tx > 0 else 0
        in_out_ratio = total_tx_in / total_tx_out if total_tx_out > 0 else float('inf')
        
        return {
            'tx_count': total_tx,
            'tx_in_count': total_tx_in,
            'tx_out_count': total_tx_out,
            'unique_counterparties': len(counterparties),
            'avg_tx_value': avg_value,
            'max_tx_value': max_value,
            'total_volume': total_volume,
            'in_out_ratio': in_out_ratio if in_out_ratio != float('inf') else 100.0,
            'active_days': 1,  # Would need timestamp data for accurate count
        }
    
    def classify_by_heuristics(self, features: Dict) -> Tuple[str, float]:
        """
        Classify wallet using rule-based heuristics.
        Returns (predicted_type, confidence)
        """
        tx_count = features.get('tx_count', 0)
        unique_cp = features.get('unique_counterparties', 0)
        avg_value = features.get('avg_tx_value', 0)
        max_value = features.get('max_tx_value', 0)
        total_volume = features.get('total_volume', 0)
        in_out_ratio = features.get('in_out_ratio', 1.0)
        
        scores = {}
        
        # Exchange detection
        if (unique_cp >= EXCHANGE_THRESHOLDS['min_unique_counterparties'] and
            tx_count >= EXCHANGE_THRESHOLDS['min_tx_count']):
            ratio_range = EXCHANGE_THRESHOLDS['in_out_ratio_range']
            if ratio_range[0] <= in_out_ratio <= ratio_range[1]:
                scores['exchange'] = 0.8
            else:
                scores['exchange'] = 0.5
        
        # Bridge detection
        if (tx_count >= BRIDGE_THRESHOLDS['min_tx_count'] and
            avg_value >= BRIDGE_THRESHOLDS['high_avg_value']):
            ratio_range = BRIDGE_THRESHOLDS['in_out_ratio_range']
            if ratio_range[0] <= in_out_ratio <= ratio_range[1]:
                scores['bridge'] = 0.75
            else:
                scores['bridge'] = 0.4
        
        # Whale detection
        if (total_volume >= WHALE_THRESHOLDS['min_total_volume'] or
            max_value >= WHALE_THRESHOLDS['min_max_tx_value']):
            scores['whale'] = 0.7
        
        # Bot detection
        if tx_count >= BOT_THRESHOLDS['min_tx_count']:
            cp_ratio = unique_cp / tx_count if tx_count > 0 else 1
            if cp_ratio <= BOT_THRESHOLDS['max_unique_counterparties_ratio']:
                scores['bot'] = 0.65
        
        # DeFi user detection (moderate activity, high value)
        if 10 <= tx_count <= 500 and avg_value >= 100:
            scores['defi'] = 0.5
        
        # Default: normal user
        if not scores:
            scores['normal'] = 0.6
        
        # Return highest scoring type
        best_type = max(scores.keys(), key=lambda k: scores[k])
        return best_type, scores[best_type]
    
    def classify_by_clustering(self, features: Dict) -> Tuple[Optional[int], bool, float]:
        """
        Classify using K-means clustering and DBSCAN anomaly detection.
        Returns (cluster_id, is_anomaly, anomaly_score)
        """
        if self.kmeans is None:
            return None, False, 0.0
        
        # Prepare feature vector
        feature_vector = np.array([[
            features.get('tx_count', 0),
            features.get('unique_counterparties', 0),
            features.get('avg_tx_value', 0),
            features.get('max_tx_value', 0),
            features.get('in_out_ratio', 1.0),
        ]])
        
        try:
            # Scale features
            scaled = self.scaler.transform(feature_vector)
            
            # K-means cluster assignment
            cluster_id = int(self.kmeans.predict(scaled)[0])
            
            # Calculate distance to cluster center (anomaly score)
            center = self.kmeans.cluster_centers_[cluster_id]
            distance = np.linalg.norm(scaled[0] - center)
            
            # Anomaly if distance > 2 std deviations
            is_anomaly = distance > 2.0
            
            return cluster_id, is_anomaly, float(distance)
            
        except Exception as e:
            logger.warning(f"Clustering error: {e}")
            return None, False, 0.0
    
    def classify(self, address: str, chain_trigram: str = 'ETH', save_result: bool = True) -> Dict:
        """
        Full classification pipeline for a wallet address.
        
        Args:
            address: Wallet address to classify
            chain_trigram: Chain (ETH, POL, BSC, BASE)
            save_result: Whether to save result to wallet_score table
            
        Returns:
            Classification result dict
        """
        session = self.session_factory()
        
        try:
            # Check for existing labels first
            existing_labels = session.query(WalletLabel).filter(
                WalletLabel.address == address.lower(),
                WalletLabel.chain_id == TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1)
            ).all()
            
            if existing_labels:
                trusted_labels = [l for l in existing_labels if l.is_trusted]
                if trusted_labels:
                    return {
                        'address': address,
                        'chain': chain_trigram,
                        'predicted_type': trusted_labels[0].label_type or trusted_labels[0].label,
                        'confidence': 1.0,
                        'source': 'trusted_label',
                        'existing_labels': [l.label for l in existing_labels]
                    }
            
            # Extract features
            features = self.extract_features(address, chain_trigram, session)
            
            if features is None:
                return {
                    'address': address,
                    'chain': chain_trigram,
                    'predicted_type': 'unknown',
                    'confidence': 0.0,
                    'source': 'no_data',
                    'message': 'No transaction data found for this address'
                }
            
            # Heuristic classification
            heuristic_type, heuristic_conf = self.classify_by_heuristics(features)
            
            # Clustering classification
            cluster_id, is_anomaly, anomaly_score = self.classify_by_clustering(features)
            
            # Combine results (prefer heuristics if confident, else use clustering)
            if heuristic_conf >= 0.7:
                final_type = heuristic_type
                final_conf = heuristic_conf
            elif cluster_id is not None and cluster_id in CLUSTER_LABEL_MAP:
                cluster_type, cluster_conf = CLUSTER_LABEL_MAP[cluster_id]
                final_type = cluster_type
                final_conf = cluster_conf
            else:
                final_type = heuristic_type
                final_conf = heuristic_conf
            
            result = {
                'address': address,
                'chain': chain_trigram,
                'predicted_type': final_type,
                'confidence': round(final_conf, 3),
                'source': 'ml_classification',
                'features': {
                    'tx_count': features.get('tx_count'),
                    'unique_counterparties': features.get('unique_counterparties'),
                    'avg_tx_value': round(features.get('avg_tx_value', 0), 4),
                    'max_tx_value': round(features.get('max_tx_value', 0), 4),
                    'total_volume': round(features.get('total_volume', 0), 4),
                    'in_out_ratio': round(features.get('in_out_ratio', 1), 3),
                },
                'clustering': {
                    'cluster_id': cluster_id,
                    'is_anomaly': is_anomaly,
                    'anomaly_score': round(anomaly_score, 3) if anomaly_score else None,
                },
                'existing_labels': [l.label for l in existing_labels] if existing_labels else []
            }
            
            # Save to database
            if save_result:
                self._save_score(address, chain_trigram, features, result, session)
            
            return result
            
        except Exception as e:
            logger.error(f"Classification error for {address}: {e}", exc_info=True)
            return {
                'address': address,
                'chain': chain_trigram,
                'predicted_type': 'error',
                'confidence': 0.0,
                'error': str(e)
            }
        finally:
            session.close()
    
    def _save_score(self, address: str, chain_trigram: str, features: Dict, result: Dict, session):
        """Save classification result to wallet_score table"""
        try:
            chain_id = TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1)
            
            # Ensure table exists
            Base.metadata.create_all(session.get_bind(), tables=[WalletScore.__table__])
            
            # Upsert score
            existing = session.query(WalletScore).filter_by(
                address=address.lower(),
                chain_id=chain_id
            ).first()
            
            score_data = {
                'predicted_type': result['predicted_type'],
                'confidence': result['confidence'],
                'cluster_id': result['clustering'].get('cluster_id'),
                'is_anomaly': result['clustering'].get('is_anomaly', False),
                'anomaly_score': result['clustering'].get('anomaly_score'),
                'feature_tx_count': features.get('tx_count'),
                'feature_unique_counterparties': features.get('unique_counterparties'),
                'feature_avg_tx_value': features.get('avg_tx_value'),
                'feature_max_tx_value': features.get('max_tx_value'),
                'feature_in_out_ratio': features.get('in_out_ratio'),
                'model_version': self.MODEL_VERSION,
                'scored_at': datetime.utcnow(),
            }
            
            # Set type-specific scores
            pred_type = result['predicted_type']
            conf = result['confidence']
            score_data[f'score_{pred_type}'] = conf if pred_type in ['exchange', 'bridge', 'mixer', 'defi', 'whale', 'bot'] else 0.0
            
            if existing:
                for key, value in score_data.items():
                    setattr(existing, key, value)
            else:
                score = WalletScore(
                    address=address.lower(),
                    chain_id=chain_id,
                    **score_data
                )
                session.add(score)
            
            session.commit()
            logger.debug(f"Saved score for {address}: {result['predicted_type']} ({result['confidence']})")
            
        except Exception as e:
            session.rollback()
            logger.warning(f"Could not save score for {address}: {e}")
    
    def batch_classify(self, addresses: List[str], chain_trigram: str = 'ETH') -> List[Dict]:
        """Classify multiple addresses"""
        results = []
        for address in addresses:
            result = self.classify(address, chain_trigram)
            results.append(result)
        return results
    
    def find_similar_wallets(self, address: str, chain_trigram: str = 'ETH', limit: int = 10) -> List[Dict]:
        """Find wallets with similar behavior patterns"""
        session = self.session_factory()
        
        try:
            chain_id = TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1)
            
            # Get target wallet's score
            target = session.query(WalletScore).filter_by(
                address=address.lower(),
                chain_id=chain_id
            ).first()
            
            if not target:
                # Classify first
                self.classify(address, chain_trigram)
                target = session.query(WalletScore).filter_by(
                    address=address.lower(),
                    chain_id=chain_id
                ).first()
            
            if not target or target.cluster_id is None:
                return []
            
            # Find wallets in same cluster
            similar = session.query(WalletScore).filter(
                WalletScore.chain_id == chain_id,
                WalletScore.cluster_id == target.cluster_id,
                WalletScore.address != address.lower()
            ).limit(limit).all()
            
            return [
                {
                    'address': w.address,
                    'predicted_type': w.predicted_type,
                    'confidence': w.confidence,
                    'tx_count': w.feature_tx_count,
                }
                for w in similar
            ]
            
        finally:
            session.close()


# Singleton instance
_classifier = None

def get_wallet_classifier() -> WalletClassifier:
    """Get or create wallet classifier instance"""
    global _classifier
    if _classifier is None:
        _classifier = WalletClassifier()
    return _classifier
