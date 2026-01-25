// Visualization JavaScript for Transaction Flow Graph
// Generalized for any token on any EVM chain - no hardcoded token references

let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);
let currentToken = 'USDT';

// Supported chains from backend config
const SUPPORTED_CHAINS = ['ETH', 'POL', 'BSC', 'BASE', 'ARB', 'OP', 'AVAX', 'FTM'];

// Initialize the network graph
function initGraph() {
    const container = document.getElementById('network-graph');
    
    const data = {
        nodes: nodes,
        edges: edges
    };
    
    const options = {
        nodes: {
            shape: 'dot',
            size: 20,
            font: {
                size: 12,
                color: '#ffffff'
            },
            borderWidth: 2,
            shadow: true
        },
        edges: {
            width: 2,
            arrows: {
                to: {
                    enabled: true,
                    scaleFactor: 0.5
                }
            },
            smooth: {
                type: 'continuous'
            },
            shadow: true,
            color: {
                color: '#666',
                highlight: '#00d4ff'
            }
        },
        physics: {
            enabled: true,
            stabilization: {
                iterations: 200
            },
            barnesHut: {
                gravitationalConstant: -8000,
                centralGravity: 0.3,
                springLength: 150,
                springConstant: 0.04
            }
        },
        interaction: {
            hover: true,
            tooltipDelay: 200
        }
    };
    
    network = new vis.Network(container, data, options);
    
    // Event listeners
    network.on('click', function(params) {
        if (params.nodes.length > 0) {
            showNodeDetails(params.nodes[0]);
        }
    });
    
    network.on('hoverNode', function(params) {
        const node = nodes.get(params.node);
        network.canvas.body.container.style.cursor = 'pointer';
    });
    
    network.on('blurNode', function() {
        network.canvas.body.container.style.cursor = 'default';
    });
}

// Load graph data from backend API
async function loadGraph() {
    const chain = document.getElementById('chain-select').value;
    const symbol = document.getElementById('token-select')?.value || 'USDT';
    const hours = document.getElementById('time-select')?.value || 24;
    const minValue = parseFloat(document.getElementById('min-value')?.value || 0);
    
    currentToken = symbol.toUpperCase();
    showNotification(`Loading ${currentToken} transfers on ${chain}...`, 'info');
    
    try {
        // Fetch real data from backend API
        const response = await fetch(`/api/graph/transfers?chain=${chain}&symbol=${symbol}&limit=500`);
        
        if (!response.ok) {
            throw new Error(`API error: ${response.status}`);
        }
        
        const data = await response.json();
        
        // Clear existing data
        nodes.clear();
        edges.clear();
        
        if (data.nodes && data.nodes.length > 0) {
            // Filter by minimum value if specified
            let filteredEdges = data.edges;
            if (minValue > 0) {
                filteredEdges = data.edges.filter(e => e.value >= minValue);
                // Also filter nodes to only include those with connections
                const connectedNodeIds = new Set();
                filteredEdges.forEach(e => {
                    connectedNodeIds.add(e.from);
                    connectedNodeIds.add(e.to);
                });
                data.nodes = data.nodes.filter(n => connectedNodeIds.has(n.id));
            }
            
            // Add data to graph
            nodes.add(data.nodes);
            edges.add(filteredEdges);
            
            // Update stats
            updateGraphStats({
                nodes: data.nodes,
                edges: filteredEdges,
                clusters: data.stats?.clusters || estimateClusters(data.nodes.length),
                totalVolume: data.stats?.total_volume || filteredEdges.reduce((sum, e) => sum + e.value, 0)
            });
            
            showNotification(`Loaded ${data.nodes.length} wallets, ${filteredEdges.length} transfers`, 'success');
        } else {
            showNotification(`No transfer data found for ${currentToken} on ${chain}`, 'warning');
            updateGraphStats({ nodes: [], edges: [], clusters: 0, totalVolume: 0 });
        }
        
    } catch (error) {
        console.error('Error loading graph:', error);
        showNotification(`Failed to load graph: ${error.message}`, 'error');
    }
}

// Estimate cluster count based on network size
function estimateClusters(nodeCount) {
    if (nodeCount < 10) return 1;
    if (nodeCount < 30) return Math.ceil(nodeCount / 10);
    return Math.ceil(Math.sqrt(nodeCount));
}

function updateGraphStats(data) {
    const nodeCountEl = document.getElementById('node-count');
    const edgeCountEl = document.getElementById('edge-count');
    const clusterCountEl = document.getElementById('cluster-count');
    const volumeEl = document.getElementById('graph-volume');
    
    if (nodeCountEl) nodeCountEl.textContent = data.nodes?.length || 0;
    if (edgeCountEl) edgeCountEl.textContent = data.edges?.length || 0;
    if (clusterCountEl) clusterCountEl.textContent = data.clusters || 0;
    if (volumeEl) volumeEl.textContent = (data.totalVolume || 0).toFixed(2) + ` ${currentToken}`;
}

