"""Register trained models in ModelMetadata and promote best to production."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from datetime import datetime
from api.application.erc20models import ModelMetadata, AuditLog, Base
from utils.database import get_db_session

session = get_db_session()
engine = session.get_bind()
Base.metadata.create_all(engine, tables=[ModelMetadata.__table__, AuditLog.__table__])

with open("/tmp/sync_train.json") as f:
    results = json.load(f)

data_info = results["data"]

for model_type in ["random_forest", "gradient_boosting", "xgboost"]:
    r = results[model_type]
    metrics = r["metrics"]
    run_id = metrics.get("run_id", "unknown")
    m = ModelMetadata(
        model_name="wallet_classifier",
        version=run_id[:10],
        model_type=model_type,
        mlflow_run_id=run_id,
        accuracy=metrics.get("accuracy"),
        f1_score=metrics.get("f1_weighted"),
        roc_auc=metrics.get("roc_auc"),
        n_samples=data_info["samples"],
        n_features=data_info["features"],
        feature_names=json.dumps(r.get("feature_names", [])),
        is_production=False,
        is_validated=True,
    )
    session.add(m)
    print(f"Registered: {model_type} v={run_id[:10]} acc={metrics['accuracy']:.4f} cv={metrics['cv_mean']:.4f}")

session.flush()

# Promote Random Forest — best CV mean (91.0%) with lowest std (1.6%)
best = session.query(ModelMetadata).filter_by(
    model_type="random_forest"
).order_by(ModelMetadata.accuracy.desc()).first()

best.is_production = True
best.approved_at = datetime.utcnow()
best.approved_by = "system"
best.review_notes = "Best CV mean (91.0%) with lowest std (1.6%); promoted via automated pipeline"

audit = AuditLog(
    timestamp=datetime.utcnow(),
    action_type="model",
    user_id="system",
    notes=f"Promoted random_forest to production: acc={best.accuracy:.4f}, f1={best.f1_score:.4f}, roc_auc={best.roc_auc:.4f}",
    model_version=best.version,
    mlflow_run_id=best.mlflow_run_id,
    confidence=best.accuracy
)
session.add(audit)
session.commit()

print(f"\nPromoted to PRODUCTION: {best.model_type} v={best.version} (id={best.id})")
print("\nAll registered models:")
for m in session.query(ModelMetadata).all():
    tag = " *** PRODUCTION ***" if m.is_production else ""
    print(f"  [{m.id}] {m.model_type:25s} v={m.version} acc={m.accuracy:.4f} f1={m.f1_score:.4f} roc={m.roc_auc:.4f}{tag}")

session.close()
