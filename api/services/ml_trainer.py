"""
ML Training Pipeline for Wallet Classification
Following mission7 patterns with MLflow tracking, SHAP explainability, and data drift detection.
"""
import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import numpy as np
import pandas as pd

import mlflow
import mlflow.sklearn
from mlflow.tracking import MlflowClient

from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    classification_report, confusion_matrix, roc_auc_score,
    precision_recall_curve, f1_score, accuracy_score
)

try:
    import xgboost as xgb
    HAS_XGBOOST = True
except ImportError:
    HAS_XGBOOST = False

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False

try:
    from evidently import ColumnMapping
    from evidently.report import Report
    from evidently.metric_preset import DataDriftPreset, ClassificationPreset
    HAS_EVIDENTLY = True
except ImportError:
    HAS_EVIDENTLY = False

try:
    from imblearn.over_sampling import SMOTE
    from imblearn.pipeline import Pipeline as ImbPipeline
    HAS_IMBLEARN = True
except ImportError:
    HAS_IMBLEARN = False

logger = logging.getLogger(__name__)

# MLflow configuration
MLFLOW_TRACKING_URI = os.environ.get('MLFLOW_TRACKING_URI', 'http://mlflow:5005')
EXPERIMENT_NAME = "wallet_classification"

# Label encoding for wallet types
LABEL_ENCODING = {
    'unknown': 0,
    'exchange': 1,
    'bridge': 2,
    'mixer': 3,
    'defi': 4,
    'whale': 5,
    'bot': 6,
    'normal': 7,
    'attacker': 8,
    'suspect': 9
}

LABEL_DECODING = {v: k for k, v in LABEL_ENCODING.items()}