function showNodeDetails(nodeId) {
    const node = nodes.get(nodeId);
    const detailsDiv = document.getElementById('node-details');
    const infoDiv = document.getElementById('node-info');
    
    if (!node || !detailsDiv || !infoDiv) return;
    
    // Get connected edges
    const connectedEdges = network.getConnectedEdges(nodeId);
    const incomingTxs = connectedEdges.filter(edgeId => {
        const edge = edges.get(edgeId);
        return edge && edge.to === nodeId;
    });
    const outgoingTxs = connectedEdges.filter(edgeId => {
        const edge = edges.get(edgeId);
        return edge && edge.from === nodeId;
    });
    
    // Calculate volumes
    let inVolume = 0, outVolume = 0;
    incomingTxs.forEach(edgeId => {
        const edge = edges.get(edgeId);
        if (edge) inVolume += edge.value || 0;
    });
    outgoingTxs.forEach(edgeId => {
        const edge = edges.get(edgeId);
        if (edge) outVolume += edge.value || 0;
    });
    
    infoDiv.innerHTML = `
        <p><strong>Address:</strong> ${node.id || node.label}</p>
        <p><strong>Incoming:</strong> ${incomingTxs.length} txs (${inVolume.toFixed(2)} ${currentToken})</p>
        <p><strong>Outgoing:</strong> ${outgoingTxs.length} txs (${outVolume.toFixed(2)} ${currentToken})</p>
        <p><strong>Net Flow:</strong> ${(inVolume - outVolume).toFixed(2)} ${currentToken}</p>
        <button onclick="investigateAddress('${node.id}')" class="btn btn-sm btn-primary mt-2">
            Investigate Address
        </button>
    `;
    
    detailsDiv.style.display = 'block';
}

// Open investigation for a specific address
async function investigateAddress(address) {
    try {
        const chain = document.getElementById('chain-select').value;
        window.location.href = `/investigations?address=${address}&chain=${chain}`;
    } catch (error) {
        showNotification('Failed to open investigation', 'error');
    }
}

async function detectClusters() {
    showNotification('Detecting transaction clusters...', 'info');
    
    try {
        // Use backend API for cluster detection if available
        const chain = document.getElementById('chain-select').value;
        const response = await fetch(`/api/graph/clusters?chain=${chain}`);
        
        if (response.ok) {
            const clusterData = await response.json();
            applyClusterColors(clusterData.clusters);
            showNotification(`Detected ${clusterData.clusters.length} clusters`, 'success');
        } else {
            // Fallback: simple client-side clustering by connectivity
            const clusterColors = ['#00d4ff', '#7b68ee', '#51cf66', '#ffd43b', '#ff6b6b', '#ff922b', '#cc5de8', '#20c997'];
            const nodeList = nodes.get();
            
            // Simple heuristic: assign colors based on connection patterns
            nodeList.forEach((node, idx) => {
                const connections = network.getConnectedEdges(node.id).length;
                const clusterId = Math.min(Math.floor(connections / 3), clusterColors.length - 1);
                nodes.update({
                    id: node.id,
                    color: clusterColors[clusterId]
                });
            });
            
            showNotification('Cluster detection completed (client-side)', 'success');
        }
        
    } catch (error) {
        console.error('Error detecting clusters:', error);
        showNotification('Cluster detection failed', 'error');
    }
}

function applyClusterColors(clusters) {
    const clusterColors = ['#00d4ff', '#7b68ee', '#51cf66', '#ffd43b', '#ff6b6b', '#ff922b', '#cc5de8', '#20c997'];
    
    clusters.forEach((cluster, idx) => {
        const color = clusterColors[idx % clusterColors.length];
        cluster.nodes.forEach(nodeId => {
            nodes.update({
                id: nodeId,
                color: color
            });
        });
    });
}

function exportGraph() {
    const data = {
        nodes: nodes.get(),
        edges: edges.get(),
        token: currentToken,
        chain: document.getElementById('chain-select')?.value || 'unknown',
        timestamp: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${currentToken}-graph-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    
    showNotification('Graph data exported', 'success');
}

function showNotification(message, type = 'info') {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? '#51cf66' : type === 'error' ? '#ff6b6b' : type === 'warning' ? '#ffd43b' : '#00d4ff'};
        color: ${type === 'warning' ? '#1a1a2e' : '#0a0a0a'};
        border-radius: 8px;
        font-weight: 600;
        z-index: 9999;
        animation: slideIn 0.3s ease-out;
    `;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initGraph();
    loadGraph();
});
