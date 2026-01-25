/**
 * Sankey Diagram Visualization for Fund Flow Analysis
 * 
 * This module creates D3.js-based Sankey diagrams to visualize 
 * the flow of stolen funds through various wallets and services.
 * 
 * Author: Bubble Platform Team
 */

class SankeyFlowDiagram {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        if (!this.container) {
            console.error(`Container ${containerId} not found`);
            return;
        }
        
        this.options = {
            width: options.width || this.container.clientWidth || 900,
            height: options.height || 600,
            nodeWidth: options.nodeWidth || 24,
            nodePadding: options.nodePadding || 16,
            margin: options.margin || { top: 20, right: 20, bottom: 20, left: 20 },
            ...options
        };
        
        // Color palette for different entity types
        this.colors = {
            theft_origin: '#ef4444',      // Red - stolen funds origin
            exchange: '#3b82f6',          // Blue - exchanges
            mixer: '#a855f7',             // Purple - mixers
            bridge: '#f59e0b',            // Amber - bridges
            dex: '#10b981',               // Emerald - DEXs
            smart_contract: '#6366f1',    // Indigo - contracts
            unknown: '#6b7280',           // Gray - unknown
            destination: '#22c55e'        // Green - final destination
        };
        
        this.svg = null;
        this.sankey = null;
        this.graph = null;
        