class WalletMLTrainer:
    """
    ML Training Pipeline for Wallet Classification.
    Follows mission7 patterns with full MLflow integration.
    """
    
    MODEL_VERSION = "1.0.0"
    
    def __init__(self, experiment_name: str = EXPERIMENT_NAME):
        """Initialize trainer with MLflow experiment."""
        self.experiment_name = experiment_name
        self.client = None
        self.model = None
        self.scaler = StandardScaler()
        self.feature_names = []
        self.shap_explainer = None
        
        # Initialize MLflow
        self._init_mlflow()
    
    def _init_mlflow(self):
        """Initialize MLflow tracking."""
        try:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            mlflow.set_experiment(self.experiment_name)
            self.client = MlflowClient()
            logger.info(f"MLflow initialized: {MLFLOW_TRACKING_URI}")
        except Exception as e:
            logger.warning(f"MLflow not available: {e}")
            self.client = None
    
    def prepare_training_data(
        self, session, chain: str = None, token: str = None
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare training data from validated wallet labels.
        Uses GraphQL batch query for efficient feature extraction (single DB scan).
        
        Args:
            session: SQLAlchemy session
            chain: Optional chain trigram filter (e.g. 'ETH', 'POL')
            token: Optional token symbol filter
        
        Returns:
            X: Feature DataFrame
            y: Label Series
        """
        from api.services.fetch_wallet_features_service import (
            fetch_wallet_features_batch, fetch_validated_labels
        )
        
        # Step 1: Get validated labels via GraphQL
        logger.info("Fetching validated labels via GraphQL...")
        label_records = fetch_validated_labels(session, min_confidence=0.8, chain=chain)
        
        if len(label_records) < 50:
            raise ValueError(f"Insufficient training data: {len(label_records)} labels (need at least 50)")
        
        logger.info(f"Found {len(label_records)} validated labels")
        
        # Build address→label mapping
        addr_to_label = {}
        for rec in label_records:
            addr = rec['address'].lower()
            addr_to_label[addr] = rec['label_type'] or 'unknown'
        
        # Step 2: Batch feature extraction via GraphQL (single scan of investigation_transfer)
        addresses = list(addr_to_label.keys())
        logger.info(f"Batch extracting features for {len(addresses)} wallets via GraphQL...")
        
        all_features = fetch_wallet_features_batch(addresses, session)
        
        logger.info(f"Got features for {len(all_features)} wallets")
        
        # Step 3: Align features with labels
        features_list = []
        labels = []
        
        for feat in all_features:
            addr = feat['address'].lower()
            if addr in addr_to_label and feat.get('tx_count', 0) > 0:
                features_list.append({k: v for k, v in feat.items() if k != 'address'})
                labels.append(addr_to_label[addr])
        
        if len(features_list) < 50:
            raise ValueError(f"Insufficient valid features: {len(features_list)} (need at least 50)")
        
        # Create DataFrame
        X = pd.DataFrame(features_list)
        
        # Handle NaN/Inf values
        X = X.fillna(0)
        X = X.replace([float('inf'), float('-inf')], 0)
        
        # Log-transform large-value columns to prevent float32 overflow
        # Raw values from blockchain (wei) can be astronomically large
        value_cols = ['avg_tx_value', 'max_tx_value', 'total_volume']
        for col in value_cols:
            if col in X.columns:
                X[col] = np.log1p(X[col].abs())  # log1p handles 0 gracefully
        
        # Clip any remaining extreme values to prevent float32 overflow
        float32_max = np.finfo(np.float32).max
        X = X.clip(lower=-float32_max, upper=float32_max)
        
        # Use LabelEncoder for contiguous integer labels (required for XGBoost)
        from sklearn.preprocessing import LabelEncoder
        le = LabelEncoder()
        y = pd.Series(le.fit_transform(labels))
        self.label_encoder = le
        self.label_classes = list(le.classes_)
        
        self.feature_names = list(X.columns)
        
        logger.info(f"Training data prepared: {len(X)} samples, {len(self.feature_names)} features, "
                    f"{len(le.classes_)} classes: {dict(zip(le.classes_, range(len(le.classes_))))}")
        
        return X, y
    
    def _extract_features_from_db(
        self, session, address: str, chain_trigram: str, token_symbol: str = None
    ) -> Dict:
        """
        Extract wallet features from per-token transfer tables using dynamic ORM classes.
        Falls back to GraphQL service for investigation_transfer if no per-token tables exist.
        
        Pure SQLAlchemy ORM — zero raw SQL.
        """
        from sqlalchemy import func, inspect as sa_inspect
        from api.application.erc20models import (
            Token, get_transfer_event_class, get_block_transfer_event_class
        )
        
        # Discover available dynamic ORM classes for this chain
        available_classes = []
        
        try:
            tokens = session.query(Token).filter(
                Token.trigram == chain_trigram.upper()
            ).all()
            
            inspector = sa_inspect(session.get_bind())
            existing_tables = set(inspector.get_table_names())
            
            for token in tokens:
                if token_symbol and token.symbol.lower() != token_symbol.lower():
                    continue
                table_name = f"{token.symbol.lower()}_{chain_trigram.lower()}_erc20_transfer_event"
                if table_name in existing_tables:
                    cls = get_transfer_event_class(token.symbol, chain_trigram)
                    if cls:
                        available_classes.append(cls)
        except Exception as e:
            logger.debug(f"Table discovery failed: {e}")
        
        if not available_classes:
            logger.debug(f"No per-token tables for chain {chain_trigram}, using GraphQL fallback")
            from api.services.fetch_wallet_features_service import fetch_wallet_features
            return fetch_wallet_features(address, session) or {}
        
        # Aggregate features across all dynamic ORM classes
        total_out_count = 0
        total_in_count = 0
        total_unique_to = set()
        total_unique_from = set()
        total_values = []
        total_out_volume = 0.0
        total_in_volume = 0.0
        addr_lower = address.lower()
        
        for cls in available_classes:
            try:
                # Outgoing — pure ORM
                out_row = session.query(
                    func.count(cls.id),
                    func.avg(cls.value),
                    func.max(cls.value),
                    func.sum(cls.value),
                ).filter(
                    func.lower(cls.from_contract_address) == addr_lower
                ).first()
                
                # Unique receivers — pure ORM
                unique_to = session.query(
                    func.lower(cls.to_contract_address)
                ).filter(
                    func.lower(cls.from_contract_address) == addr_lower
                ).distinct().all()
                
                # Incoming — pure ORM
                in_row = session.query(
                    func.count(cls.id),
                    func.sum(cls.value),
                ).filter(
                    func.lower(cls.to_contract_address) == addr_lower
                ).first()
                
                # Unique senders — pure ORM
                unique_from = session.query(
                    func.lower(cls.from_contract_address)
                ).filter(
                    func.lower(cls.to_contract_address) == addr_lower
                ).distinct().all()
                
                total_out_count += out_row[0] or 0
                total_in_count += in_row[0] or 0
                
                total_unique_to.update([r[0] for r in unique_to if r[0]])
                total_unique_from.update([r[0] for r in unique_from if r[0]])
                    
                if out_row[1]:
                    total_values.append(float(out_row[1]))
                if out_row[2]:
                    total_values.append(float(out_row[2]))
                    
                total_out_volume += float(out_row[3] or 0)
                total_in_volume += float(in_row[1] or 0)
                
            except Exception as e:
                logger.debug(f"Feature extraction from {cls.__tablename__} failed: {e}")
                continue
        
        if total_out_count + total_in_count == 0:
            return {}
        
        return {
            'tx_count': total_out_count + total_in_count,
            'unique_counterparties': len(total_unique_to) + len(total_unique_from),
            'avg_tx_value': (sum(total_values) / len(total_values) / 1e18) if total_values else 0,
            'max_tx_value': (max(total_values) / 1e18) if total_values else 0,
            'in_out_ratio': (total_in_count / total_out_count) if total_out_count > 0 else 1.0,
            'total_volume': (total_out_volume + total_in_volume) / 1e18,
            'out_count': total_out_count,
            'in_count': total_in_count,
            'unique_senders': len(total_unique_from),
            'unique_receivers': len(total_unique_to),
        }
    
    def _extract_features_from_investigation_transfers(
        self, session, address: str
    ) -> Dict:
        """
        Extract wallet features from investigation_transfer using pure SQLAlchemy ORM.
        Zero raw SQL.
        """
        from sqlalchemy import func, case, or_
        
        T = InvestigationTransfer
        addr_lower = address.lower()
        is_sender = func.lower(T.from_address) == addr_lower
        is_receiver = func.lower(T.to_address) == addr_lower
        
        try:
            row = session.query(
                func.sum(case((is_sender, 1), else_=0)).label('out_count'),
                func.sum(case((is_receiver, 1), else_=0)).label('in_count'),
                func.count(func.distinct(case((is_sender, T.to_address)))).label('unique_to'),
                func.count(func.distinct(case((is_receiver, T.from_address)))).label('unique_from'),
                func.avg(case((is_sender, func.coalesce(T.value, 0)))).label('avg_out_value'),
                func.max(case((is_sender, func.coalesce(T.value, 0)))).label('max_out_value'),
                func.sum(case((is_sender, func.coalesce(T.value, 0)), else_=0)).label('total_out'),
                func.sum(case((is_receiver, func.coalesce(T.value, 0)), else_=0)).label('total_in'),
            ).filter(or_(is_sender, is_receiver)).first()
            
            if row is None:
                return {}
            
            out_count = int(row.out_count or 0)
            in_count = int(row.in_count or 0)
            
            if out_count + in_count == 0:
                return {}
            
            return {
                'tx_count': out_count + in_count,
                'unique_counterparties': int(row.unique_to or 0) + int(row.unique_from or 0),
                'avg_tx_value': float(row.avg_out_value or 0),
                'max_tx_value': float(row.max_out_value or 0),
                'in_out_ratio': (in_count / out_count) if out_count > 0 else 1.0,
                'total_volume': float(row.total_out or 0) + float(row.total_in or 0),
                'out_count': out_count,
                'in_count': in_count,
                'unique_senders': int(row.unique_from or 0),
                'unique_receivers': int(row.unique_to or 0),
            }
        except Exception as e:
            logger.warning(f"Feature extraction from investigation_transfer failed for {address}: {e}")
            return {}
    
    def train_model(
        self, 
        X: pd.DataFrame, 
        y: pd.Series,
        model_type: str = 'xgboost',
        run_name: str = None,
        test_size: float = 0.2,
        use_smote: bool = True
    ) -> Dict:
        """
        Train wallet classification model with MLflow tracking.
        
        Args:
            X: Feature DataFrame
            y: Label Series  
            model_type: 'xgboost', 'random_forest', or 'gradient_boosting'
            run_name: MLflow run name
            
        Returns:
            Dict with training results and metrics
        """
        run_name = run_name or f"wallet_classifier_{model_type}_{datetime.now().strftime('%Y%m%d_%H%M')}"
        
        # Select model
        if model_type == 'xgboost' and HAS_XGBOOST:
            n_classes = len(set(y))
            base_model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                objective='multi:softprob',
                num_class=n_classes,
                random_state=42,
                use_label_encoder=False,
                eval_metric='mlogloss'
            )
        elif model_type == 'random_forest':
            base_model = RandomForestClassifier(
                n_estimators=100,
                max_depth=10,
                random_state=42,
                n_jobs=-1
            )
        else:
            base_model = GradientBoostingClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                random_state=42
            )
        
        # Create pipeline (use SMOTE for class balancing if available and requested)
        if use_smote and HAS_IMBLEARN and len(y.unique()) > 1:
            min_class_size = y.value_counts().min()
            k = min(5, max(1, min_class_size - 1))
            pipeline = ImbPipeline([
                ('scaler', StandardScaler()),
                ('smote', SMOTE(random_state=42, k_neighbors=k)),
                ('classifier', base_model)
            ])
        else:
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('classifier', base_model)
            ])
        
        # Cross-validation (adjust folds based on data size)
        n_splits = min(5, max(2, int(1.0 / test_size))) if test_size > 0 else 5
        min_class_count = y.value_counts().min()
        n_splits = min(n_splits, min_class_count)  # Can't have more folds than smallest class
        n_splits = max(2, n_splits)
        
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        cv_scores = cross_val_score(pipeline, X, y, cv=cv, scoring='f1_weighted')
        
        # Train final model
        pipeline.fit(X, y)
        self.model = pipeline
        
        # Predictions for metrics
        y_pred = pipeline.predict(X)
        y_proba = pipeline.predict_proba(X) if hasattr(pipeline, 'predict_proba') else None
        
        # Calculate metrics
        metrics = {
            'accuracy': accuracy_score(y, y_pred),
            'f1_weighted': f1_score(y, y_pred, average='weighted'),
            'cv_mean': cv_scores.mean(),
            'cv_std': cv_scores.std(),
        }
        
        if y_proba is not None:
            try:
                metrics['roc_auc'] = roc_auc_score(y, y_proba, multi_class='ovr', average='weighted')
            except:
                pass
        
        # Log to MLflow
        if self.client:
            with mlflow.start_run(run_name=run_name) as run:
                # Log parameters
                mlflow.log_param("model_type", model_type)
                mlflow.log_param("n_samples", len(X))
                mlflow.log_param("n_features", len(self.feature_names))
                mlflow.log_param("model_version", self.MODEL_VERSION)
                
                # Log metrics
                for name, value in metrics.items():
                    mlflow.log_metric(name, value)
                
                # Log model (wrapped in try/except for MLflow version compatibility)
                try:
                    mlflow.sklearn.log_model(pipeline, "model")
                except Exception as model_log_err:
                    logger.warning(f"MLflow log_model failed (version mismatch?): {model_log_err}")
                    # Still save model locally as fallback
                    try:
                        import pickle
                        import os
                        model_dir = os.path.join('/tmp', 'bubble_models')
                        os.makedirs(model_dir, exist_ok=True)
                        model_path = os.path.join(model_dir, f'{model_type}_model.pkl')
                        with open(model_path, 'wb') as f:
                            pickle.dump(pipeline, f)
                        mlflow.log_artifact(model_path, 'model')
                        logger.info(f"Model saved as artifact: {model_path}")
                    except Exception as fallback_err:
                        logger.warning(f"Fallback model save also failed: {fallback_err}")
                
                # Log feature names
                mlflow.log_dict({"features": self.feature_names}, "feature_names.json")
                
                # Log classification report
                report = classification_report(y, y_pred, output_dict=True)
                mlflow.log_dict(report, "classification_report.json")
                
                # Compute and log SHAP values
                if HAS_SHAP:
                    shap_summary = self._compute_shap_importance(X, pipeline)
                    if shap_summary:
                        mlflow.log_dict(shap_summary, "shap_importance.json")
                
                run_id = run.info.run_id
                metrics['run_id'] = run_id
                
                logger.info(f"Model trained and logged to MLflow: {run_id}")
        
        return {
            'status': 'success',
            'model_type': model_type,
            'metrics': metrics,
            'feature_names': self.feature_names,
            'class_distribution': dict(y.value_counts())
        }
    
    def _compute_shap_importance(self, X: pd.DataFrame, pipeline) -> Optional[Dict]:
        """Compute SHAP feature importance."""
        if not HAS_SHAP:
            return None
        
        try:
            # Get the classifier from pipeline
            if hasattr(pipeline, 'named_steps'):
                classifier = pipeline.named_steps['classifier']
                scaler = pipeline.named_steps['scaler']
                X_scaled = scaler.transform(X)
            else:
                classifier = pipeline
                X_scaled = X.values
            
            # Sample for SHAP (limit to 100 samples for speed)
            sample_size = min(100, len(X))
            X_sample = X_scaled[:sample_size] if isinstance(X_scaled, np.ndarray) else X_scaled.iloc[:sample_size]
            
            # Create explainer based on model type
            if hasattr(classifier, 'feature_importances_'):
                # Tree-based model
                explainer = shap.TreeExplainer(classifier)
            else:
                # Generic model
                explainer = shap.KernelExplainer(classifier.predict_proba, X_sample[:10])
            
            # Compute SHAP values
            shap_values = explainer.shap_values(X_sample)
            
            # Handle different SHAP output formats
            if isinstance(shap_values, list):
                # Multi-class: average across classes
                shap_values = np.abs(np.array(shap_values)).mean(axis=0)
            
            # Calculate mean absolute SHAP per feature
            mean_shap = np.abs(shap_values).mean(axis=0)
            
            # Create importance dict
            importance = {
                self.feature_names[i]: float(mean_shap[i])
                for i in range(len(self.feature_names))
            }
            
            # Sort by importance
            sorted_importance = dict(
                sorted(importance.items(), key=lambda x: x[1], reverse=True)
            )
            
            self.shap_explainer = explainer
            
            return {
                'feature_importance': sorted_importance,
                'method': 'SHAP TreeExplainer' if hasattr(classifier, 'feature_importances_') else 'SHAP KernelExplainer'
            }
            
        except Exception as e:
            logger.warning(f"SHAP computation failed: {e}")
            return None
    
    def explain_prediction(self, features: Dict, address: str = None) -> Dict:
        """
        Generate SHAP explanation for a single prediction.
        
        Args:
            features: Wallet features dict
            address: Wallet address (for logging)
            
        Returns:
            Dict with prediction and SHAP explanations
        """
        if self.model is None:
            return {'error': 'Model not trained'}
        
        if not HAS_SHAP:
            return {'error': 'SHAP not available'}
        
        try:
            # Prepare features
            X = pd.DataFrame([features])[self.feature_names]
            
            # Get prediction
            pred_proba = self.model.predict_proba(X)[0]
            pred_class = self.model.predict(X)[0]
            
            # Get SHAP values for this prediction
            if hasattr(self.model, 'named_steps'):
                scaler = self.model.named_steps['scaler']
                classifier = self.model.named_steps['classifier']
                X_scaled = scaler.transform(X)
            else:
                classifier = self.model
                X_scaled = X.values
            
            # Compute SHAP for this instance
            if self.shap_explainer is None:
                if hasattr(classifier, 'feature_importances_'):
                    self.shap_explainer = shap.TreeExplainer(classifier)
                else:
                    return {'error': 'SHAP explainer not initialized'}
            
            shap_values = self.shap_explainer.shap_values(X_scaled)
            
            # Handle multi-class output
            if isinstance(shap_values, list):
                # Get SHAP values for predicted class
                instance_shap = shap_values[pred_class][0]
            else:
                instance_shap = shap_values[0]
            
            # Create explanation
            explanation = {
                'address': address,
                'predicted_class': LABEL_DECODING.get(pred_class, 'unknown'),
                'confidence': float(pred_proba[pred_class]),
                'probabilities': {
                    LABEL_DECODING.get(i, f'class_{i}'): float(p)
                    for i, p in enumerate(pred_proba)
                },
                'shap_values': {
                    self.feature_names[i]: {
                        'value': float(features.get(self.feature_names[i], 0)),
                        'shap_contribution': float(instance_shap[i])
                    }
                    for i in range(len(self.feature_names))
                },
                'top_positive_factors': [],
                'top_negative_factors': []
            }
            
            # Sort SHAP contributions
            shap_contributions = [
                (self.feature_names[i], float(instance_shap[i]))
                for i in range(len(self.feature_names))
            ]
            shap_contributions.sort(key=lambda x: x[1], reverse=True)
            
            explanation['top_positive_factors'] = [
                {'feature': name, 'contribution': val}
                for name, val in shap_contributions[:3] if val > 0
            ]
            explanation['top_negative_factors'] = [
                {'feature': name, 'contribution': val}
                for name, val in shap_contributions[-3:] if val < 0
            ]
            
            return explanation
            
        except Exception as e:
            logger.error(f"SHAP explanation failed: {e}")
            return {'error': str(e)}
    
    def check_data_drift(
        self, 
        reference_data: pd.DataFrame, 
        current_data: pd.DataFrame
    ) -> Dict:
        """
        Check for data drift between training and production data.
        Uses Evidently for drift detection.
        
        Args:
            reference_data: Training/baseline data
            current_data: Current production data
            
        Returns:
            Dict with drift report
        """
        if not HAS_EVIDENTLY:
            return {'error': 'Evidently not available'}
        
        try:
            # Create column mapping
            column_mapping = ColumnMapping(
                numerical_features=self.feature_names
            )
            
            # Create drift report
            report = Report(metrics=[DataDriftPreset()])
            report.run(
                reference_data=reference_data,
                current_data=current_data,
                column_mapping=column_mapping
            )
            
            # Extract results
            result = report.as_dict()
            
            # Parse drift metrics
            drift_summary = {
                'dataset_drift': result.get('metrics', [{}])[0].get('result', {}).get('dataset_drift', False),
                'drift_share': result.get('metrics', [{}])[0].get('result', {}).get('drift_share', 0),
                'drifted_features': [],
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # Get per-feature drift
            columns_data = result.get('metrics', [{}])[0].get('result', {}).get('drift_by_columns', {})
            for col, col_data in columns_data.items():
                if col_data.get('drift_detected', False):
                    drift_summary['drifted_features'].append({
                        'feature': col,
                        'drift_score': col_data.get('drift_score', 0),
                        'stattest': col_data.get('stattest_name', 'unknown')
                    })
            
            # Log to MLflow
            if self.client:
                with mlflow.start_run(run_name=f"drift_check_{datetime.now().strftime('%Y%m%d_%H%M')}"):
                    mlflow.log_metric("drift_share", drift_summary['drift_share'])
                    mlflow.log_metric("dataset_drift", 1 if drift_summary['dataset_drift'] else 0)
                    mlflow.log_dict(drift_summary, "drift_report.json")
            
            return drift_summary
            
        except Exception as e:
            logger.error(f"Drift detection failed: {e}")
            return {'error': str(e)}
    
    def load_production_model(self, run_id: str = None) -> bool:
        """
        Load a model from MLflow for production use.
        
        Args:
            run_id: Specific run ID, or None for latest
            
        Returns:
            True if successful
        """
        try:
            if run_id:
                model_uri = f"runs:/{run_id}/model"
            else:
                # Get latest run from experiment
                experiment = self.client.get_experiment_by_name(self.experiment_name)
                if experiment:
                    runs = self.client.search_runs(
                        experiment_ids=[experiment.experiment_id],
                        order_by=["start_time DESC"],
                        max_results=1
                    )
                    if runs:
                        model_uri = f"runs:/{runs[0].info.run_id}/model"
                    else:
                        return False
                else:
                    return False
            
            self.model = mlflow.sklearn.load_model(model_uri)
            
            # Load feature names
            features_uri = model_uri.replace("/model", "/feature_names.json")
            try:
                features_artifact = mlflow.artifacts.load_dict(features_uri)
                self.feature_names = features_artifact.get('features', [])
            except:
                pass
            
            logger.info(f"Loaded production model from {model_uri}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            return False
    
    def register_model(self, run_id: str, model_name: str = "wallet_classifier") -> Dict:
        """
        Register model in MLflow Model Registry.
        
        Args:
            run_id: Run ID of the model to register
            model_name: Name for the registered model
            
        Returns:
            Dict with registration info
        """
        try:
            model_uri = f"runs:/{run_id}/model"
            
            # Register model
            result = mlflow.register_model(model_uri, model_name)
            
            return {
                'status': 'success',
                'model_name': model_name,
                'version': result.version,
                'run_id': run_id
            }
            
        except Exception as e:
            logger.error(f"Model registration failed: {e}")
            return {'error': str(e)}
    
    def promote_model(
        self, 
        model_name: str, 
        version: int, 
        stage: str = "Production"
    ) -> Dict:
        """
        Promote model version to a stage (Staging/Production).
        
        Args:
            model_name: Registered model name
            version: Model version number
            stage: Target stage
            
        Returns:
            Dict with promotion result
        """
        try:
            self.client.transition_model_version_stage(
                name=model_name,
                version=version,
                stage=stage
            )
            
            return {
                'status': 'success',
                'model_name': model_name,
                'version': version,
                'stage': stage
            }
            
        except Exception as e:
            logger.error(f"Model promotion failed: {e}")
            return {'error': str(e)}


# Singleton instance
_trainer_instance = None

def get_ml_trainer() -> WalletMLTrainer:
    """Get or create ML trainer singleton."""
    global _trainer_instance
    if _trainer_instance is None:
        _trainer_instance = WalletMLTrainer()
    return _trainer_instance
