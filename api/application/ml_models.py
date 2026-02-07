# api/application/ml_models.py
"""
ML & Audit models — wallet scores, audit trail, model metadata.
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, Text, TIMESTAMP, ForeignKey, UniqueConstraint, Index, JSON
from datetime import datetime

from api.application.base import Base


class WalletScore(Base):
    """ML-generated wallet classification scores"""
    __tablename__ = 'wallet_score'

    id = Column(Integer, primary_key=True)
    address = Column(String(42), nullable=False)
    chain_id = Column(Integer, nullable=False, default=1)

    # Classification scores (0-1 probability for each type)
    score_exchange = Column(Float, default=0.0)
    score_bridge = Column(Float, default=0.0)
    score_mixer = Column(Float, default=0.0)
    score_defi = Column(Float, default=0.0)
    score_whale = Column(Float, default=0.0)
    score_bot = Column(Float, default=0.0)

    # Best prediction
    predicted_type = Column(String(30))
    confidence = Column(Float)

    # Clustering info
    cluster_id = Column(Integer)
    is_anomaly = Column(Boolean, default=False)
    anomaly_score = Column(Float)

    # Feature values (for explainability)
    feature_tx_count = Column(Integer)
    feature_unique_counterparties = Column(Integer)
    feature_avg_tx_value = Column(Float)
    feature_max_tx_value = Column(Float)
    feature_in_out_ratio = Column(Float)
    feature_active_days = Column(Integer)

    # Metadata
    model_version = Column(String(50))
    scored_at = Column(TIMESTAMP, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('address', 'chain_id', name='wallet_score_unique'),
        Index('ix_wallet_score_address', 'address'),
        Index('ix_wallet_score_predicted_type', 'predicted_type'),
        Index('ix_wallet_score_chain_id', 'chain_id'),
    )


class AuditLog(Base):
    """
    Audit trail for all system actions.
    Required for AI regulation compliance (EU AI Act, etc.)
    """
    __tablename__ = 'audit_log'

    id = Column(Integer, primary_key=True)
    timestamp = Column(TIMESTAMP, default=datetime.utcnow)

    # Action metadata
    action_type = Column(String(50), nullable=False)
    action_subtype = Column(String(50))

    # Actor information
    user_id = Column(String(100))
    user_role = Column(String(50))
    ip_address = Column(String(45))

    # Target information
    wallet_address = Column(String(42))
    chain_id = Column(Integer)
    investigation_id = Column(Integer, ForeignKey('investigation.id'), nullable=True)

    # Classification result
    predicted_type = Column(String(50))
    confidence = Column(Float)

    # Model information
    model_version = Column(String(50))
    mlflow_run_id = Column(String(100))

    # SHAP explanation
    shap_values = Column(JSON)

    # Validation status
    validation_status = Column(String(20), default='pending')
    validated_by = Column(String(100))
    validated_at = Column(TIMESTAMP)

    # Notes
    notes = Column(Text)
    created_at = Column(TIMESTAMP, default=datetime.utcnow)

    __table_args__ = (
        Index('ix_audit_log_action_type', 'action_type'),
        Index('ix_audit_log_timestamp', 'timestamp'),
        Index('ix_audit_log_investigation', 'investigation_id'),
        Index('ix_audit_log_wallet', 'wallet_address'),
    )


class ModelMetadata(Base):
    """
    Model metadata and configuration for production models.
    Tracks model lifecycle and governance.
    """
    __tablename__ = 'model_metadata'

    id = Column(Integer, primary_key=True)

    # Model identification
    model_name = Column(String(100), nullable=False)
    version = Column(String(50), nullable=False)
    model_type = Column(String(50))
    mlflow_run_id = Column(String(100))

    # Status
    is_production = Column(Boolean, default=False)
    is_validated = Column(Boolean, default=False)

    # Performance metrics
    accuracy = Column(Float)
    f1_score = Column(Float)
    precision = Column(Float)
    recall = Column(Float)
    roc_auc = Column(Float)

    # Training info
    n_samples = Column(Integer)
    n_features = Column(Integer)
    feature_names = Column(JSON)
    hyperparameters = Column(JSON)

    # SHAP feature importance
    shap_importance = Column(JSON)

    # Decision threshold
    threshold = Column(Float, default=0.5)

    # Governance
    approved_by = Column(String(100))
    approved_at = Column(TIMESTAMP)
    review_notes = Column(Text)

    # Drift monitoring
    last_drift_check = Column(TIMESTAMP)
    drift_detected = Column(Boolean, default=False)
    drift_score = Column(Float)

    # Timestamps
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    updated_at = Column(TIMESTAMP, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('model_name', 'version', name='model_metadata_unique'),
        Index('ix_model_metadata_production', 'model_name', 'is_production'),
    )
