"""
PCA Analysis for Bubble Wallet Features
Dimensionality reduction and variance analysis.
"""
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from typing import Dict, List, Tuple, Optional


class PCAAnalysis:
    """
    PCA Analysis for wallet behavioral features.
    Provides dimensionality reduction and visualization.
    """
    
    def __init__(self, df: pd.DataFrame, features: List[str] = None, n_components: int = 10):
        """
        Initialize PCA analysis.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Feature data
        features : list, optional
            Features to use (defaults to all numeric)
        n_components : int
            Maximum components to extract
        """
        self.df = df
        
        # Auto-detect numeric features
        if features is None:
            self.features = df.select_dtypes(include=['number']).columns.tolist()
            # Remove address-like columns
            self.features = [f for f in self.features if 'address' not in f.lower()]
        else:
            self.features = features
        
        # Fit PCA
        self.n_components = min(n_components, len(self.features))
        self.pca = PCA(n_components=self.n_components)
        self.X_pca = self.pca.fit_transform(df[self.features].fillna(0))
        
        print(f"✅ PCA fitted with {self.n_components} components")
        print(f"   Total variance explained: {self.pca.explained_variance_ratio_.sum():.1%}")
    
    def get_loadings(self) -> pd.DataFrame:
        """Get feature loadings for each component."""
        loadings = pd.DataFrame(
            self.pca.components_.T,
            columns=[f'PC{i+1}' for i in range(self.n_components)],
            index=self.features
        )
        return loadings
    
    def plot_explained_variance(self, max_components: int = None) -> go.Figure:
        """
        Plot explained variance by component.
        
        Returns:
        --------
        go.Figure
            Interactive Plotly figure
        """
        if max_components is None:
            max_components = self.n_components
        
        explained = self.pca.explained_variance_ratio_[:max_components]
        cumulative = np.cumsum(explained)
        components = list(range(1, max_components + 1))
        
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        
        # Individual variance
        fig.add_trace(
            go.Bar(
                x=components,
                y=explained,
                name="Individual",
                marker_color='rgb(55, 83, 109)'
            ),
            secondary_y=False
        )
        
        # Cumulative variance
        fig.add_trace(
            go.Scatter(
                x=components,
                y=cumulative,
                name="Cumulative",
                mode='lines+markers',
                line=dict(color='red', width=2)
            ),
            secondary_y=True
        )
        
        # Add 80% and 95% threshold lines
        fig.add_hline(y=0.80, line_dash="dash", line_color="orange", 
                      annotation_text="80%", secondary_y=True)
        fig.add_hline(y=0.95, line_dash="dash", line_color="green",
                      annotation_text="95%", secondary_y=True)
        
        fig.update_layout(
            title='PCA Explained Variance',
            xaxis_title='Principal Component',
            height=500
        )
        fig.update_yaxes(title_text="Individual Variance", secondary_y=False)
        fig.update_yaxes(title_text="Cumulative Variance", secondary_y=True)
        
        return fig
    
    def plot_loadings_heatmap(self, n_components: int = 5) -> go.Figure:
        """
        Plot feature loadings as heatmap.
        
        Parameters:
        -----------
        n_components : int
            Number of components to show
            
        Returns:
        --------
        go.Figure
            Interactive heatmap
        """
        loadings = self.get_loadings()
        
        # Select top components
        cols = [f'PC{i+1}' for i in range(min(n_components, self.n_components))]
        
        fig = go.Figure(data=go.Heatmap(
            z=loadings[cols].values,
            x=cols,
            y=loadings.index,
            colorscale='RdBu_r',
            zmid=0
        ))
        
        fig.update_layout(
            title='PCA Feature Loadings',
            xaxis_title='Principal Component',
            yaxis_title='Feature',
            height=600,
            width=800
        )
        
        return fig
    
    def plot_biplot(self, pc_x: int = 1, pc_y: int = 2, 
                    labels: pd.Series = None, sample: int = 5000) -> go.Figure:
        """
        Create biplot showing samples and feature vectors.
        
        Parameters:
        -----------
        pc_x, pc_y : int
            Principal components for axes
        labels : pd.Series, optional
            Labels for coloring points
        sample : int
            Number of points to sample for visualization
            
        Returns:
        --------
        go.Figure
            Interactive biplot
        """
        # Sample data if needed
        n_points = len(self.X_pca)
        if n_points > sample:
            idx = np.random.choice(n_points, sample, replace=False)
            X_plot = self.X_pca[idx]
            if labels is not None:
                labels_plot = labels.iloc[idx]
            else:
                labels_plot = None
        else:
            X_plot = self.X_pca
            labels_plot = labels
        
        fig = go.Figure()
        
        # Plot points
        if labels_plot is not None:
            for label in labels_plot.unique():
                mask = labels_plot == label
                fig.add_trace(go.Scatter(
                    x=X_plot[mask, pc_x-1],
                    y=X_plot[mask, pc_y-1],
                    mode='markers',
                    name=str(label),
                    marker=dict(size=5, opacity=0.6)
                ))
        else:
            fig.add_trace(go.Scatter(
                x=X_plot[:, pc_x-1],
                y=X_plot[:, pc_y-1],
                mode='markers',
                name='Wallets',
                marker=dict(size=5, opacity=0.6, color='steelblue')
            ))
        
        # Add loading vectors
        loadings = self.pca.components_.T
        scale = np.max(np.abs(X_plot)) * 0.8
        
        for i, feature in enumerate(self.features):
            fig.add_annotation(
                ax=0, ay=0,
                x=loadings[i, pc_x-1] * scale,
                y=loadings[i, pc_y-1] * scale,
                axref='x', ayref='y',
                xref='x', yref='y',
                showarrow=True,
                arrowhead=2,
                arrowsize=1,
                arrowwidth=2,
                arrowcolor='red'
            )
            fig.add_annotation(
                x=loadings[i, pc_x-1] * scale * 1.1,
                y=loadings[i, pc_y-1] * scale * 1.1,
                text=feature,
                showarrow=False,
                font=dict(size=9, color='red')
            )
        
        fig.update_layout(
            title=f'PCA Biplot (PC{pc_x} vs PC{pc_y})',
            xaxis_title=f'PC{pc_x} ({self.pca.explained_variance_ratio_[pc_x-1]:.1%})',
            yaxis_title=f'PC{pc_y} ({self.pca.explained_variance_ratio_[pc_y-1]:.1%})',
            height=700,
            width=900
        )
        
        return fig
    
    def plot_3d_scatter(self, labels: pd.Series = None, sample: int = 5000) -> go.Figure:
        """
        3D scatter plot of first 3 principal components.
        
        Parameters:
        -----------
        labels : pd.Series, optional
            Labels for coloring
        sample : int
            Number of points to sample
            
        Returns:
        --------
        go.Figure
            Interactive 3D scatter
        """
        n_points = len(self.X_pca)
        if n_points > sample:
            idx = np.random.choice(n_points, sample, replace=False)
            X_plot = self.X_pca[idx]
            if labels is not None:
                labels_plot = labels.iloc[idx]
            else:
                labels_plot = None
        else:
            X_plot = self.X_pca
            labels_plot = labels
        
        if labels_plot is not None:
            fig = px.scatter_3d(
                x=X_plot[:, 0],
                y=X_plot[:, 1],
                z=X_plot[:, 2],
                color=labels_plot.astype(str),
                opacity=0.6
            )
        else:
            fig = px.scatter_3d(
                x=X_plot[:, 0],
                y=X_plot[:, 1],
                z=X_plot[:, 2],
                opacity=0.6
            )
        
        var = self.pca.explained_variance_ratio_
        fig.update_layout(
            title='3D PCA Visualization',
            scene=dict(
                xaxis_title=f'PC1 ({var[0]:.1%})',
                yaxis_title=f'PC2 ({var[1]:.1%})',
                zaxis_title=f'PC3 ({var[2]:.1%})'
            ),
            height=700
        )
        
        return fig
