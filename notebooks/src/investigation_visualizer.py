"""
InvestigationVisualizer — Plotly visualizations for blockchain investigations.

Following mission7 pattern: static methods returning plotly Figure objects.
All charts are interactive, lightweight, and work in Jupyter on 16GB M4 Mac.

Usage:
    from notebooks.src.investigation_visualizer import InvestigationVisualizer as viz
    fig = viz.plot_fund_flow_timeline(transfers_df, wallets_df)
    fig.show()
"""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import Dict, List, Optional
from collections import defaultdict


class InvestigationVisualizer:
    """
    Plotly-based interactive visualizations for blockchain forensic investigations.
    All methods are @staticmethod returning go.Figure objects.
    """

    # Color palette for wallet roles
    ROLE_COLORS = {
        'attacker': '#d62728',       # Red
        'theft_origin': '#d62728',
        'suspect': '#ff7f0e',        # Orange
        'victim': '#2ca02c',         # Green
        'exchange': '#1f77b4',       # Blue
        'mixer': '#9467bd',          # Purple
        'bridge': '#8c564b',         # Brown
        'related': '#7f7f7f',        # Grey
        'normal': '#bcbd22',         # Yellow-green
        'unknown': '#c7c7c7',        # Light grey
    }

    @staticmethod
    def plot_fund_flow_timeline(
        transfers_df: pd.DataFrame,
        wallets_df: pd.DataFrame,
        title: str = "Fund Flow Timeline"
    ) -> go.Figure:
        """
        Timeline visualization: X=time, Y=grouped by jump depth level.
        Each node is a wallet, edges are transfers.
        Left=oldest transactions, Right=newest.
        
        Optimized for 16GB Mac: aggregates to max ~500 visible elements.
        
        Args:
            transfers_df: DataFrame with columns [from_address, to_address, value, timestamp, token_symbol]
            wallets_df: DataFrame with columns [address, role, depth, total_received]
        """
        if transfers_df.empty:
            fig = go.Figure()
            fig.add_annotation(text="No transfer data available", xref="paper", yref="paper",
                             x=0.5, y=0.5, showarrow=False, font_size=20)
            return fig

        # Build wallet depth mapping
        wallet_depth = {}
        wallet_role = {}
        if not wallets_df.empty:
            for _, w in wallets_df.iterrows():
                wallet_depth[w['address'].lower()] = w.get('depth', 0)
                wallet_role[w['address'].lower()] = w.get('role', 'unknown')

        # Assign depths to addresses not in wallets_df
        all_addresses = set(transfers_df['from_address'].str.lower()) | set(transfers_df['to_address'].str.lower())
        for addr in all_addresses:
            if addr not in wallet_depth:
                wallet_depth[addr] = -1  # Unknown depth
                wallet_role[addr] = 'unknown'

        # Compute first-seen time per address for X positioning
        first_seen = {}
        for _, tx in transfers_df.iterrows():
            ts = tx['timestamp']
            from_a = tx['from_address'].lower()
            to_a = tx['to_address'].lower()
            if from_a not in first_seen or ts < first_seen[from_a]:
                first_seen[from_a] = ts
            if to_a not in first_seen or ts < first_seen[to_a]:
                first_seen[to_a] = ts

        # Create figure
        fig = go.Figure()

        # === Plot edges (transfers) as lines ===
        # Limit to top transfers by value to keep it smooth
        tf_sorted = transfers_df.nlargest(min(500, len(transfers_df)), 'value') if 'value' in transfers_df.columns and len(transfers_df) > 500 else transfers_df

        for _, tx in tf_sorted.iterrows():
            from_a = tx['from_address'].lower()
            to_a = tx['to_address'].lower()
            x0 = first_seen.get(from_a, tx['timestamp'])
            x1 = first_seen.get(to_a, tx['timestamp'])
            y0 = wallet_depth.get(from_a, 0)
            y1 = wallet_depth.get(to_a, 0)
            val = tx.get('value', 0)

            fig.add_trace(go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode='lines',
                line=dict(color='rgba(100,100,100,0.15)', width=max(0.3, min(3, (val or 0) / 1000))),
                hoverinfo='text',
                text=f"{from_a[:8]}→{to_a[:8]}<br>{val:.2f} {tx.get('token_symbol', '')}",
                showlegend=False,
            ))

        # === Plot nodes (wallets) as markers ===
        for role in InvestigationVisualizer.ROLE_COLORS:
            addrs = [a for a, r in wallet_role.items() if r == role and a in first_seen]
            if not addrs:
                continue

            x_vals = [first_seen[a] for a in addrs]
            y_vals = [wallet_depth.get(a, 0) for a in addrs]
            colors = [InvestigationVisualizer.ROLE_COLORS.get(role, '#c7c7c7')] * len(addrs)
            hover = [f"{a[:12]}...<br>Role: {role}<br>Depth: {wallet_depth.get(a, '?')}" for a in addrs]

            fig.add_trace(go.Scatter(
                x=x_vals,
                y=y_vals,
                mode='markers',
                marker=dict(size=10, color=colors[0], line=dict(width=1, color='white')),
                name=f"{role} ({len(addrs)})",
                text=hover,
                hoverinfo='text',
            ))

        fig.update_layout(
            title=title,
            xaxis_title="Time (first seen)",
            yaxis_title="Jump Level (depth from seed)",
            template='plotly_white',
            height=700,
            hovermode='closest',
            yaxis=dict(dtick=1, autorange='reversed'),
            legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='left', x=0),
        )

        return fig

    @staticmethod
    def plot_role_distribution(wallets_df: pd.DataFrame) -> go.Figure:
        """Pie chart of wallet roles in the investigation."""
        if wallets_df.empty:
            return go.Figure()

        role_counts = wallets_df['role'].value_counts()
        colors = [InvestigationVisualizer.ROLE_COLORS.get(r, '#c7c7c7') for r in role_counts.index]

        fig = go.Figure(go.Pie(
            labels=role_counts.index,
            values=role_counts.values,
            marker_colors=colors,
            hole=0.4,
            textposition='inside',
            textinfo='label+value+percent',
        ))
        fig.update_layout(title="Wallet Roles Distribution", template='plotly_white', height=450)
        return fig

    @staticmethod
    def plot_depth_histogram(wallets_df: pd.DataFrame) -> go.Figure:
        """Bar chart showing how many wallets at each depth level."""
        if wallets_df.empty:
            return go.Figure()

        depth_counts = wallets_df.groupby(['depth', 'role']).size().reset_index(name='count')

        fig = go.Figure()
        for role in depth_counts['role'].unique():
            subset = depth_counts[depth_counts['role'] == role]
            fig.add_trace(go.Bar(
                x=subset['depth'],
                y=subset['count'],
                name=role,
                marker_color=InvestigationVisualizer.ROLE_COLORS.get(role, '#c7c7c7'),
            ))

        fig.update_layout(
            barmode='stack',
            title="Wallets by Jump Level (Depth)",
            xaxis_title="Depth (hops from seed)",
            yaxis_title="Number of Wallets",
            template='plotly_white',
            height=450,
        )
        return fig

    @staticmethod
    def plot_transfer_volume_over_time(transfers_df: pd.DataFrame, freq: str = 'D') -> go.Figure:
        """Line chart of daily/hourly transfer volume."""
        if transfers_df.empty:
            return go.Figure()

        df = transfers_df.copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        daily = df.set_index('timestamp').resample(freq)['value'].agg(['sum', 'count']).fillna(0)

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(go.Bar(x=daily.index, y=daily['count'], name='# Transfers', opacity=0.4), secondary_y=False)
        fig.add_trace(go.Scatter(x=daily.index, y=daily['sum'], name='Volume', line=dict(width=2, color='#d62728')), secondary_y=True)

        fig.update_layout(
            title="Transfer Activity Over Time",
            template='plotly_white',
            height=450,
            hovermode='x unified',
        )
        fig.update_yaxes(title_text="# Transfers", secondary_y=False)
        fig.update_yaxes(title_text="Total Volume", secondary_y=True)
        return fig

    @staticmethod
    def plot_top_wallets(wallets_df: pd.DataFrame, top_n: int = 20) -> go.Figure:
        """Horizontal bar chart of top wallets by total volume."""
        if wallets_df.empty:
            return go.Figure()

        df = wallets_df.copy()
        df['total_volume'] = (df.get('total_received', pd.Series(0, index=df.index)).fillna(0) +
                              df.get('total_sent', pd.Series(0, index=df.index)).fillna(0))
        df = df.nlargest(top_n, 'total_volume')
        df['short_addr'] = df['address'].str[:12] + '...'

        colors = [InvestigationVisualizer.ROLE_COLORS.get(r, '#c7c7c7') for r in df['role']]

        fig = go.Figure(go.Bar(
            x=df['total_volume'],
            y=df['short_addr'],
            orientation='h',
            marker_color=colors,
            text=df['role'],
            textposition='auto',
        ))
        fig.update_layout(
            title=f"Top {top_n} Wallets by Volume",
            xaxis_title="Total Volume",
            template='plotly_white',
            height=max(400, top_n * 25),
            yaxis=dict(autorange='reversed'),
        )
        return fig

    @staticmethod
    def plot_entity_sankey(
        edges_df: pd.DataFrame,
        wallets_df: pd.DataFrame,
        min_value: float = 0
    ) -> go.Figure:
        """
        Sankey diagram showing fund flows between entity types.
        Aggregates by role type for a high-level view.
        """
        if edges_df.empty or wallets_df.empty:
            return go.Figure()

        # Map addresses to roles
        addr_role = dict(zip(wallets_df['address'].str.lower(), wallets_df['role']))

        # Aggregate by role pairs
        role_flows = defaultdict(float)
        for _, e in edges_df.iterrows():
            from_role = addr_role.get(e['from'].lower() if 'from' in e else e.get('from_address', '').lower(), 'unknown')
            to_role = addr_role.get(e['to'].lower() if 'to' in e else e.get('to_address', '').lower(), 'unknown')
            val = float(e.get('total_value', 0) or 0)
            if val >= min_value:
                role_flows[(from_role, to_role)] += val

        if not role_flows:
            return go.Figure()

        # Build Sankey
        all_roles = sorted(set(r for pair in role_flows for r in pair))
        role_idx = {r: i for i, r in enumerate(all_roles)}
        colors = [InvestigationVisualizer.ROLE_COLORS.get(r, '#c7c7c7') for r in all_roles]

        sources = [role_idx[s] for (s, t) in role_flows]
        targets = [role_idx[t] for (s, t) in role_flows]
        values = list(role_flows.values())

        fig = go.Figure(go.Sankey(
            node=dict(pad=15, thickness=20, label=all_roles, color=colors),
            link=dict(source=sources, target=targets, value=values,
                     color=['rgba(100,100,100,0.2)'] * len(values)),
        ))
        fig.update_layout(title="Fund Flow by Entity Type (Sankey)", template='plotly_white', height=500)
        return fig

    @staticmethod
    def plot_classification_confidence(wallets_df: pd.DataFrame) -> go.Figure:
        """Scatter plot: each wallet as a point, X=features, Y=confidence, color=type."""
        # Placeholder for scores visualization — delegates to ModelVisualizer for ML-specific charts
        if wallets_df.empty:
            return go.Figure()

        fig = go.Figure()
        for role in wallets_df['role'].unique():
            subset = wallets_df[wallets_df['role'] == role]
            fig.add_trace(go.Scatter(
                x=subset.get('total_received', pd.Series(0, index=subset.index)).fillna(0),
                y=subset['depth'],
                mode='markers',
                name=role,
                marker_color=InvestigationVisualizer.ROLE_COLORS.get(role, '#c7c7c7'),
                marker_size=8,
                text=subset['address'].str[:12] + '...',
                hoverinfo='text+name',
            ))

        fig.update_layout(
            title="Wallets: Volume vs Depth",
            xaxis_title="Total Received",
            yaxis_title="Depth",
            template='plotly_white',
            height=500,
        )
        return fig
