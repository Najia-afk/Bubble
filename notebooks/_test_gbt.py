"""Test: GradientBoosting Optuna training alone."""
import sys, os, time, warnings, traceback, signal
warnings.filterwarnings('ignore')
os.environ['TQDM_DISABLE'] = '1'
sys.path.insert(0, '/app')

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier 
from sklearn.model_selection import cross_val_score
from sklearn.preprocessing import StandardScaler
import optuna
optuna.logging.set_verbosity(optuna.logging.WARNING)

print("Creating synthetic data matching real shape...")
np.random.seed(42)
X = np.random.randn(670, 24)
y = np.random.randint(0, 5, 670)
print(f"X: {X.shape}, y: {y.shape}")
sys.stdout.flush()

def objective(trial):
    n = trial.suggest_int('n_estimators', 50, 400)
    d = trial.suggest_int('max_depth', 2, 15)
    lr = trial.suggest_float('learning_rate', 0.01, 0.3, log=True)
    model = GradientBoostingClassifier(n_estimators=n, max_depth=d, learning_rate=lr, random_state=42)
    return cross_val_score(model, X, y, cv=5, scoring='f1_macro').mean()

print("Starting Optuna study (20 trials)...")
sys.stdout.flush()

study = optuna.create_study(direction='maximize', study_name='GBT_test')
study.optimize(objective, n_trials=20, show_progress_bar=False)
print(f"Best: {study.best_value:.4f}")
print(f"Params: {study.best_params}")
sys.stdout.flush()
print("Done.")
