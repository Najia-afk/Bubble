"""ML training, model management, drift detection, and SHAP endpoints."""

from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

ml_bp = Blueprint('ml', __name__)


@ml_bp.route("/ml/stats", methods=['GET'])
def get_ml_stats():
    """Get ML model statistics."""
    from api.application.erc20models import ModelMetadata, AuditLog

    try:
        session = g.db_session

        total_models = session.query(ModelMetadata).count()
        production_models = session.query(ModelMetadata).filter_by(is_production=True).count()

        latest = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).limit(5).all()
        avg_accuracy = sum(m.accuracy or 0 for m in latest) / len(latest) if latest else 0

        last = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).first()
        last_trained = last.created_at.strftime('%Y-%m-%d') if last else 'Never'

        drift_status = 'OK'
        if last and last.drift_detected:
            drift_status = 'DRIFT'

        return jsonify({
            "total_models": total_models,
            "production_models": production_models,
            "avg_accuracy": avg_accuracy,
            "last_trained": last_trained,
            "drift_status": drift_status
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ml_bp.route("/ml/models", methods=['GET'])
def get_ml_models():
    """Get list of registered models."""
    from api.application.erc20models import ModelMetadata

    try:
        session = g.db_session
        models = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).all()

        return jsonify([
            {
                "id": m.id, "name": m.model_name, "version": m.version,
                "stage": 'Production' if m.is_production else 'Staging' if m.is_validated else 'None',
                "accuracy": m.accuracy, "f1_score": m.f1_score,
                "created": m.created_at.isoformat() if m.created_at else None,
                "run_id": m.mlflow_run_id
            }
            for m in models
        ]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ml_bp.route("/ml/train", methods=['POST'])
def train_ml_model():
    """Train a new ML model."""
    from api.tasks.ml_tasks import train_wallet_classifier

    data = request.get_json() or {}

    task = train_wallet_classifier.delay(
        model_type=data.get('model_type', 'xgboost'),
        chain=data.get('chain'),
        token=data.get('token'),
        test_size=data.get('test_size', 0.2),
        use_smote=data.get('use_smote', True)
    )

    return jsonify({"message": "Training task submitted", "task_id": task.id}), 202


@ml_bp.route("/ml/check-drift", methods=['POST'])
def check_model_drift():
    """Check for data drift."""
    from api.tasks.ml_tasks import check_model_drift as drift_task

    task = drift_task.delay()
    return jsonify({"message": "Drift check submitted", "task_id": task.id}), 202


@ml_bp.route("/ml/drift", methods=['GET'])
def get_drift_status():
    """Get latest drift detection results."""
    from api.application.erc20models import ModelMetadata

    try:
        session = g.db_session
        prod = session.query(ModelMetadata).filter_by(is_production=True).first()

        if not prod:
            return jsonify({"error": "No production model found"}), 404

        return jsonify({
            "drift_detected": prod.drift_detected or False,
            "drift_score": prod.drift_score or 0.0,
            "last_checked": prod.last_drift_check.isoformat() if prod.last_drift_check else None,
            "model_name": prod.model_name,
            "version": prod.version
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ml_bp.route("/ml/promote", methods=['POST'])
def promote_ml_model():
    """Promote a model to a new stage."""
    from api.tasks.ml_tasks import promote_model_to_production

    data = request.get_json()
    model_name = data.get('model_name')
    version = data.get('version')
    stage = data.get('stage', 'Production')

    if not model_name or not version:
        return jsonify({"error": "model_name and version required"}), 400

    task = promote_model_to_production.delay(model_name, version, stage)
    return jsonify({"message": "Promotion task submitted", "task_id": task.id}), 202


@ml_bp.route("/ml/experiments", methods=['GET'])
def get_ml_experiments():
    """Get list of MLflow experiments/runs."""
    from api.application.erc20models import ModelMetadata

    try:
        session = g.db_session
        runs = session.query(ModelMetadata).order_by(ModelMetadata.created_at.desc()).limit(20).all()

        return jsonify([
            {
                "run_id": r.mlflow_run_id, "run_name": r.model_name,
                "model_type": r.model_type, "accuracy": r.accuracy,
                "f1_score": r.f1_score, "precision": r.precision,
                "recall": r.recall, "n_samples": r.n_samples,
                "start_time": r.created_at.isoformat() if r.created_at else None
            }
            for r in runs
        ]), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ml_bp.route("/ml/feature-importance", methods=['GET'])
def get_feature_importance():
    """Get SHAP feature importance from production model."""
    from api.application.erc20models import ModelMetadata
    import json

    try:
        session = g.db_session
        prod = session.query(ModelMetadata).filter_by(is_production=True).first()

        if not prod or not prod.shap_importance:
            return jsonify({"error": "No production model with SHAP importance"}), 404

        importance = json.loads(prod.shap_importance) if isinstance(prod.shap_importance, str) else prod.shap_importance

        return jsonify({
            "model_name": prod.model_name,
            "version": prod.version,
            "importance": importance
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
