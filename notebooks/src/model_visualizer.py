"""
ModelVisualizer — Plotly charts for ML model performance.

Following mission7 pattern: static methods, Plotly figures, SHAP integration.
For use in Jupyter notebooks during model development.

Usage:
    from notebooks.src.model_visualizer import ModelVisualizer as mviz
    fig = mviz.plot_feature_importance(shap_values, feature_names)
    fig.show()
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Optional, Any
from collections import defaultdict


class ModelVisualizer:
    """
    Plotly-based ML model visualizations.
    All methods return go.Figure objects for interactive display.
    """

    @staticmethod
    def plot_confusion_matrix(
        y_true: np.ndarray,
        y_pred: np.ndarray,
        labels: List[str] = None
    ) -> go.Figure:
        """Interactive confusion matrix heatmap."""
        from sklearn.metrics import confusion_matrix
        cm = confusion_matrix(y_true, y_pred)

        if labels is None:
            labels = [str(i) for i in range(cm.shape[0])]

        fig = go.Figure(go.Heatmap(
            z=cm,
            x=labels,
            y=labels,
            texttemplate='%{z}',
            colorscale='Blues',
            hovertemplate="True: %{y}<br>Predicted: %{x}<br>Count: %{z}<extra></extra>",
        ))
        fig.update_layout(
            title="Confusion Matrix",
            xaxis_title="Predicted",
            yaxis_title="True",
            template='plotly_white',
            width=500, height=500,
        )
        return fig

    @staticmethod
    def plot_model_comparison(
        results: Dict[str, Dict[str, float]],
        metrics: List[str] = None
    ) -> go.Figure:
        """
        Radar chart comparing multiple models on multiple metrics.
        
        Args:
            results: {model_name: {metric_name: value, ...}, ...}
            metrics: List of metric names to include
        """
        if metrics is None:
            metrics = ['accuracy', 'precision', 'recall', 'f1_score', 'roc_auc']

        fig = go.Figure()
        for model_name, model_metrics in results.items():
            values = [model_metrics.get(m, 0) for m in metrics]
            values.append(values[0])  # Close the polygon
            fig.add_trace(go.Scatterpolar(
                r=values,
                theta=metrics + [metrics[0]],
                name=model_name,
                fill='toself',
                opacity=0.6,
            ))

        fig.update_layout(
            title="Model Comparison",
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            template='plotly_white',
            height=500,
        )
        return fig

    @staticmethod
    def plot_learning_curves(
        train_sizes: np.ndarray,
        train_scores: np.ndarray,
        val_scores: np.ndarray,
        scoring_name: str = 'Score'
    ) -> go.Figure:
        """Learning curves with shaded confidence band."""
        train_mean = np.mean(train_scores, axis=1)
        train_std = np.std(train_scores, axis=1)
        val_mean = np.mean(val_scores, axis=1)
        val_std = np.std(val_scores, axis=1)

        fig = go.Figure()

        # Training score
        fig.add_trace(go.Scatter(
            x=train_sizes, y=train_mean, name='Training Score',
            mode='lines+markers', line=dict(color='blue'),
        ))
        fig.add_trace(go.Scatter(
            x=np.concatenate([train_sizes, train_sizes[::-1]]),
            y=np.concatenate([train_mean + train_std, (train_mean - train_std)[::-1]]),
            fill='toself', fillcolor='rgba(0,0,255,0.1)',
            line=dict(color='rgba(0,0,0,0)'), showlegend=False,
        ))

        # Validation score
        fig.add_trace(go.Scatter(
            x=train_sizes, y=val_mean, name='Validation Score',
            mode='lines+markers', line=dict(color='green'),
        ))
        fig.add_trace(go.Scatter(
            x=np.concatenate([train_sizes, train_sizes[::-1]]),
            y=np.concatenate([val_mean + val_std, (val_mean - val_std)[::-1]]),
            fill='toself', fillcolor='rgba(0,128,0,0.1)',
            line=dict(color='rgba(0,0,0,0)'), showlegend=False,
        ))

        fig.update_layout(
            title=f"Learning Curves ({scoring_name})",
            xaxis_title='Training Examples',
            yaxis_title=scoring_name,
            template='plotly_white',
            height=450,
            hovermode='x unified',
        )
        return fig

    @staticmethod
    def plot_feature_importance(
        importances: np.ndarray,
        feature_names: List[str],
        top_n: int = 20,
        title: str = "Feature Importance"
    ) -> go.Figure:
        """Horizontal bar chart of top feature importances (SHAP or model-based)."""
        idx = np.argsort(np.abs(importances))[-top_n:]
        sorted_names = [feature_names[i] for i in idx]
        sorted_values = importances[idx]

        colors = ['#d62728' if v > 0 else '#1f77b4' for v in sorted_values]

        fig = go.Figure(go.Bar(
            x=sorted_values,
            y=sorted_names,
            orientation='h',
            marker_color=colors,
        ))
        fig.update_layout(
            title=title,
            xaxis_title="Importance",
            template='plotly_white',
            height=max(400, top_n * 25),
        )
        return fig

    @staticmethod
    def plot_shap_summary(
        shap_values: np.ndarray,
        feature_names: List[str],
        X: np.ndarray = None,
        top_n: int = 20
    ) -> go.Figure:
        """
        SHAP summary plot (beeswarm-style).
        Shows distribution of SHAP values for each feature.
        """
        mean_abs_shap = np.mean(np.abs(shap_values), axis=0)
        top_idx = np.argsort(mean_abs_shap)[-top_n:]

        fig = go.Figure()
        for i in top_idx:
            vals = shap_values[:, i]
            fig.add_trace(go.Box(
                x=vals,
                name=feature_names[i],
                orientation='h',
                marker_color='#1f77b4',
                boxmean=True,
            ))

        fig.update_layout(
            title="SHAP Value Distribution",
            xaxis_title="SHAP Value (impact on prediction)",
            template='plotly_white',
            height=max(400, top_n * 30),
            showlegend=False,
        )
        return fig

    @staticmethod
    def plot_score_distribution(
        y_true: np.ndarray,
        y_proba: np.ndarray,
        threshold: float = 0.5
    ) -> go.Figure:
        """Histogram of predicted probabilities, split by true class."""
        fig = go.Figure()

        for cls, name, color in [(0, 'Negative', '#1f77b4'), (1, 'Positive', '#d62728')]:
            mask = y_true == cls
            fig.add_trace(go.Histogram(
                x=y_proba[mask],
                name=name,
                marker_color=color,
                opacity=0.6,
                nbinsx=50,
            ))

        fig.add_vline(x=threshold, line_dash='dash', line_color='black',
                     annotation_text=f'Threshold={threshold}')

        fig.update_layout(
            title="Prediction Score Distribution",
            xaxis_title="Predicted Probability",
            yaxis_title="Count",
            barmode='overlay',
            template='plotly_white',
            height=400,
        )
        return fig

    @staticmethod
    def plot_roc_curves(
        results: Dict[str, Dict],
    ) -> go.Figure:
        """
        ROC curves for multiple models.
        
        Args:
            results: {model_name: {'fpr': array, 'tpr': array, 'auc': float}, ...}
        """
        fig = go.Figure()
        for name, data in results.items():
            fig.add_trace(go.Scatter(
                x=data['fpr'], y=data['tpr'],
                name=f"{name} (AUC={data['auc']:.3f})",
                mode='lines',
            ))

        fig.add_trace(go.Scatter(
            x=[0, 1], y=[0, 1],
            line=dict(dash='dash', color='grey'),
            showlegend=False,
        ))

        fig.update_layout(
            title="ROC Curves",
            xaxis_title="False Positive Rate",
            yaxis_title="True Positive Rate",
            template='plotly_white',
            height=500,
        )
        return fig