        this.init();
    }
    
    init() {
        // Create SVG
        const width = this.options.width + this.options.margin.left + this.options.margin.right;
        const height = this.options.height + this.options.margin.top + this.options.margin.bottom;
        
        this.svg = d3.select(this.container)
            .append('svg')
            .attr('width', width)
            .attr('height', height)
            .append('g')
            .attr('transform', `translate(${this.options.margin.left},${this.options.margin.top})`);
        
        // Initialize sankey generator
        this.sankey = d3.sankey()
            .nodeWidth(this.options.nodeWidth)
            .nodePadding(this.options.nodePadding)
            .extent([[0, 0], [this.options.width, this.options.height]]);
    }
    
    /**
     * Process raw transaction data into Sankey-compatible format
     */
    processTransactionData(transactions) {
        const nodes = new Map();
        const links = [];
        
        // Build nodes from transactions
        transactions.forEach(tx => {
            // Add source node
            if (!nodes.has(tx.from)) {
                nodes.set(tx.from, {
                    id: tx.from,
                    name: this.formatAddress(tx.from),
                    type: tx.from_type || 'unknown',
                    label: tx.from_label || null,
                    fullAddress: tx.from
                });
            }
            
            // Add target node
            if (!nodes.has(tx.to)) {
                nodes.set(tx.to, {
                    id: tx.to,
                    name: this.formatAddress(tx.to),
                    type: tx.to_type || 'unknown',
                    label: tx.to_label || null,
                    fullAddress: tx.to
                });
            }
            
            // Add link
            links.push({
                source: tx.from,
                target: tx.to,
                value: parseFloat(tx.value) || 1,
                token: tx.token || 'ETH',
                hash: tx.hash,
                timestamp: tx.timestamp
            });
        });
        
        // Convert to array with indices
        const nodeArray = Array.from(nodes.values());
        const nodeIndex = new Map(nodeArray.map((n, i) => [n.id, i]));
        
        const linkArray = links.map(l => ({
            ...l,
            source: nodeIndex.get(l.source),
            target: nodeIndex.get(l.target)
        }));
        
        return { nodes: nodeArray, links: linkArray };
    }
    
    /**
     * Render the Sankey diagram
     */
    render(data) {
        // Clear previous content
        this.svg.selectAll('*').remove();
        
        // Process data if needed
        if (data.transactions) {
            this.graph = this.processTransactionData(data.transactions);
        } else {
            this.graph = data;
        }
        
        // Apply sankey layout
        const { nodes, links } = this.sankey({
            nodes: this.graph.nodes.map(d => Object.assign({}, d)),
            links: this.graph.links.map(d => Object.assign({}, d))
        });
        
        // Create gradient definitions
        const defs = this.svg.append('defs');
        
        links.forEach((link, i) => {
            const gradient = defs.append('linearGradient')
                .attr('id', `gradient-${i}`)
                .attr('gradientUnits', 'userSpaceOnUse')
                .attr('x1', link.source.x1)
                .attr('x2', link.target.x0);
            
            gradient.append('stop')
                .attr('offset', '0%')
                .attr('stop-color', this.getNodeColor(link.source));
            
            gradient.append('stop')
                .attr('offset', '100%')
                .attr('stop-color', this.getNodeColor(link.target));
        });
        
        // Draw links
        const linkGroup = this.svg.append('g')
            .attr('class', 'links')
            .attr('fill', 'none')
            .attr('stroke-opacity', 0.4);
        
        const link = linkGroup.selectAll('path')
            .data(links)
            .enter()
            .append('path')
            .attr('d', d3.sankeyLinkHorizontal())
            .attr('stroke', (d, i) => `url(#gradient-${i})`)
            .attr('stroke-width', d => Math.max(1, d.width))
            .attr('class', 'sankey-link')
            .on('mouseover', (event, d) => this.showLinkTooltip(event, d))
            .on('mouseout', () => this.hideTooltip());
        
        // Draw nodes
        const nodeGroup = this.svg.append('g')
            .attr('class', 'nodes');
        
        const node = nodeGroup.selectAll('g')
            .data(nodes)
            .enter()
            .append('g')
            .attr('class', 'sankey-node')
            .attr('transform', d => `translate(${d.x0},${d.y0})`)
            .on('mouseover', (event, d) => this.showNodeTooltip(event, d))
            .on('mouseout', () => this.hideTooltip())
            .on('click', (event, d) => this.onNodeClick(d));
        
        // Node rectangles
        node.append('rect')
            .attr('height', d => d.y1 - d.y0)
            .attr('width', this.sankey.nodeWidth())
            .attr('fill', d => this.getNodeColor(d))
            .attr('stroke', '#000')
            .attr('stroke-width', 1)
            .attr('rx', 3)
            .attr('ry', 3);
        
        // Node labels
        node.append('text')
            .attr('x', d => d.x0 < this.options.width / 2 ? this.sankey.nodeWidth() + 6 : -6)
            .attr('y', d => (d.y1 - d.y0) / 2)
            .attr('dy', '0.35em')
            .attr('text-anchor', d => d.x0 < this.options.width / 2 ? 'start' : 'end')
            .attr('font-size', '11px')
            .attr('fill', 'var(--text-primary, #fff)')
            .text(d => d.label || d.name);
        
        // Node value labels
        node.append('text')
            .attr('x', d => d.x0 < this.options.width / 2 ? this.sankey.nodeWidth() + 6 : -6)
            .attr('y', d => (d.y1 - d.y0) / 2 + 14)
            .attr('dy', '0.35em')
            .attr('text-anchor', d => d.x0 < this.options.width / 2 ? 'start' : 'end')
            .attr('font-size', '10px')
            .attr('fill', 'var(--text-secondary, #888)')
            .text(d => {
                const total = d.sourceLinks.reduce((acc, l) => acc + l.value, 0) || 
                             d.targetLinks.reduce((acc, l) => acc + l.value, 0);
                return total > 0 ? this.formatValue(total) : '';
            });
        
        // Add type badges
        node.append('circle')
            .attr('cx', this.sankey.nodeWidth() / 2)
            .attr('cy', -8)
            .attr('r', 6)
            .attr('fill', d => this.getNodeColor(d))
            .attr('stroke', '#fff')
            .attr('stroke-width', 1);
        
        this.nodes = node;
        this.links = link;
    }
    
    /**
     * Get color for node based on type
     */
    getNodeColor(node) {
        return this.colors[node.type] || this.colors.unknown;
    }
    
    /**
     * Format address for display
     */
    formatAddress(address) {
        if (!address || address.length < 10) return address;
        return `${address.slice(0, 6)}...${address.slice(-4)}`;
    }
    
    /**
     * Format value with units
     */
    formatValue(value) {
        if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
        if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
        if (value >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
        return value.toFixed(2);
    }
    
    /**
     * Show tooltip for node
     */
    showNodeTooltip(event, d) {
        const tooltip = this.getOrCreateTooltip();
        
        const inflow = d.targetLinks.reduce((acc, l) => acc + l.value, 0);
        const outflow = d.sourceLinks.reduce((acc, l) => acc + l.value, 0);
        
        tooltip.innerHTML = `
            <div class="sankey-tooltip-header">
                <span class="type-badge" style="background: ${this.getNodeColor(d)}">${d.type}</span>
                ${d.label ? `<strong>${d.label}</strong>` : ''}
            </div>
            <div class="sankey-tooltip-address">${d.fullAddress || d.id}</div>
            <div class="sankey-tooltip-stats">
                <div>📥 Inflow: ${this.formatValue(inflow)}</div>
                <div>📤 Outflow: ${this.formatValue(outflow)}</div>
                <div>📊 Connections: ${d.sourceLinks.length + d.targetLinks.length}</div>
            </div>
            <div class="sankey-tooltip-hint">Click to view details</div>
        `;
        
        this.positionTooltip(event, tooltip);
        tooltip.style.display = 'block';
    }
    
    /**
     * Show tooltip for link
     */
    showLinkTooltip(event, d) {
        const tooltip = this.getOrCreateTooltip();
        
        tooltip.innerHTML = `
            <div class="sankey-tooltip-header">
                <strong>Transfer</strong>
            </div>
            <div class="sankey-tooltip-transfer">
                <div>From: ${this.formatAddress(d.source.fullAddress || d.source.id)}</div>
                <div>To: ${this.formatAddress(d.target.fullAddress || d.target.id)}</div>
                <div>Amount: ${this.formatValue(d.value)} ${d.token || ''}</div>
                ${d.timestamp ? `<div>Time: ${new Date(d.timestamp).toLocaleString()}</div>` : ''}
            </div>
        `;
        
        this.positionTooltip(event, tooltip);
        tooltip.style.display = 'block';
    }
    
    /**
     * Hide tooltip
     */
    hideTooltip() {
        const tooltip = document.getElementById('sankey-tooltip');
        if (tooltip) tooltip.style.display = 'none';
    }
    
    /**
     * Get or create tooltip element
     */
    getOrCreateTooltip() {
        let tooltip = document.getElementById('sankey-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.id = 'sankey-tooltip';
            tooltip.className = 'sankey-tooltip';
            document.body.appendChild(tooltip);
        }
        return tooltip;
    }
    
    /**
     * Position tooltip near cursor
     */
    positionTooltip(event, tooltip) {
        const padding = 10;
        const x = event.pageX + padding;
        const y = event.pageY + padding;
        
        // Prevent overflow
        const rect = tooltip.getBoundingClientRect();
        const maxX = window.innerWidth - rect.width - padding;
        const maxY = window.innerHeight - rect.height - padding;
        
        tooltip.style.left = `${Math.min(x, maxX)}px`;
        tooltip.style.top = `${Math.min(y, maxY)}px`;
    }
    
    /**
     * Handle node click
     */
    onNodeClick(node) {
        // Emit custom event
        const event = new CustomEvent('sankey-node-click', { 
            detail: { node } 
        });
        this.container.dispatchEvent(event);
        
        // Default behavior: highlight connected paths
        this.highlightConnected(node);
    }
    
    /**
     * Highlight nodes and links connected to a node
     */
    highlightConnected(node) {
        const connected = new Set();
        connected.add(node.id);
        
        // Find all connected nodes
        const findConnected = (n, visited = new Set()) => {
            if (visited.has(n.id)) return;
            visited.add(n.id);
            connected.add(n.id);
            
            n.sourceLinks.forEach(l => {
                connected.add(l.target.id);
                findConnected(l.target, visited);
            });
            n.targetLinks.forEach(l => {
                connected.add(l.source.id);
                findConnected(l.source, visited);
            });
        };
        
        findConnected(node);
        
        // Update opacity
        this.nodes.attr('opacity', d => connected.has(d.id) ? 1 : 0.2);
        this.links.attr('stroke-opacity', d => 
            connected.has(d.source.id) && connected.has(d.target.id) ? 0.4 : 0.05
        );
    }
    
    /**
     * Reset highlighting
     */
    resetHighlight() {
        this.nodes.attr('opacity', 1);
        this.links.attr('stroke-opacity', 0.4);
    }
    
    /**
     * Update diagram size
     */
    resize(width, height) {
        this.options.width = width;
        this.options.height = height;
        
        const totalWidth = width + this.options.margin.left + this.options.margin.right;
        const totalHeight = height + this.options.margin.top + this.options.margin.bottom;
        
        d3.select(this.container).select('svg')
            .attr('width', totalWidth)
            .attr('height', totalHeight);
        
        this.sankey.extent([[0, 0], [width, height]]);
        
        // Re-render with current data
        if (this.graph) {
            this.render(this.graph);
        }
    }
    
    /**
     * Export as SVG
     */
    exportSVG() {
        const svgElement = this.container.querySelector('svg');
        const serializer = new XMLSerializer();
        const svgString = serializer.serializeToString(svgElement);
        
        const blob = new Blob([svgString], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `fund-flow-sankey-${Date.now()}.svg`;
        a.click();
        
        URL.revokeObjectURL(url);
    }
}


// CSS Styles for Sankey
const sankeyStyles = `
.sankey-tooltip {
    position: absolute;
    display: none;
    background: var(--card-bg, #1a1a2e);
    border: 1px solid var(--border, #333);
    border-radius: 8px;
    padding: 12px;
    font-size: 12px;
    z-index: 1000;
    max-width: 300px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.3);
}

.sankey-tooltip-header {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 8px;
}

.sankey-tooltip .type-badge {
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 10px;
    text-transform: uppercase;
    color: white;
}

.sankey-tooltip-address {
    font-family: monospace;
    font-size: 11px;
    color: var(--text-secondary, #888);
    word-break: break-all;
    margin-bottom: 8px;
}

.sankey-tooltip-stats {
    display: flex;
    flex-direction: column;
    gap: 4px;
    color: var(--text-primary, #fff);
}

.sankey-tooltip-transfer {
    display: flex;
    flex-direction: column;
    gap: 4px;
}

.sankey-tooltip-hint {
    margin-top: 8px;
    font-size: 10px;
    color: var(--text-muted, #666);
    font-style: italic;
}

.sankey-link {
    cursor: pointer;
    transition: stroke-opacity 0.2s;
}

.sankey-link:hover {
    stroke-opacity: 0.7 !important;
}

.sankey-node rect {
    cursor: pointer;
    transition: opacity 0.2s;
}

.sankey-node:hover rect {
    opacity: 0.8;
}

.sankey-legend {
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    padding: 12px;
    background: var(--bg-secondary, #111);
    border-radius: 8px;
    margin-top: 12px;
}

.sankey-legend-item {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: 11px;
}

.sankey-legend-color {
    width: 14px;
    height: 14px;
    border-radius: 3px;
}
`;

// Inject styles
if (typeof document !== 'undefined') {
    const styleEl = document.createElement('style');
    styleEl.textContent = sankeyStyles;
    document.head.appendChild(styleEl);
}


// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = SankeyFlowDiagram;
}
