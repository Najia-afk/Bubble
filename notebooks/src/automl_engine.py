"""
AutoML Engine for Bubble Platform
Automated model selection, training, evaluation, and promotion pipeline.
Supports: RandomForest, GradientBoosting, XGBoost, LightGBM, ExtraTrees, SVM, LogisticRegression
Uses Optuna for hyperparameter tuning, MLflow for tracking, SHAP for explainability.
"""
import os
import sys
import json
import time
import hashlib
import warnings
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any

import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')
logger = logging.getLogger('bubble.automl')

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ─── Model Registry ──────────────────────────────────────────────────────────

CANDIDATE_MODELS = {
    'random_forest': {
        'class': 'sklearn.ensemble.RandomForestClassifier',
        'param_space': {
            'n_estimators': ('int', 50, 500),
            'max_depth': ('int', 3, 20),
            'min_samples_split': ('int', 2, 20),
            'min_samples_leaf': ('int', 1, 10),
            'max_features': ('categorical', ['sqrt', 'log2', None]),
        },
        'default_params': {'n_estimators': 200, 'max_depth': 10, 'random_state': 42, 'n_jobs': -1},
    },
    'gradient_boosting': {
        'class': 'sklearn.ensemble.GradientBoostingClassifier',
        'param_space': {
            'n_estimators': ('int', 50, 400),
            'max_depth': ('int', 3, 12),
            'learning_rate': ('float_log', 0.01, 0.3),
            'subsample': ('float', 0.6, 1.0),
            'min_samples_split': ('int', 2, 20),
        },
        'default_params': {'n_estimators': 200, 'max_depth': 5, 'learning_rate': 0.1, 'random_state': 42},
    },
    'extra_trees': {
        'class': 'sklearn.ensemble.ExtraTreesClassifier',
        'param_space': {
            'n_estimators': ('int', 50, 500),
            'max_depth': ('int', 3, 20),
            'min_samples_split': ('int', 2, 20),
            'min_samples_leaf': ('int', 1, 10),
        },
        'default_params': {'n_estimators': 200, 'max_depth': 10, 'random_state': 42, 'n_jobs': -1},
    },
    'logistic_regression': {
        'class': 'sklearn.linear_model.LogisticRegression',
        'param_space': {
            'C': ('float_log', 0.001, 100.0),
            'penalty': ('categorical', ['l1', 'l2']),
            'solver': ('categorical', ['liblinear', 'saga']),
            'max_iter': ('int', 100, 1000),
        },
        'default_params': {'C': 1.0, 'max_iter': 500, 'random_state': 42},
    },
    'svm': {
        'class': 'sklearn.svm.SVC',
        'param_space': {
            'C': ('float_log', 0.01, 100.0),
            'kernel': ('categorical', ['rbf', 'poly', 'sigmoid']),
            'gamma': ('categorical', ['scale', 'auto']),
        },
        'default_params': {'C': 1.0, 'kernel': 'rbf', 'probability': True, 'random_state': 42},
    },
}

# Optional models (require pip install)
OPTIONAL_MODELS = {
    'xgboost': {
        'class': 'xgboost.XGBClassifier',
        'import_check': 'xgboost',
        'param_space': {
            'n_estimators': ('int', 50, 500),
            'max_depth': ('int', 3, 15),
            'learning_rate': ('float_log', 0.01, 0.3),
            'subsample': ('float', 0.6, 1.0),
            'colsample_bytree': ('float', 0.5, 1.0),
            'reg_alpha': ('float_log', 1e-3, 10.0),
            'reg_lambda': ('float_log', 1e-3, 10.0),
        },
        'default_params': {'n_estimators': 200, 'max_depth': 6, 'learning_rate': 0.1,
                           'use_label_encoder': False, 'eval_metric': 'mlogloss', 'random_state': 42, 'n_jobs': -1},
    },
    'lightgbm': {
        'class': 'lightgbm.LGBMClassifier',
        'import_check': 'lightgbm',
        'param_space': {
            'n_estimators': ('int', 50, 500),
            'max_depth': ('int', 3, 15),
            'learning_rate': ('float_log', 0.01, 0.3),
            'subsample': ('float', 0.6, 1.0),
            'colsample_bytree': ('float', 0.5, 1.0),
            'num_leaves': ('int', 15, 127),
            'reg_alpha': ('float_log', 1e-3, 10.0),
            'reg_lambda': ('float_log', 1e-3, 10.0),
        },
        'default_params': {'n_estimators': 200, 'max_depth': 6, 'learning_rate': 0.1,
                           'verbose': -1, 'random_state': 42, 'n_jobs': -1},
    },
}


