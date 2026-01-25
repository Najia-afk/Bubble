"""
ML Training Celery Tasks
Tasks for training, evaluation, and drift detection.
"""
import logging
from datetime import datetime
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name='train_wallet_classifier')
def train_wallet_classifier(model_type: str = 'xgboost', run_name: str = None,
                           chain: str = None, token: str = None,
                           test_size: float = 0.2, use_smote: bool = True):
    """
    Train wallet classification model using validated labels.
    
    Args:
        model_type: 'xgboost', 'random_forest', or 'gradient_boosting'
        run_name: Optional MLflow run name
        chain: Filter training data by chain
        token: Filter training data by token
        test_size: Fraction for test split
        use_smote: Whether to use SMOTE for class balancing
    """
    from api.application import get_session_factory
    from api.services.ml_trainer import get_ml_trainer
    from api.application.erc20models import ModelMetadata, AuditLog, Base
    import json
    
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        # Ensure tables exist
        Base.metadata.create_all(session.get_bind(), tables=[
            ModelMetadata.__table__,
            AuditLog.__table__
        ])
        
        trainer = get_ml_trainer()
        
        # Prepare training data
        X, y = trainer.prepare_training_data(session, chain=chain, token=token)
        
        # Train model
        result = trainer.train_model(
            X, y, 
            model_type=model_type, 
            run_name=run_name,
            test_size=test_size,
            use_smote=use_smote
        )
        
        # Save model metadata to database
        if result.get('status') == 'success':
            metadata = ModelMetadata(
                model_name='wallet_classifier',
                version=result.get('run_id', 'unknown')[:10],
                model_type=model_type,
                mlflow_run_id=result.get('run_id'),
                accuracy=result.get('accuracy'),
                f1_score=result.get('f1'),
                n_samples=result.get('n_samples'),
                shap_importance=json.dumps(result.get('shap_importance', {})),
                is_production=False,
                is_validated=False
            )
            session.add(metadata)
            
            # Log to audit
            audit = AuditLog(
                timestamp=datetime.utcnow(),
                action_type='model',
                user_id='system',
                notes=f'Trained {model_type} model with {result.get("n_samples")} samples',
                model_version=result.get('run_id', 'unknown')[:10],
                mlflow_run_id=result.get('run_id'),
                confidence=result.get('accuracy')
            )
            session.add(audit)
            session.commit()
        
        logger.info(f"Training completed: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Training failed: {e}")
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


@shared_task(name='check_model_drift')
def check_model_drift():
    """
    Check for data drift between training and recent predictions.
    Compares feature distributions.
    """
    from api.application import get_session_factory
    from api.application.erc20models import WalletScore, ModelMetadata, AuditLog
    from api.services.ml_trainer import get_ml_trainer
    import pandas as pd
    
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        trainer = get_ml_trainer()
        
        # Get training data (reference)
        X_train, _ = trainer.prepare_training_data(session)
        
        # Get recent predictions (current)
        recent_scores = session.query(WalletScore).filter(
            WalletScore.feature_tx_count.isnot(None)
        ).order_by(WalletScore.scored_at.desc()).limit(500).all()
        
        if len(recent_scores) < 50:
            return {
                'status': 'skipped',
                'message': f'Insufficient recent predictions: {len(recent_scores)}'
            }
        
        # Build current data DataFrame
        current_features = []
        for score in recent_scores:
            current_features.append({
                'tx_count': score.feature_tx_count or 0,
                'unique_counterparties': score.feature_unique_counterparties or 0,
                'avg_tx_value': score.feature_avg_tx_value or 0,
                'max_tx_value': score.feature_max_tx_value or 0,
                'in_out_ratio': score.feature_in_out_ratio or 1.0,
            })
        
        X_current = pd.DataFrame(current_features)
        
        # Check drift
        drift_result = trainer.check_data_drift(X_train, X_current)
        
        # Update production model with drift status
        prod_model = session.query(ModelMetadata).filter_by(is_production=True).first()
        if prod_model:
            prod_model.drift_detected = drift_result.get('drift_detected', False)
            prod_model.drift_score = drift_result.get('drift_score', 0.0)
            prod_model.last_drift_check = datetime.utcnow()
            
            # Log to audit if drift detected
            if drift_result.get('drift_detected'):
                audit = AuditLog(
                    timestamp=datetime.utcnow(),
                    action_type='alert',
                    user_id='system',
                    notes=f'Data drift detected! Score: {drift_result.get("drift_score")}',
                    model_version=prod_model.version,
                    confidence=drift_result.get('drift_score')
                )
                session.add(audit)
            
            session.commit()
        
        logger.info(f"Drift check completed: {drift_result}")
        return drift_result
        
    except Exception as e:
        logger.error(f"Drift check failed: {e}")
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


