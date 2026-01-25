"""
Wallet Visualization Utilities
Plotly-based visualizations for blockchain wallet analysis.
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from typing import List, Optional, Dict


class WalletVisualizer:
    """
    Interactive Plotly visualizations for wallet data analysis.
    """
    
    # Consistent color scheme
    COLORS = {
        'primary': '#1f77b4',
        'secondary': '#ff7f0e', 
        'success': '#2ca02c',
        'danger': '#d62728',
        'warning': '#f0ad4e',
        'info': '#17a2b8',
        'dark': '#343a40',
    }
    
    RISK_COLORS = {
        'low': '#28a745',
        'medium': '#ffc107',
        'high': '#fd7e14',
        'critical': '#dc3545',
    }
    
    @staticmethod
    def plot_feature_distributions(df: pd.DataFrame, 
                                   features: List[str], 
                                   n_cols: int = 3,
                                   log_scale: bool = False) -> go.Figure:
        """
        Plot histograms for multiple features.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Data with features
        features : List[str]
            Features to plot
        n_cols : int
            Number of columns in subplot grid
        log_scale : bool
            Use log scale for x-axis
            
        Returns:
        --------
        go.Figure
        """
        n_features = len(features)
        n_rows = (n_features + n_cols - 1) // n_cols
        
        fig = make_subplots(
            rows=n_rows, cols=n_cols,
            subplot_titles=features
        )
        
        for i, feature in enumerate(features):
            row = i // n_cols + 1
            col = i % n_cols + 1
            
            values = df[feature].dropna()
            
            if log_scale and values.min() > 0:
                values = np.log1p(values)
            
            fig.add_trace(
                go.Histogram(x=values, name=feature, showlegend=False),
                row=row, col=col
            )
        
        fig.update_layout(
            height=200 * n_rows,
            title_text='Feature Distributions',
            showlegend=False
        )
        
        return fig
    
    @staticmethod
    def plot_correlation_matrix(df: pd.DataFrame, 
                               features: List[str] = None) -> go.Figure:
        """
        Plot correlation heatmap.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Data
        features : List[str], optional
            Features to include
            
        Returns:
        --------
        go.Figure
        """
        if features is None:
            features = df.select_dtypes(include=['number']).columns.tolist()
        
        corr = df[features].corr()
        
        fig = go.Figure(data=go.Heatmap(
            z=corr.values,
            x=features,
            y=features,
            colorscale='RdBu_r',
            zmid=0,
            text=corr.values.round(2),
            texttemplate='%{text}',
            textfont={"size": 8},
            hoverongaps=False
        ))
        
        fig.update_layout(
            title='Feature Correlation Matrix',
            height=max(400, len(features) * 25),
            width=max(600, len(features) * 30)
        )
        
        return fig
    
    @staticmethod
    def plot_wallet_risk_distribution(df: pd.DataFrame,
                                      score_col: str = 'risk_score') -> go.Figure:
        """
        Plot risk score distribution with thresholds.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Data with risk scores
        score_col : str
            Column name for risk score
            
        Returns:
        --------
        go.Figure
        """
        fig = go.Figure()
        
        fig.add_trace(go.Histogram(
            x=df[score_col],
            nbinsx=50,
            name='Risk Score',
            marker_color='steelblue'
        ))
        
        # Add threshold lines
        thresholds = [
            (0.3, 'Low/Medium', 'green'),
            (0.6, 'Medium/High', 'orange'),
            (0.8, 'High/Critical', 'red')
        ]
        
        for thresh, label, color in thresholds:
            fig.add_vline(
                x=thresh, 
                line_dash="dash", 
                line_color=color,
                annotation_text=label
            )
        
        fig.update_layout(
            title='Risk Score Distribution',
            xaxis_title='Risk Score',
            yaxis_title='Count',
            height=400
        )
        
        return fig
    
    @staticmethod
    def plot_cluster_distribution(labels: np.ndarray) -> go.Figure:
        """
        Plot cluster size distribution.
        
        Parameters:
        -----------
        labels : np.ndarray
            Cluster labels
            
        Returns:
        --------
        go.Figure
        """
        unique, counts = np.unique(labels, return_counts=True)
        
        colors = ['#888888' if u == -1 else px.colors.qualitative.Plotly[i % 10] 
                  for i, u in enumerate(unique)]
        
        fig = go.Figure(data=[
            go.Bar(
                x=[f'Cluster {u}' if u != -1 else 'Noise' for u in unique],
                y=counts,
                marker_color=colors,
                text=counts,
                textposition='auto'
            )
        ])
        
        fig.update_layout(
            title='Cluster Size Distribution',
            xaxis_title='Cluster',
            yaxis_title='Count',
            height=400
        )
        
        return fig
    
    @staticmethod
    def plot_time_series(df: pd.DataFrame,
                         date_col: str = 'timestamp',
                         value_col: str = 'value',
                         agg: str = 'sum') -> go.Figure:
        """
        Plot time series of transactions.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Transaction data
        date_col : str
            Date column
        value_col : str
            Value column
        agg : str
            Aggregation function
            
        Returns:
        --------
        go.Figure
        """
        df_copy = df.copy()
        df_copy[date_col] = pd.to_datetime(df_copy[date_col])
        
        daily = df_copy.groupby(df_copy[date_col].dt.date)[value_col].agg(agg).reset_index()
        daily.columns = ['date', 'value']
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=daily['date'],
            y=daily['value'],
            mode='lines+markers',
            name='Daily Value'
        ))
        
        fig.update_layout(
            title=f'Transaction {agg.title()} Over Time',
            xaxis_title='Date',
            yaxis_title=f'{agg.title()} Value',
            height=400
        )
        
        return fig
    
    @staticmethod  
    def plot_wallet_comparison(profiles: pd.DataFrame,
                               features: List[str],
                               wallets: List[int]) -> go.Figure:
        """
        Radar chart comparing multiple wallets/clusters.
        
        Parameters:
        -----------
        profiles : pd.DataFrame
            Feature profiles (normalized)
        features : List[str]
            Features to compare
        wallets : List[int]
            Wallet/cluster indices to compare
            
        Returns:
        --------
        go.Figure
        """
        from sklearn.preprocessing import MinMaxScaler
        
        scaler = MinMaxScaler()
        normalized = pd.DataFrame(
            scaler.fit_transform(profiles[features]),
            columns=features,
            index=profiles.index
        )
        
        fig = go.Figure()
        
        colors = px.colors.qualitative.Plotly
        
        for i, wallet in enumerate(wallets):
            if wallet in normalized.index:
                values = normalized.loc[wallet].values.tolist()
                values.append(values[0])  # Close the radar
                
                fig.add_trace(go.Scatterpolar(
                    r=values,
                    theta=features + [features[0]],
                    fill='toself',
                    name=f'Cluster {wallet}',
                    line_color=colors[i % len(colors)]
                ))
        
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            title='Cluster Profile Comparison',
            height=500
        )
        
        return fig
    
    @staticmethod
    def plot_feature_importance(feature_names: List[str],
                                importances: np.ndarray,
                                top_n: int = 20) -> go.Figure:
        """
        Plot feature importance bar chart.
        
        Parameters:
        -----------
        feature_names : List[str]
            Feature names
        importances : np.ndarray
            Importance values
        top_n : int
            Number of features to show
            
        Returns:
        --------
        go.Figure
        """
        # Sort by importance
        idx = np.argsort(importances)[::-1][:top_n]
        
        fig = go.Figure(go.Bar(
            x=importances[idx],
            y=[feature_names[i] for i in idx],
            orientation='h',
            marker_color='steelblue'
        ))
        
        fig.update_layout(
            title=f'Top {top_n} Feature Importances',
            xaxis_title='Importance',
            yaxis_title='Feature',
            height=max(400, top_n * 25),
            yaxis=dict(autorange='reversed')
        )
        
        return fig
    
    @staticmethod
    def plot_confusion_matrix(y_true: np.ndarray,
                              y_pred: np.ndarray,
                              labels: List[str] = None) -> go.Figure:
        """
        Plot confusion matrix heatmap.
        
        Parameters:
        -----------
        y_true : np.ndarray
            True labels
        y_pred : np.ndarray
            Predicted labels
        labels : List[str]
            Label names
            
        Returns:
        --------
        go.Figure
        """
        from sklearn.metrics import confusion_matrix
        
        cm = confusion_matrix(y_true, y_pred)
        
        if labels is None:
            labels = [str(i) for i in range(len(cm))]
        
        fig = go.Figure(data=go.Heatmap(
            z=cm,
            x=labels,
            y=labels,
            colorscale='Blues',
            text=cm,
            texttemplate='%{text}',
            textfont={"size": 14},
            hoverongaps=False
        ))
        
        fig.update_layout(
            title='Confusion Matrix',
            xaxis_title='Predicted',
            yaxis_title='Actual',
            height=400,
            width=500
        )
        
        return fig
    
    @staticmethod
    def create_summary_dashboard(df: pd.DataFrame,
                                 labels: np.ndarray = None) -> go.Figure:
        """
        Create a summary dashboard with multiple panels.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Feature data
        labels : np.ndarray
            Cluster labels (optional)
            
        Returns:
        --------
        go.Figure
        """
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('Sample Size', 'Feature Count', 
                          'Cluster Distribution', 'Value Distribution'),
            specs=[[{"type": "indicator"}, {"type": "indicator"}],
                   [{"type": "bar"}, {"type": "histogram"}]]
        )
        
        # Sample size indicator
        fig.add_trace(go.Indicator(
            mode="number",
            value=len(df),
            title={"text": "Total Samples"}
        ), row=1, col=1)
        
        # Feature count indicator
        numeric_cols = df.select_dtypes(include=['number']).columns
        fig.add_trace(go.Indicator(
            mode="number",
            value=len(numeric_cols),
            title={"text": "Features"}
        ), row=1, col=2)
        
        # Cluster distribution
        if labels is not None:
            unique, counts = np.unique(labels, return_counts=True)
            fig.add_trace(go.Bar(
                x=[f'C{u}' for u in unique],
                y=counts,
                showlegend=False
            ), row=2, col=1)
        
        # Value distribution (first numeric column)
        if len(numeric_cols) > 0:
            fig.add_trace(go.Histogram(
                x=df[numeric_cols[0]].dropna(),
                name=numeric_cols[0],
                showlegend=False
            ), row=2, col=2)
        
        fig.update_layout(
            title='Data Summary Dashboard',
            height=600
        )
        
        return fig