def _check_optional_package(pkg_name: str) -> bool:
    """Check if an optional ML package is available."""
    try:
        __import__(pkg_name)
        return True
    except ImportError:
        return False


def get_available_models() -> Dict[str, dict]:
    """Return all available model configurations (base + optional if installed)."""
    models = dict(CANDIDATE_MODELS)
    for name, config in OPTIONAL_MODELS.items():
        if _check_optional_package(config['import_check']):
            models[name] = config
    return models


def _import_model_class(class_path: str):
    """Dynamically import a model class from its dotted path."""
    parts = class_path.rsplit('.', 1)
    module = __import__(parts[0], fromlist=[parts[1]])
    return getattr(module, parts[1])


# ─── Data Preparation ────────────────────────────────────────────────────────

LABEL_ENCODING = {
    'unknown': 0, 'exchange': 1, 'bridge': 2, 'mixer': 3,
    'defi': 4, 'whale': 5, 'bot': 6, 'normal': 7, 'attacker': 8, 'suspect': 9
}


def prepare_training_data(loader, min_samples: int = 30) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """
    Load wallet features + labels from DB, return (X, y, feature_names).
    Falls back to synthetic data if insufficient real samples.
    """
    try:
        scores_df = loader.get_wallet_scores()
        if len(scores_df) < min_samples:
            raise ValueError(f"Only {len(scores_df)} samples, need {min_samples}")

        feature_cols = [c for c in scores_df.columns if c not in
                        ['address', 'chain_id', 'predicted_type', 'confidence',
                         'cluster_id', 'is_anomaly', 'anomaly_score', 'model_version']]
        X = scores_df[feature_cols].fillna(0)
        y = scores_df['predicted_type'].map(LABEL_ENCODING).fillna(0).astype(int)
        return X, y, feature_cols

    except Exception as e:
        logger.warning(f"Cannot load real data: {e} — using investigation wallets")
        return _prepare_from_investigations(loader)


def _prepare_from_investigations(loader) -> Tuple[pd.DataFrame, pd.Series, List[str]]:
    """Build training data from investigation wallets if WalletScore table is sparse."""
    from notebooks.src.classes.wallet_features import WalletFeatureExtractor

    all_features = []
    all_labels = []

    # Try each investigation (1-10)
    for inv_id in range(1, 11):
        try:
            wallets_df = loader.get_wallets(inv_id)
            transfers_df = loader.get_transfers(inv_id)
            if wallets_df.empty or transfers_df.empty:
                continue

            extractor = WalletFeatureExtractor(transfers_df)
            for _, w in wallets_df.iterrows():
                addr = w.get('address', '')
                role = w.get('role', w.get('wallet_type', 'unknown'))
                if not addr:
                    continue
                feats = extractor.extract_features_for_wallet(addr)
                if feats.get('tx_count', 0) >= 2:
                    all_features.append(feats)
                    all_labels.append(LABEL_ENCODING.get(str(role).lower(), 0))
        except Exception:
            continue

    if len(all_features) < 10:
        raise ValueError(f"Insufficient data: {len(all_features)} wallets across all investigations")

    X = pd.DataFrame(all_features).fillna(0)
    y = pd.Series(all_labels)
    feature_cols = [c for c in X.columns if c != 'address']
    X = X[feature_cols]
    return X, y, feature_cols


# ─── Optuna Hyperparameter Tuning ────────────────────────────────────────────

def _suggest_params(trial, param_space: dict) -> dict:
    """Generate hyperparameters from Optuna trial based on param_space definition."""
    params = {}
    for name, spec in param_space.items():
        ptype = spec[0]
        if ptype == 'int':
            params[name] = trial.suggest_int(name, spec[1], spec[2])
        elif ptype == 'float':
            params[name] = trial.suggest_float(name, spec[1], spec[2])
        elif ptype == 'float_log':
            params[name] = trial.suggest_float(name, spec[1], spec[2], log=True)
        elif ptype == 'categorical':
            params[name] = trial.suggest_categorical(name, spec[1])
    return params


