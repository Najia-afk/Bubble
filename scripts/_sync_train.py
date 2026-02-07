"""
Run ML training synchronously inside the container.
Bypasses celery to get direct results. Uses GraphQL batch query for features.
"""
import sys, json, traceback
sys.stdout.reconfigure(line_buffering=True)  # Unbuffered output
sys.path.insert(0, '/app')

from config.settings import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from api.services.ml_trainer import WalletMLTrainer

engine = create_engine(Config.SQLALCHEMY_DATABASE_URI)
SessionFactory = sessionmaker(bind=engine)

results = {}

# Step 1: Prepare training data (via GraphQL batch)
print("=== PREPARING TRAINING DATA (via GraphQL) ===")
session = SessionFactory()
trainer = WalletMLTrainer()

try:
    X, y = trainer.prepare_training_data(session)
    print(f"X shape: {X.shape}")
    print(f"y distribution: {dict(y.value_counts().sort_index())}")
    print(f"Features: {list(X.columns)}")
    print(f"Classes: {trainer.label_classes}")
    print(f"X dtypes:\n{X.dtypes}")
    print(f"X describe:\n{X.describe()}")
    results['data'] = {
        'samples': int(X.shape[0]),
        'features': int(X.shape[1]),
        'classes': len(set(y)),
        'y_dist': {str(k): int(v) for k, v in y.value_counts().sort_index().items()}
    }
except Exception as e:
    print(f"Data prep FAILED: {e}")
    traceback.print_exc()
    results['data_error'] = str(e)[:500]
    with open('/tmp/sync_train.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)
    sys.exit(1)
finally:
    session.close()

# Step 2: Train each model type
for model_type in ['random_forest', 'gradient_boosting', 'xgboost']:
    print(f"\n=== TRAINING {model_type.upper()} ===")
    try:
        result = trainer.train_model(
            X, y,
            model_type=model_type,
            test_size=0.2,
            use_smote=True
        )
        print(f"  Status: {result.get('status')}")
        metrics = result.get('metrics', {})
        for k, v in metrics.items():
            print(f"  {k}: {v}")
        results[model_type] = result
        print(f"  === {model_type.upper()} DONE ===")
    except Exception as e:
        print(f"  FAILED: {e}")
        traceback.print_exc()
        results[model_type] = {'status': 'error', 'message': str(e)[:500]}

# Save results
with open('/tmp/sync_train.json', 'w') as f:
    json.dump(results, f, indent=2, default=str)

print("\n=== ALL TRAINING COMPLETE ===")
print(f"Results saved to /tmp/sync_train.json")

# Summary
for mt in ['random_forest', 'gradient_boosting', 'xgboost']:
    r = results.get(mt, {})
    m = r.get('metrics', {})
    status = r.get('status', 'missing')
    acc = m.get('accuracy', 'N/A')
    f1 = m.get('f1_weighted', 'N/A')
    cv = m.get('cv_mean', 'N/A')
    print(f"  {mt}: status={status}, accuracy={acc}, f1={f1}, cv_mean={cv}")

print(f"\n=== DONE ===")
print(f"Results saved to /tmp/sync_train.json")
