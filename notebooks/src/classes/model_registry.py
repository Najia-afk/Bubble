"""
MLflow Model Registry Integration for Bubble Notebook
Handles model logging, registration, and champion promotion.
"""
import os
import pickle
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional
import pandas as pd
import numpy as np

try:
    import mlflow
    from mlflow.tracking import MlflowClient
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    print("⚠️ MLflow not available. Install with: pip install mlflow")


class ModelRegistry:
    """
    Manage MLflow experiment tracking and model registry.
    Follows mission7 patterns for model versioning and champion promotion.
    """
    
    def __init__(self, 
                 tracking_uri: str = None,
                 experiment_name: str = "bubble_wallet_clustering"):
        """
        Initialize MLflow connection.
        
        Parameters:
        -----------
        tracking_uri : str
            MLflow tracking server URI
        experiment_name : str
            Experiment name for tracking
        """
        if not MLFLOW_AVAILABLE:
            raise ImportError("MLflow is required. Install with: pip install mlflow")
        
        self.tracking_uri = tracking_uri or os.getenv('MLFLOW_TRACKING_URI', 'http://localhost:5000')
        self.experiment_name = experiment_name
        
        # Connect to MLflow
        mlflow.set_tracking_uri(self.tracking_uri)
        
        # Create or get experiment
        experiment = mlflow.get_experiment_by_name(experiment_name)
        if experiment is None:
            self.experiment_id = mlflow.create_experiment(experiment_name)
        else:
            self.experiment_id = experiment.experiment_id
        
        mlflow.set_experiment(experiment_name)
        
        self.client = MlflowClient()
        
        print(f"✅ Connected to MLflow at {self.tracking_uri}")
        print(f"   Experiment: {experiment_name} (ID: {self.experiment_id})")
    
    def log_clustering_run(self,
                           cluster_model,
                           metrics: Dict[str, float],
                           params: Dict[str, Any],
                           features_df: pd.DataFrame,
                           run_name: str = None,
                           tags: Dict[str, str] = None) -> str:
        """
        Log a clustering run to MLflow.
        
        Parameters:
        -----------
        cluster_model : sklearn clustering model
            Fitted clustering model (KMeans, DBSCAN, etc.)
        metrics : Dict
            Metrics to log (silhouette, calinski, etc.)
        params : Dict
            Parameters (n_clusters, eps, etc.)
        features_df : pd.DataFrame
            Feature dataframe used for clustering
        run_name : str
            Optional run name
        tags : Dict
            Optional tags
            
        Returns:
        --------
        str
            MLflow run ID
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_name = run_name or f"clustering_{timestamp}"
        
        with mlflow.start_run(run_name=run_name) as run:
            # Log parameters
            for key, value in params.items():
                mlflow.log_param(key, value)
            
            # Log metrics
            for key, value in metrics.items():
                if isinstance(value, (int, float)) and not np.isnan(value):
                    mlflow.log_metric(key, value)
            
            # Log model
            mlflow.sklearn.log_model(cluster_model, "cluster_model")
            
            # Log feature names
            mlflow.log_param("n_features", len(features_df.columns))
            
            # Save feature names artifact
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write('\n'.join(features_df.columns.tolist()))
                f.flush()
                mlflow.log_artifact(f.name, "features")
                os.unlink(f.name)
            
            # Log cluster distribution
            if hasattr(cluster_model, 'labels_'):
                labels = cluster_model.labels_
                unique, counts = np.unique(labels, return_counts=True)
                for label, count in zip(unique, counts):
                    mlflow.log_metric(f"cluster_{label}_count", count)
            
            # Tags
            mlflow.set_tag("model_type", type(cluster_model).__name__)
            mlflow.set_tag("dataset_size", len(features_df))
            
            if tags:
                for key, value in tags.items():
                    mlflow.set_tag(key, value)
            
            run_id = run.info.run_id
            print(f"✅ Logged run: {run_name} (ID: {run_id})")
            
            return run_id
    
    def register_model(self, run_id: str, model_name: str = "bubble_cluster_model") -> str:
        """
        Register a model from a run to the model registry.
        
        Parameters:
        -----------
        run_id : str
            MLflow run ID
        model_name : str
            Name for registered model
            
        Returns:
        --------
        str
            Model version
        """
        model_uri = f"runs:/{run_id}/cluster_model"
        
        result = mlflow.register_model(model_uri, model_name)
        
        version = result.version
        print(f"✅ Registered model: {model_name} v{version}")
        
        return version
    
    def promote_to_champion(self, 
                           model_name: str = "bubble_cluster_model",
                           version: str = None,
                           metric_name: str = "silhouette",
                           higher_is_better: bool = True) -> bool:
        """
        Promote a model version to champion (Production alias).
        
        Parameters:
        -----------
        model_name : str
            Registered model name
        version : str
            Specific version to promote (None = find best)
        metric_name : str
            Metric to compare for finding best
        higher_is_better : bool
            Whether higher metric is better
            
        Returns:
        --------
        bool
            Success
        """
        try:
            # Get all versions
            versions = self.client.search_model_versions(f"name='{model_name}'")
            
            if not versions:
                print(f"❌ No versions found for model: {model_name}")
                return False
            
            if version is None:
                # Find best version by metric
                best_version = None
                best_metric = None
                
                for v in versions:
                    run = self.client.get_run(v.run_id)
                    metrics = run.data.metrics
                    
                    if metric_name in metrics:
                        m = metrics[metric_name]
                        if best_metric is None:
                            best_metric = m
                            best_version = v.version
                        elif (higher_is_better and m > best_metric) or \
                             (not higher_is_better and m < best_metric):
                            best_metric = m
                            best_version = v.version
                
                if best_version is None:
                    print(f"❌ No versions found with metric: {metric_name}")
                    return False
                
                version = best_version
                print(f"📊 Best version by {metric_name}: v{version} ({best_metric:.4f})")
            
            # Set alias (MLflow 2.0+)
            try:
                self.client.set_registered_model_alias(model_name, "champion", version)
                print(f"🏆 Promoted {model_name} v{version} to Champion")
            except AttributeError:
                # Fallback for older MLflow
                self.client.transition_model_version_stage(
                    name=model_name,
                    version=version,
                    stage="Production"
                )
                print(f"🏆 Promoted {model_name} v{version} to Production stage")
            
            return True
            
        except Exception as e:
            print(f"❌ Error promoting model: {e}")
            return False
    
    def get_champion_model(self, model_name: str = "bubble_cluster_model"):
        """
        Load the champion (production) model.
        
        Parameters:
        -----------
        model_name : str
            Registered model name
            
        Returns:
        --------
        sklearn model
            The champion model
        """
        try:
            # Try alias first (MLflow 2.0+)
            try:
                model_version = self.client.get_model_version_by_alias(model_name, "champion")
                model_uri = f"models:/{model_name}@champion"
            except AttributeError:
                # Fallback to stage
                versions = self.client.get_latest_versions(model_name, stages=["Production"])
                if not versions:
                    print(f"❌ No champion model found for: {model_name}")
                    return None
                model_version = versions[0]
                model_uri = f"models:/{model_name}/Production"
            
            model = mlflow.sklearn.load_model(model_uri)
            print(f"✅ Loaded champion model: {model_name} v{model_version.version}")
            
            return model
            
        except Exception as e:
            print(f"❌ Error loading champion: {e}")
            return None
    
    def compare_with_champion(self,
                             new_metrics: Dict[str, float],
                             model_name: str = "bubble_cluster_model",
                             metric_name: str = "silhouette") -> Dict:
        """
        Compare new model metrics with the current champion.
        
        Parameters:
        -----------
        new_metrics : Dict
            Metrics from new model
        model_name : str
            Registered model name
        metric_name : str
            Primary metric to compare
            
        Returns:
        --------
        Dict
            Comparison results
        """
        result = {
            'new_metric': new_metrics.get(metric_name, 0),
            'champion_metric': None,
            'improvement': None,
            'is_better': False
        }
        
        try:
            # Get champion version
            try:
                champion_version = self.client.get_model_version_by_alias(model_name, "champion")
            except (AttributeError, Exception):
                versions = self.client.get_latest_versions(model_name, stages=["Production"])
                if not versions:
                    print("ℹ️ No champion model exists yet. New model will be first champion.")
                    result['is_better'] = True
                    return result
                champion_version = versions[0]
            
            # Get champion metrics
            run = self.client.get_run(champion_version.run_id)
            champion_metrics = run.data.metrics
            
            if metric_name in champion_metrics:
                champion_value = champion_metrics[metric_name]
                result['champion_metric'] = champion_value
                result['improvement'] = result['new_metric'] - champion_value
                result['is_better'] = result['new_metric'] > champion_value
                
                print(f"📊 Champion {metric_name}: {champion_value:.4f}")
                print(f"📊 New model {metric_name}: {result['new_metric']:.4f}")
                
                if result['is_better']:
                    print(f"✅ New model is BETTER by {result['improvement']:.4f}")
                else:
                    print(f"❌ New model is worse by {abs(result['improvement']):.4f}")
            
        except Exception as e:
            print(f"⚠️ Could not compare with champion: {e}")
            result['is_better'] = True  # Promote if comparison fails
        
        return result
    
    def get_experiment_runs(self, 
                           max_results: int = 20,
                           order_by: str = "metrics.silhouette DESC") -> pd.DataFrame:
        """
        Get recent experiment runs.
        
        Parameters:
        -----------
        max_results : int
            Maximum number of runs
        order_by : str
            Ordering (e.g., "metrics.silhouette DESC")
            
        Returns:
        --------
        pd.DataFrame
            Run summaries
        """
        runs = self.client.search_runs(
            experiment_ids=[self.experiment_id],
            max_results=max_results,
            order_by=[order_by] if order_by else None
        )
        
        data = []
        for run in runs:
            row = {
                'run_id': run.info.run_id,
                'run_name': run.info.run_name,
                'start_time': datetime.fromtimestamp(run.info.start_time / 1000),
                'status': run.info.status
            }
            row.update(run.data.params)
            row.update(run.data.metrics)
            data.append(row)
        
        return pd.DataFrame(data)