def tune_model(model_name: str, model_config: dict, X: pd.DataFrame, y: pd.Series,
               n_trials: int = 20, cv_folds: int = 5, scoring: str = 'f1_weighted',
               timeout: int = 300) -> Tuple[dict, float]:
    """
    Run Optuna hyperparameter search for a single model.
    Returns (best_params, best_score).
    Resource-conscious: limited trials + timeout.
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.info(f"Optuna not available — using default params for {model_name}")
        return model_config['default_params'], 0.0

    from sklearn.model_selection import cross_val_score, StratifiedKFold

    ModelClass = _import_model_class(model_config['class'])
    skf = StratifiedKFold(n_splits=min(cv_folds, min(y.value_counts())), shuffle=True, random_state=42)

    def objective(trial):
        params = _suggest_params(trial, model_config['param_space'])
        # Merge with non-tunable defaults
        full_params = {**model_config['default_params'], **params}
        # Remove conflicting params
        if model_name == 'svm':
            full_params['probability'] = True
        try:
            model = ModelClass(**full_params)
            scores = cross_val_score(model, X, y, cv=skf, scoring=scoring, n_jobs=1)
            return scores.mean()
        except Exception as e:
            logger.debug(f"Trial failed: {e}")
            return 0.0

    study = optuna.create_study(direction='maximize', study_name=f'bubble_{model_name}')
    study.optimize(objective, n_trials=n_trials, timeout=timeout, show_progress_bar=False)

    best_params = {**model_config['default_params'], **study.best_params}
    return best_params, study.best_value


# ─── Model Evaluation ────────────────────────────────────────────────────────

def evaluate_model(model, X_test: pd.DataFrame, y_test: pd.Series, label_names: List[str] = None) -> dict:
    """Comprehensive model evaluation with multiple metrics."""
    from sklearn.metrics import (accuracy_score, f1_score, precision_score, recall_score,
                                 classification_report, confusion_matrix)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test) if hasattr(model, 'predict_proba') else None

    metrics = {
        'accuracy': accuracy_score(y_test, y_pred),
        'f1_weighted': f1_score(y_test, y_pred, average='weighted', zero_division=0),
        'f1_macro': f1_score(y_test, y_pred, average='macro', zero_division=0),
        'precision_weighted': precision_score(y_test, y_pred, average='weighted', zero_division=0),
        'recall_weighted': recall_score(y_test, y_pred, average='weighted', zero_division=0),
        'classification_report': classification_report(y_test, y_pred, output_dict=True, zero_division=0),
        'confusion_matrix': confusion_matrix(y_test, y_pred).tolist(),
        'n_test_samples': len(y_test),
        'n_classes': len(set(y_test)),
    }

    # SHAP if available
    try:
        import shap
        if hasattr(model, 'feature_importances_'):
            explainer = shap.TreeExplainer(model)
            shap_values = explainer.shap_values(X_test[:min(100, len(X_test))])
            if isinstance(shap_values, list):
                metrics['shap_mean_abs'] = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0).tolist()
            else:
                metrics['shap_mean_abs'] = np.abs(shap_values).mean(axis=0).tolist()
    except Exception:
        pass

    # Feature importance
    if hasattr(model, 'feature_importances_'):
        metrics['feature_importances'] = model.feature_importances_.tolist()
    elif hasattr(model, 'coef_'):
        metrics['feature_importances'] = np.abs(model.coef_).mean(axis=0).tolist()

    return metrics


# ─── Full AutoML Pipeline ────────────────────────────────────────────────────

class BubbleAutoML:
    """
    End-to-end AutoML engine for wallet classification.

    Usage:
        automl = BubbleAutoML(loader)
        results = automl.run(n_trials=20, timeout_per_model=120)
        automl.promote_best()
        automl.save_report('reports/ml/automl_report.md')
    """

    def __init__(self, loader=None, mlflow_uri: str = None):
        self.loader = loader
        self.mlflow_uri = mlflow_uri or os.environ.get('MLFLOW_TRACKING_URI', 'http://localhost:5005')
        self.results: Dict[str, dict] = {}
        self.best_model_name: str = None
        self.best_model = None
        self.best_params: dict = None
        self.X_train = None
        self.X_test = None
        self.y_train = None
        self.y_test = None
        self.feature_names: List[str] = []
        self.run_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    def run(self, n_trials: int = 20, timeout_per_model: int = 120, cv_folds: int = 5,
            test_size: float = 0.2, use_smote: bool = True,
            models_to_try: List[str] = None) -> Dict[str, dict]:
        """
        Execute full AutoML pipeline:
        1. Load & prepare data
        2. Split train/test
        3. Optional SMOTE balancing
        4. Tune each candidate model with Optuna
        5. Train best params on full train set
        6. Evaluate on held-out test set
        7. Return ranked results
        """
        print("=" * 60)
        print(f"🚀 Bubble AutoML Pipeline — {self.run_timestamp}")
        print("=" * 60)

        # 1. Load data
        print("\n[INFO] Step 1: Loading training data...")
        X, y, self.feature_names = prepare_training_data(self.loader)
        print(f"   Samples: {len(X)}, Features: {len(self.feature_names)}, Classes: {y.nunique()}")
        class_dist = y.value_counts().to_dict()
        inv_encoding = {v: k for k, v in LABEL_ENCODING.items()}
        print(f"   Distribution: {', '.join(f'{inv_encoding.get(k, k)}: {v}' for k, v in sorted(class_dist.items()))}")

        # 2. Split
        print("\n✂️  Step 2: Train/test split...")
        from sklearn.model_selection import train_test_split
        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            X, y, test_size=test_size, stratify=y, random_state=42
        )
        print(f"   Train: {len(self.X_train)}, Test: {len(self.X_test)}")

        # 3. SMOTE
        if use_smote:
            try:
                from imblearn.over_sampling import SMOTE
                min_class_count = self.y_train.value_counts().min()
                if min_class_count >= 2:
                    k = min(5, min_class_count - 1)
                    smote = SMOTE(random_state=42, k_neighbors=k)
                    self.X_train, self.y_train = smote.fit_resample(self.X_train, self.y_train)
                    print(f"   ⚖️  SMOTE applied: {len(self.X_train)} samples (k={k})")
                else:
                    print("   [WARN]  Skipping SMOTE — min class too small")
            except ImportError:
                print("   [WARN]  imblearn not installed — skipping SMOTE")

        # 4. Scale features
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X_train_scaled = pd.DataFrame(
            scaler.fit_transform(self.X_train), columns=self.feature_names, index=self.X_train.index
        )
        X_test_scaled = pd.DataFrame(
            scaler.transform(self.X_test), columns=self.feature_names, index=self.X_test.index
        )

        # 5. Tune & evaluate models
        available_models = get_available_models()
        if models_to_try:
            available_models = {k: v for k, v in available_models.items() if k in models_to_try}

        print(f"\n🔧 Step 3: Tuning {len(available_models)} models ({n_trials} trials each, {timeout_per_model}s timeout)...")

        for i, (model_name, config) in enumerate(available_models.items(), 1):
            print(f"\n   [{i}/{len(available_models)}] {model_name}...")
            t0 = time.time()

            try:
                # Use scaled data for SVM and LogReg, raw for tree-based
                needs_scaling = model_name in ('svm', 'logistic_regression')
                X_tr = X_train_scaled if needs_scaling else self.X_train
                X_te = X_test_scaled if needs_scaling else self.X_test

                # Tune
                best_params, cv_score = tune_model(
                    model_name, config, X_tr, self.y_train,
                    n_trials=n_trials, cv_folds=cv_folds, timeout=timeout_per_model
                )

                # Train final model
                ModelClass = _import_model_class(config['class'])
                model = ModelClass(**best_params)
                model.fit(X_tr, self.y_train)

                # Evaluate
                metrics = evaluate_model(model, X_te, self.y_test)
                metrics['cv_score'] = cv_score
                metrics['tuning_time'] = time.time() - t0
                metrics['best_params'] = best_params
                metrics['model_object'] = model
                metrics['needs_scaling'] = needs_scaling

                self.results[model_name] = metrics
                gap = metrics['accuracy'] - cv_score if cv_score > 0 else 0
                print(f"      Accuracy: {metrics['accuracy']:.4f} | F1: {metrics['f1_weighted']:.4f} "
                      f"| CV: {cv_score:.4f} | Gap: {gap:+.4f} | {metrics['tuning_time']:.1f}s")

            except Exception as e:
                print(f"      [ERROR] Failed: {e}")
                self.results[model_name] = {'error': str(e)}

        # 6. Select best
        valid_results = {k: v for k, v in self.results.items() if 'error' not in v}
        if valid_results:
            self.best_model_name = max(valid_results, key=lambda k: valid_results[k]['f1_weighted'])
            self.best_model = valid_results[self.best_model_name]['model_object']
            self.best_params = valid_results[self.best_model_name]['best_params']

        # 7. Summary
        print("\n" + "=" * 60)
        print("[INFO] RESULTS LEADERBOARD")
        print("=" * 60)
        sorted_results = sorted(valid_results.items(), key=lambda x: x[1]['f1_weighted'], reverse=True)
        for rank, (name, m) in enumerate(sorted_results, 1):
            medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else "  "
            cv_gap = m['accuracy'] - m.get('cv_score', 0) if m.get('cv_score', 0) > 0 else 0
            flag = " [WARN]OVERFIT" if cv_gap > 0.1 else ""
            print(f"   {medal} #{rank} {name:<22} F1={m['f1_weighted']:.4f}  "
                  f"Acc={m['accuracy']:.4f}  CV={m.get('cv_score', 0):.4f}  "
                  f"Gap={cv_gap:+.3f}{flag}")

        if self.best_model_name:
            print(f"\n   🏆 Champion: {self.best_model_name}")

        return self.results

    def promote_best(self, experiment_name: str = 'wallet_classification') -> Optional[str]:
        """Register and promote the best model to MLflow Production."""
        if not self.best_model:
            print("[ERROR] No model to promote — run AutoML first")
            return None

        try:
            import mlflow
            import mlflow.sklearn
            mlflow.set_tracking_uri(self.mlflow_uri)
            mlflow.set_experiment(experiment_name)

            with mlflow.start_run(run_name=f"automl_{self.best_model_name}_{self.run_timestamp}"):
                metrics = self.results[self.best_model_name]
                mlflow.log_params(self.best_params)
                mlflow.log_metric('accuracy', metrics['accuracy'])
                mlflow.log_metric('f1_weighted', metrics['f1_weighted'])
                mlflow.log_metric('f1_macro', metrics['f1_macro'])
                mlflow.log_metric('precision_weighted', metrics['precision_weighted'])
                mlflow.log_metric('recall_weighted', metrics['recall_weighted'])
                mlflow.log_metric('cv_score', metrics.get('cv_score', 0))
                mlflow.log_metric('n_train_samples', len(self.X_train))
                mlflow.log_metric('n_test_samples', len(self.X_test))
                mlflow.log_metric('n_features', len(self.feature_names))
                mlflow.sklearn.log_model(self.best_model, 'model')
                run_id = mlflow.active_run().info.run_id

            print(f"[OK] Model logged to MLflow: {self.best_model_name} (run_id={run_id[:8]}...)")
            return run_id

        except Exception as e:
            print(f"[WARN]  MLflow unavailable ({e}) — saving model locally")
            return self._save_local()

    def _save_local(self) -> str:
        """Fallback: save model as pickle when MLflow is down."""
        import pickle
        model_dir = os.path.join(PROJECT_ROOT, 'models')
        os.makedirs(model_dir, exist_ok=True)
        path = os.path.join(model_dir, f"automl_{self.best_model_name}_{self.run_timestamp}.pkl")
        with open(path, 'wb') as f:
            pickle.dump({
                'model': self.best_model,
                'params': self.best_params,
                'feature_names': self.feature_names,
                'metrics': {k: v for k, v in self.results[self.best_model_name].items()
                            if k != 'model_object'},
            }, f)
        print(f"   💾 Saved to {path}")
        return path

    def save_report(self, path: str = None) -> str:
        """Generate Markdown report of AutoML run."""
        if path is None:
            path = os.path.join(PROJECT_ROOT, 'reports', 'ml', f'automl_report_{self.run_timestamp}.md')
        os.makedirs(os.path.dirname(path), exist_ok=True)

        lines = [
            f"# AutoML Report — {self.run_timestamp}",
            "",
            f"> Generated: {datetime.now().isoformat()}  ",
            f"> Champion: **{self.best_model_name}**  ",
            f"> Training samples: {len(self.X_train)}  ",
            f"> Test samples: {len(self.X_test)}  ",
            f"> Features: {len(self.feature_names)}  ",
            "",
            "---",
            "",
            "## Leaderboard",
            "",
            "| Rank | Model | F1 (weighted) | Accuracy | CV Score | Gap | Time |",
            "|------|-------|--------------|----------|----------|-----|------|",
        ]

        valid = {k: v for k, v in self.results.items() if 'error' not in v}
        sorted_r = sorted(valid.items(), key=lambda x: x[1]['f1_weighted'], reverse=True)
        for rank, (name, m) in enumerate(sorted_r, 1):
            gap = m['accuracy'] - m.get('cv_score', 0) if m.get('cv_score', 0) > 0 else 0
            flag = " [WARN]" if gap > 0.1 else ""
            lines.append(
                f"| {rank} | {name} | {m['f1_weighted']:.4f} | {m['accuracy']:.4f} "
                f"| {m.get('cv_score', 0):.4f} | {gap:+.3f}{flag} | {m.get('tuning_time', 0):.1f}s |"
            )

        # Champion details
        if self.best_model_name and self.best_model_name in valid:
            bm = valid[self.best_model_name]
            lines.extend([
                "",
                f"## Champion: {self.best_model_name}",
                "",
                "### Best Hyperparameters",
                "```json",
                json.dumps(bm.get('best_params', {}), indent=2, default=str),
                "```",
                "",
                "### Feature Importance (Top 15)",
                "",
                "| Rank | Feature | Importance |",
                "|------|---------|------------|",
            ])
            if 'feature_importances' in bm:
                fi = list(zip(self.feature_names, bm['feature_importances']))
                fi.sort(key=lambda x: abs(x[1]), reverse=True)
                for i, (fname, imp) in enumerate(fi[:15], 1):
                    lines.append(f"| {i} | {fname} | {imp:.4f} |")

        # Recommendations
        lines.extend([
            "",
            "## Recommendations",
            "",
        ])
        if len(self.X_train) < 500:
            lines.append(f"- [WARN] **Low training data** ({len(self.X_train)} samples) — target 2000+ for production")
        if valid:
            best_gap = sorted_r[0][1]['accuracy'] - sorted_r[0][1].get('cv_score', 0)
            if best_gap > 0.08:
                lines.append(f"- [WARN] **Potential overfitting** — {best_gap:.1%} gap between test and CV scores")
        if len(self.feature_names) < 20:
            lines.append(f"- 📈 **Feature expansion** — only {len(self.feature_names)} features, add temporal/network/risk features")
        lines.append("- 🔄 Retrain after adding new investigation data")
        lines.append("- 🧪 Enable drift monitoring via Evidently")
        lines.append("")

        content = '\n'.join(lines)
        with open(path, 'w') as f:
            f.write(content)
        print(f"📄 Report saved: {path}")
        return path

    def get_predictions_for_investigation(self, investigation_id: int) -> pd.DataFrame:
        """Run the champion model on wallets from a specific investigation."""
        if not self.best_model:
            raise RuntimeError("No trained model — run AutoML first")

        wallets_df = self.loader.get_wallets(investigation_id)
        transfers_df = self.loader.get_transfers(investigation_id)
        if wallets_df.empty or transfers_df.empty:
            return pd.DataFrame()

        from notebooks.src.classes.wallet_features import WalletFeatureExtractor
        extractor = WalletFeatureExtractor(transfers_df)

        rows = []
        for _, w in wallets_df.iterrows():
            addr = w.get('address', '')
            if not addr:
                continue
            feats = extractor.extract_features_for_wallet(addr)
            feats['address'] = addr
            feats['role'] = w.get('role', 'unknown')
            rows.append(feats)

        if not rows:
            return pd.DataFrame()

        pred_df = pd.DataFrame(rows)
        feature_cols = [c for c in self.feature_names if c in pred_df.columns]
        missing = [c for c in self.feature_names if c not in pred_df.columns]
        for c in missing:
            pred_df[c] = 0

        X_pred = pred_df[self.feature_names].fillna(0)
        if self.results.get(self.best_model_name, {}).get('needs_scaling'):
            from sklearn.preprocessing import StandardScaler
            scaler = StandardScaler()
            scaler.fit(self.X_train[self.feature_names])
            X_pred = pd.DataFrame(scaler.transform(X_pred), columns=self.feature_names)

        inv_encoding = {v: k for k, v in LABEL_ENCODING.items()}
        predictions = self.best_model.predict(X_pred)
        probabilities = self.best_model.predict_proba(X_pred) if hasattr(self.best_model, 'predict_proba') else None

        pred_df['ml_prediction'] = [inv_encoding.get(p, 'unknown') for p in predictions]
        if probabilities is not None:
            pred_df['ml_confidence'] = probabilities.max(axis=1)

        return pred_df[['address', 'role', 'ml_prediction', 'ml_confidence', 'tx_count',
                         'unique_counterparties', 'total_volume']].sort_values('ml_confidence', ascending=False)
