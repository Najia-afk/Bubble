"""
Cluster Analysis for Bubble Wallet Features
K-Means, DBSCAN, and Agglomerative clustering with evaluation.
"""
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans, MiniBatchKMeans, DBSCAN, AgglomerativeClustering
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score, silhouette_samples, calinski_harabasz_score, davies_bouldin_score
from sklearn.neighbors import NearestNeighbors
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import plotly.express as px
from typing import Dict, List, Tuple, Optional
from tqdm import tqdm


class ClusterAnalysis:
    """
    Comprehensive clustering analysis for wallet behavioral features.
    Supports K-Means, DBSCAN, and Agglomerative clustering.
    """
    
    # Color palette for clusters (consistent with mission5)
    CLUSTER_COLORS = [
        '#5cb85c',  # green
        '#5bc0de',  # blue
        '#f0ad4e',  # orange
        '#d9534f',  # red
        '#9370DB',  # purple
        '#C71585',  # magenta
        '#20B2AA',  # teal
        '#F08080',  # coral
        '#4682B4',  # steel blue
        '#FFD700',  # gold
    ]
    
    def __init__(self, df: pd.DataFrame, features: List[str] = None, n_pca_components: int = 10):
        """
        Initialize clustering analysis.
        
        Parameters:
        -----------
        df : pd.DataFrame
            Feature data
        features : list, optional
            Features to use for clustering
        n_pca_components : int
            Number of PCA components for dimensionality reduction
        """
        self.df = df
        
        # Auto-detect numeric features
        if features is None:
            self.features = df.select_dtypes(include=['number']).columns.tolist()
            self.features = [f for f in self.features if 'address' not in f.lower()]
        else:
            self.features = features
        
        # Apply PCA for visualization and clustering
        self.n_components = min(n_pca_components, len(self.features))
        self.pca = PCA(n_components=self.n_components)
        self.X = self.pca.fit_transform(df[self.features].fillna(0))
        
        # Store results
        self.kmeans_results = {}
        self.labels_ = None
        self.model_ = None
        
        print(f"✅ Initialized with {len(df):,} samples, {len(self.features)} features")
        print(f"   PCA variance explained: {self.pca.explained_variance_ratio_.sum():.1%}")
    
    def get_cluster_color(self, idx: int) -> str:
        """Get consistent color for cluster index."""
        return self.CLUSTER_COLORS[idx % len(self.CLUSTER_COLORS)]
    
    # =========================================================================
    # ELBOW METHOD & SILHOUETTE
    # =========================================================================
    
    def elbow_analysis(self, k_range: range = range(2, 15)) -> Dict:
        """
        Perform elbow method analysis to find optimal K.
        
        Parameters:
        -----------
        k_range : range
            Range of K values to test
            
        Returns:
        --------
        Dict
            Inertia and silhouette scores for each K
        """
        inertias = []
        silhouettes = []
        calinski = []
        davies = []
        
        for k in tqdm(k_range, desc="Elbow analysis"):
            kmeans = MiniBatchKMeans(n_clusters=k, batch_size=1024, random_state=42)
            labels = kmeans.fit_predict(self.X)
            
            inertias.append(kmeans.inertia_)
            
            if k > 1:
                sil = silhouette_score(self.X, labels, sample_size=min(10000, len(self.X)))
                cal = calinski_harabasz_score(self.X, labels)
                dav = davies_bouldin_score(self.X, labels)
            else:
                sil, cal, dav = 0, 0, 0
            
            silhouettes.append(sil)
            calinski.append(cal)
            davies.append(dav)
        
        self.elbow_results = {
            'k_range': list(k_range),
            'inertia': inertias,
            'silhouette': silhouettes,
            'calinski': calinski,
            'davies': davies
        }
        
        # Find optimal K
        best_k_sil = k_range[np.argmax(silhouettes)]
        print(f"📊 Best K by silhouette: {best_k_sil} (score: {max(silhouettes):.3f})")
        
        return self.elbow_results
    
    def plot_elbow(self) -> go.Figure:
        """Plot elbow curve and silhouette scores."""
        if not hasattr(self, 'elbow_results'):
            self.elbow_analysis()
        
        results = self.elbow_results
        
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('Elbow Curve (Inertia)', 'Silhouette Score',
                          'Calinski-Harabasz Index', 'Davies-Bouldin Index')
        )
        
        # Inertia
        fig.add_trace(
            go.Scatter(x=results['k_range'], y=results['inertia'],
                      mode='lines+markers', name='Inertia'),
            row=1, col=1
        )
        
        # Silhouette
        fig.add_trace(
            go.Scatter(x=results['k_range'], y=results['silhouette'],
                      mode='lines+markers', name='Silhouette', marker_color='green'),
            row=1, col=2
        )
        
        # Calinski-Harabasz
        fig.add_trace(
            go.Scatter(x=results['k_range'], y=results['calinski'],
                      mode='lines+markers', name='Calinski-Harabasz', marker_color='orange'),
            row=2, col=1
        )
        
        # Davies-Bouldin (lower is better)
        fig.add_trace(
            go.Scatter(x=results['k_range'], y=results['davies'],
                      mode='lines+markers', name='Davies-Bouldin', marker_color='red'),
            row=2, col=2
        )
        
        fig.update_layout(
            title='Cluster Evaluation Metrics',
            height=700,
            showlegend=False
        )
        
        return fig
    
    # =========================================================================
    # K-MEANS CLUSTERING
    # =========================================================================
    
    def fit_kmeans(self, n_clusters: int = 5) -> 'ClusterAnalysis':
        """
        Fit K-Means clustering.
        
        Parameters:
        -----------
        n_clusters : int
            Number of clusters
            
        Returns:
        --------
        self
        """
        self.model_ = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        self.labels_ = self.model_.fit_predict(self.X)
        self.n_clusters_ = n_clusters
        self.method_ = 'kmeans'
        
        # Calculate metrics
        self.silhouette_ = silhouette_score(self.X, self.labels_)
        self.inertia_ = self.model_.inertia_
        
        print(f"✅ K-Means fitted with {n_clusters} clusters")
        print(f"   Silhouette score: {self.silhouette_:.3f}")
        
        return self
    
    # =========================================================================
    # DBSCAN CLUSTERING
    # =========================================================================
    
    def estimate_dbscan_eps(self, k: int = 5) -> go.Figure:
        """
        Estimate DBSCAN eps parameter using k-distance graph.
        
        Parameters:
        -----------
        k : int
            Number of neighbors
            
        Returns:
        --------
        go.Figure
            K-distance plot
        """
        nbrs = NearestNeighbors(n_neighbors=k).fit(self.X)
        distances, _ = nbrs.kneighbors(self.X)
        
        k_distances = np.sort(distances[:, k-1])[::-1]
        
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            y=k_distances,
            mode='lines',
            name=f'{k}-distance'
        ))
        
        fig.update_layout(
            title=f'K-Distance Graph (k={k})',
            xaxis_title='Points (sorted)',
            yaxis_title='Distance to k-th neighbor',
            height=400
        )
        
        return fig
    
    def fit_dbscan(self, eps: float = 0.5, min_samples: int = 5) -> 'ClusterAnalysis':
        """
        Fit DBSCAN clustering.
        
        Parameters:
        -----------
        eps : float
            Maximum distance between neighbors
        min_samples : int
            Minimum points for core sample
            
        Returns:
        --------
        self
        """
        self.model_ = DBSCAN(eps=eps, min_samples=min_samples)
        self.labels_ = self.model_.fit_predict(self.X)
        self.n_clusters_ = len(set(self.labels_)) - (1 if -1 in self.labels_ else 0)
        self.method_ = 'dbscan'
        
        # Noise points
        n_noise = (self.labels_ == -1).sum()
        
        if self.n_clusters_ > 1:
            # Exclude noise for silhouette
            mask = self.labels_ != -1
            self.silhouette_ = silhouette_score(self.X[mask], self.labels_[mask])
        else:
            self.silhouette_ = 0
        
        print(f"✅ DBSCAN fitted: {self.n_clusters_} clusters, {n_noise} noise points")
        print(f"   Silhouette score: {self.silhouette_:.3f}")
        
        return self
    
    # =========================================================================
    # AGGLOMERATIVE CLUSTERING
    # =========================================================================
    
    def fit_agglomerative(self, n_clusters: int = 5, linkage: str = 'ward') -> 'ClusterAnalysis':
        """
        Fit Agglomerative clustering.
        
        Parameters:
        -----------
        n_clusters : int
            Number of clusters
        linkage : str
            Linkage criterion: 'ward', 'complete', 'average', 'single'
            
        Returns:
        --------
        self
        """
        self.model_ = AgglomerativeClustering(n_clusters=n_clusters, linkage=linkage)
        self.labels_ = self.model_.fit_predict(self.X)
        self.n_clusters_ = n_clusters
        self.method_ = 'agglomerative'
        
        self.silhouette_ = silhouette_score(self.X, self.labels_)
        
        print(f"✅ Agglomerative ({linkage}) fitted with {n_clusters} clusters")
        print(f"   Silhouette score: {self.silhouette_:.3f}")
        
        return self
    
    # =========================================================================
    # VISUALIZATION
    # =========================================================================
    
    def plot_clusters_2d(self, pc_x: int = 1, pc_y: int = 2, sample: int = 10000) -> go.Figure:
        """
        Plot clusters in 2D PCA space.
        
        Parameters:
        -----------
        pc_x, pc_y : int
            Principal components for axes
        sample : int
            Number of points to sample
            
        Returns:
        --------
        go.Figure
        """
        if self.labels_ is None:
            raise ValueError("No clustering performed yet. Call fit_kmeans/fit_dbscan first.")
        
        n_points = len(self.X)
        if n_points > sample:
            idx = np.random.choice(n_points, sample, replace=False)
            X_plot = self.X[idx]
            labels_plot = self.labels_[idx]
        else:
            X_plot = self.X
            labels_plot = self.labels_
        
        fig = go.Figure()
        
        for cluster in sorted(set(labels_plot)):
            mask = labels_plot == cluster
            name = 'Noise' if cluster == -1 else f'Cluster {cluster}'
            color = '#888888' if cluster == -1 else self.get_cluster_color(cluster)
            
            fig.add_trace(go.Scatter(
                x=X_plot[mask, pc_x-1],
                y=X_plot[mask, pc_y-1],
                mode='markers',
                name=name,
                marker=dict(size=6, opacity=0.6, color=color)
            ))
        
        var = self.pca.explained_variance_ratio_
        fig.update_layout(
            title=f'{self.method_.upper()} Clusters (n={self.n_clusters_}, silhouette={self.silhouette_:.3f})',
            xaxis_title=f'PC{pc_x} ({var[pc_x-1]:.1%})',
            yaxis_title=f'PC{pc_y} ({var[pc_y-1]:.1%})',
            height=600
        )
        
        return fig
    
    def plot_clusters_3d(self, sample: int = 10000) -> go.Figure:
        """Plot clusters in 3D PCA space."""
        if self.labels_ is None:
            raise ValueError("No clustering performed yet.")
        
        n_points = len(self.X)
        if n_points > sample:
            idx = np.random.choice(n_points, sample, replace=False)
            X_plot = self.X[idx]
            labels_plot = self.labels_[idx]
        else:
            X_plot = self.X
            labels_plot = self.labels_
        
        fig = go.Figure()
        
        for cluster in sorted(set(labels_plot)):
            mask = labels_plot == cluster
            name = 'Noise' if cluster == -1 else f'Cluster {cluster}'
            color = '#888888' if cluster == -1 else self.get_cluster_color(cluster)
            
            fig.add_trace(go.Scatter3d(
                x=X_plot[mask, 0],
                y=X_plot[mask, 1],
                z=X_plot[mask, 2],
                mode='markers',
                name=name,
                marker=dict(size=4, opacity=0.6, color=color)
            ))
        
        var = self.pca.explained_variance_ratio_
        fig.update_layout(
            title=f'{self.method_.upper()} Clusters (3D)',
            scene=dict(
                xaxis_title=f'PC1 ({var[0]:.1%})',
                yaxis_title=f'PC2 ({var[1]:.1%})',
                zaxis_title=f'PC3 ({var[2]:.1%})'
            ),
            height=700
        )
        
        return fig
    
    def plot_silhouette(self) -> go.Figure:
        """Plot silhouette diagram for clusters."""
        if self.labels_ is None:
            raise ValueError("No clustering performed yet.")
        
        # Exclude noise points
        mask = self.labels_ != -1
        if mask.sum() < 10:
            print("Not enough non-noise points for silhouette plot")
            return go.Figure()
        
        sample_silhouettes = silhouette_samples(self.X[mask], self.labels_[mask])
        
        fig = go.Figure()
        
        y_lower = 0
        for cluster in sorted(set(self.labels_[mask])):
            cluster_silhouettes = sample_silhouettes[self.labels_[mask] == cluster]
            cluster_silhouettes.sort()
            
            size_cluster = len(cluster_silhouettes)
            y_upper = y_lower + size_cluster
            
            color = self.get_cluster_color(cluster)
            
            fig.add_trace(go.Scatter(
                x=cluster_silhouettes,
                y=list(range(y_lower, y_upper)),
                mode='lines',
                fill='tozerox',
                name=f'Cluster {cluster}',
                line=dict(color=color)
            ))
            
            y_lower = y_upper + 10
        
        # Add average line
        fig.add_vline(x=self.silhouette_, line_dash="dash", line_color="red",
                     annotation_text=f"Avg: {self.silhouette_:.3f}")
        
        fig.update_layout(
            title='Silhouette Plot',
            xaxis_title='Silhouette Coefficient',
            yaxis_title='Cluster',
            height=500
        )
        
        return fig
    
    def get_cluster_profiles(self) -> pd.DataFrame:
        """
        Get feature profiles for each cluster.
        
        Returns:
        --------
        pd.DataFrame
            Mean feature values per cluster
        """
        if self.labels_ is None:
            raise ValueError("No clustering performed yet.")
        
        df_with_labels = self.df.copy()
        df_with_labels['cluster'] = self.labels_
        
        profiles = df_with_labels.groupby('cluster')[self.features].mean()
        profiles['count'] = df_with_labels.groupby('cluster').size()
        profiles['percentage'] = profiles['count'] / len(df_with_labels) * 100
        
        return profiles
    
    def plot_cluster_radar(self, cluster: int = 0) -> go.Figure:
        """
        Plot radar chart for a specific cluster's feature profile.
        
        Parameters:
        -----------
        cluster : int
            Cluster index
            
        Returns:
        --------
        go.Figure
        """
        profiles = self.get_cluster_profiles()
        
        # Normalize profiles for radar
        from sklearn.preprocessing import MinMaxScaler
        scaler = MinMaxScaler()
        normalized = pd.DataFrame(
            scaler.fit_transform(profiles[self.features]),
            columns=self.features,
            index=profiles.index
        )
        
        values = normalized.loc[cluster].values
        values = np.append(values, values[0])  # Close the radar
        
        features = self.features + [self.features[0]]
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatterpolar(
            r=values,
            theta=features,
            fill='toself',
            name=f'Cluster {cluster}',
            line_color=self.get_cluster_color(cluster)
        ))
        
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            title=f'Cluster {cluster} Profile (n={int(profiles.loc[cluster, "count"])})',
            height=500
        )
        
        return fig
    
    def get_metrics(self) -> Dict:
        """Get all clustering metrics."""
        if self.labels_ is None:
            return {}
        
        mask = self.labels_ != -1
        
        metrics = {
            'method': self.method_,
            'n_clusters': self.n_clusters_,
            'silhouette': self.silhouette_,
            'n_samples': len(self.labels_),
            'n_noise': (self.labels_ == -1).sum()
        }
        
        if mask.sum() > 1:
            metrics['calinski_harabasz'] = calinski_harabasz_score(self.X[mask], self.labels_[mask])
            metrics['davies_bouldin'] = davies_bouldin_score(self.X[mask], self.labels_[mask])
        
        if hasattr(self.model_, 'inertia_'):
            metrics['inertia'] = self.model_.inertia_
        
        return metrics
