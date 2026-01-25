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
    'normal': 7
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
    
    def prepare_training_data(self, session) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare training data from validated wallet labels.
        
        Returns:
            X: Feature DataFrame
            y: Label Series
        """
        from api.application.erc20models import WalletLabel, WalletScore, CHAIN_ID_TO_TRIGRAM
        from sqlalchemy import text
        
        # Get validated labels
        validated_labels = session.query(WalletLabel).filter(
            WalletLabel.confidence >= 0.8
        ).all()
        
        if len(validated_labels) < 50:
            raise ValueError(f"Insufficient training data: {len(validated_labels)} labels (need at least 50)")
        
        # Extract features for each labeled wallet
        features_list = []
        labels = []
        
        for label in validated_labels:
            chain_trigram = CHAIN_ID_TO_TRIGRAM.get(label.chain_id, 'ETH')
            
            # Get existing score if available (has pre-computed features)
            score = session.query(WalletScore).filter_by(
                address=label.address.lower(),
                chain_id=label.chain_id
            ).first()
            
            if score and score.feature_tx_count:
                features = {
                    'tx_count': score.feature_tx_count or 0,
                    'unique_counterparties': score.feature_unique_counterparties or 0,
                    'avg_tx_value': score.feature_avg_tx_value or 0,
                    'max_tx_value': score.feature_max_tx_value or 0,
                    'in_out_ratio': score.feature_in_out_ratio or 1.0,
                }
            else:
                # Extract features from raw transactions
                features = self._extract_features_from_db(
                    session, label.address, chain_trigram
                )
            
            if features and features.get('tx_count', 0) > 0:
                features_list.append(features)
                labels.append(LABEL_ENCODING.get(label.label_type, 0))
        
        if len(features_list) < 50:
            raise ValueError(f"Insufficient valid features: {len(features_list)} (need at least 50)")
        
        # Create DataFrame
        X = pd.DataFrame(features_list)
        y = pd.Series(labels)
        
        self.feature_names = list(X.columns)
        
        logger.info(f"Training data prepared: {len(X)} samples, {len(self.feature_names)} features")
        
        return X, y
    
    def _extract_features_from_db(
        self, session, address: str, chain_trigram: str, token_symbol: str = None
    ) -> Dict:
        """
        Extract wallet features from transaction tables.
        Supports ANY token on ANY EVM chain - no hardcoded token references.
        
        Args:
            session: SQLAlchemy session
            address: Wallet address to extract features for
            chain_trigram: Chain identifier (ETH, POL, BSC, BASE, ARB, OP, AVAX, FTM)
            token_symbol: Optional token symbol to filter transfers (None = all tokens)
        """
        from sqlalchemy import text
        from api.application.erc20models import Token
        
        # Discover available transfer tables dynamically
        # Pattern: {symbol}_{chain}_erc20_transfer_event
        available_tables = []
        
        try:
            # Get all tokens for this chain
            tokens = session.query(Token).filter(
                Token.trigram == chain_trigram.upper()
            ).all()
            
            for token in tokens:
                if token_symbol and token.symbol.lower() != token_symbol.lower():
                    continue
                table_name = f"{token.symbol.lower()}_{chain_trigram.lower()}_erc20_transfer_event"
                # Check if table exists
                check_query = text("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = :table_name
                    )
                """)
                exists = session.execute(check_query, {'table_name': table_name}).scalar()
                if exists:
                    available_tables.append(table_name)
        except Exception as e:
            logger.debug(f"Table discovery failed: {e}")
        
        if not available_tables:
            logger.debug(f"No transfer tables found for chain {chain_trigram}")
            return {}
        
        # Aggregate features across all available token tables
        total_out_count = 0
        total_in_count = 0
        total_unique_to = set()
        total_unique_from = set()
        total_values = []
        total_out_volume = 0.0
        total_in_volume = 0.0
        
        for table_name in available_tables:
            try:
                # Outgoing transactions
                out_query = text(f"""
                    SELECT COUNT(*) as tx_count, 
                           ARRAY_AGG(DISTINCT to_contract_address) as unique_to,
                           AVG(value) as avg_value,
                           MAX(value) as max_value,
                           SUM(value) as total_out
                    FROM {table_name}
                    WHERE LOWER(from_contract_address) = :addr
                """)
                out_result = session.execute(out_query, {'addr': address.lower()}).fetchone()
                
                # Incoming transactions
                in_query = text(f"""
                    SELECT COUNT(*) as tx_count,
                           ARRAY_AGG(DISTINCT from_contract_address) as unique_from,
                           SUM(value) as total_in
                    FROM {table_name}
                    WHERE LOWER(to_contract_address) = :addr
                """)
                in_result = session.execute(in_query, {'addr': address.lower()}).fetchone()
                
                total_out_count += out_result[0] or 0
                total_in_count += in_result[0] or 0
                
                if out_result[1]:
                    total_unique_to.update([a for a in out_result[1] if a])
                if in_result[1]:
                    total_unique_from.update([a for a in in_result[1] if a])
                    
                if out_result[2]:
                    total_values.append(float(out_result[2]))
                if out_result[3]:
                    total_values.append(float(out_result[3]))
                    
                total_out_volume += float(out_result[4] or 0)
                total_in_volume += float(in_result[2] or 0)
                
            except Exception as e:
                logger.debug(f"Feature extraction from {table_name} failed: {e}")
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
    
    def train_model(
        self, 
        X: pd.DataFrame, 
        y: pd.Series,
        model_type: str = 'xgboost',
        run_name: str = None
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
            base_model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=6,
                learning_rate=0.1,
                objective='multi:softprob',
                num_class=len(LABEL_ENCODING),
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
        
        # Create pipeline
        if HAS_IMBLEARN:
            pipeline = ImbPipeline([
                ('scaler', StandardScaler()),
                ('smote', SMOTE(random_state=42, k_neighbors=min(5, len(y) - 1))),
                ('classifier', base_model)
            ])
        else:
            pipeline = Pipeline([
                ('scaler', StandardScaler()),
                ('classifier', base_model)
            ])
        
        # Cross-validation
        cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
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
                
                # Log model
                mlflow.sklearn.log_model(pipeline, "model")
                
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