@shared_task(name='classify_wallet_with_shap')
def classify_wallet_with_shap(address: str, chain_trigram: str = 'ETH', 
                              investigation_id: int = None, user_id: str = None):
    """
    Classify a wallet and generate SHAP explanation.
    
    Args:
        address: Wallet address
        chain_trigram: Chain identifier
        investigation_id: Optional investigation context
        user_id: Optional user ID for audit
        
    Returns:
        Classification with SHAP explanation
    """
    from api.application import get_session_factory
    from api.application.erc20models import AuditLog, TRIGRAM_TO_CHAIN_ID
    from api.services.wallet_classifier import get_wallet_classifier
    from api.services.ml_trainer import get_ml_trainer
    import json
    
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        # First, get classification (this extracts features)
        classifier = get_wallet_classifier()
        classification = classifier.classify(address, chain_trigram, save_result=True)
        
        # If we have features, generate SHAP explanation
        if classification.get('features') and classification.get('source') == 'ml_classification':
            trainer = get_ml_trainer()
            
            # Load production model if not already loaded
            if trainer.model is None:
                trainer.load_production_model()
            
            if trainer.model is not None:
                explanation = trainer.explain_prediction(
                    classification['features'],
                    address=address
                )
                classification['shap_explanation'] = explanation
        
        # Log to audit
        audit = AuditLog(
            timestamp=datetime.utcnow(),
            action_type='classification',
            user_id=user_id or 'system',
            wallet_address=address.lower(),
            chain_id=TRIGRAM_TO_CHAIN_ID.get(chain_trigram.upper(), 1),
            investigation_id=investigation_id,
            predicted_type=classification.get('predicted_type'),
            confidence=classification.get('confidence'),
            model_version=classification.get('model_version'),
            shap_values=json.dumps(classification.get('shap_explanation', {}).get('shap_values', {})) if classification.get('shap_explanation') else None,
            validation_status='pending'
        )
        session.add(audit)
        session.commit()
        
        return classification
        
    except Exception as e:
        logger.error(f"SHAP classification failed: {e}")
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()


@shared_task(name='batch_classify_with_shap')
def batch_classify_with_shap(addresses: list, chain_trigram: str = 'ETH'):
    """
    Batch classify wallets with SHAP explanations.
    
    Args:
        addresses: List of wallet addresses
        chain_trigram: Chain identifier
        
    Returns:
        List of classifications with SHAP
    """
    results = []
    for address in addresses:
        result = classify_wallet_with_shap(address, chain_trigram)
        results.append(result)
    return results


@shared_task(name='register_best_model')
def register_best_model(model_name: str = 'wallet_classifier'):
    """
    Register the best performing model from recent runs.
    """
    from api.services.ml_trainer import get_ml_trainer
    import mlflow
    
    try:
        trainer = get_ml_trainer()
        
        if trainer.client is None:
            return {'status': 'error', 'message': 'MLflow not available'}
        
        # Get experiment
        experiment = trainer.client.get_experiment_by_name(trainer.experiment_name)
        if not experiment:
            return {'status': 'error', 'message': 'Experiment not found'}
        
        # Find best run by f1_weighted
        runs = trainer.client.search_runs(
            experiment_ids=[experiment.experiment_id],
            order_by=["metrics.f1_weighted DESC"],
            max_results=1
        )
        
        if not runs:
            return {'status': 'error', 'message': 'No runs found'}
        
        best_run = runs[0]
        
        # Register model
        result = trainer.register_model(best_run.info.run_id, model_name)
        
        logger.info(f"Best model registered: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Model registration failed: {e}")
        return {'status': 'error', 'message': str(e)}


@shared_task(name='promote_model_to_production')
def promote_model_to_production(model_name: str, version: str, stage: str = 'Production'):
    """
    Promote a model version to Production stage.
    
    Args:
        model_name: Registered model name
        version: Version to promote (string)
        stage: Target stage (Staging or Production)
    """
    from api.application import get_session_factory
    from api.application.erc20models import ModelMetadata, AuditLog
    from api.services.ml_trainer import get_ml_trainer
    
    SessionFactory = get_session_factory()
    session = SessionFactory()
    
    try:
        trainer = get_ml_trainer()
        
        # Try to convert version to int for MLflow
        try:
            version_int = int(version)
        except ValueError:
            version_int = 1
        
        result = trainer.promote_model(model_name, version_int, stage=stage)
        
        # Update database
        if stage.lower() == 'production':
            # Demote other models
            session.query(ModelMetadata).filter_by(is_production=True).update({'is_production': False})
            
            # Promote this one
            model = session.query(ModelMetadata).filter_by(
                model_name=model_name, 
                version=version
            ).first()
            
            if model:
                model.is_production = True
                model.approved_at = datetime.utcnow()
                
                # Audit log
                audit = AuditLog(
                    timestamp=datetime.utcnow(),
                    action_type='model',
                    user_id='system',
                    notes=f'Promoted {model_name} v{version} to {stage}',
                    model_version=version
                )
                session.add(audit)
                session.commit()
        
        logger.info(f"Model promoted: {result}")
        return result
        
    except Exception as e:
        logger.error(f"Promotion failed: {e}")
        session.rollback()
        return {'status': 'error', 'message': str(e)}
    finally:
        session.close()
