// Visualization JavaScript for Transaction Flow Graph

let network = null;
let nodes = new vis.DataSet([]);
let edges = new vis.DataSet([]);

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

// Load graph data from TigerGraph
async function loadGraph() {
    const chain = document.getElementById('chain-select').value;
    const hours = document.getElementById('time-select').value;
    const minValue = document.getElementById('min-value').value || 0;
    
    showNotification('Loading transaction graph...', 'info');
    
    try {
        // TODO: Implement actual TigerGraph query
        // For now, generate mock data
        const mockData = generateMockGraphData(chain, parseInt(hours));
        
        // Clear existing data
        nodes.clear();
        edges.clear();
        
        // Add new data
        nodes.add(mockData.nodes);
        edges.add(mockData.edges);
        
        // Update stats
        updateGraphStats(mockData);
        
        showNotification('Graph loaded successfully', 'success');
        
    } catch (error) {
        console.error('Error loading graph:', error);
        showNotification('Failed to load graph', 'error');
    }
}

// Generate mock data for demonstration
function generateMockGraphData(chain, hours) {
    const nodeCount = Math.floor(Math.random() * 30) + 20;
    const mockNodes = [];
    const mockEdges = [];
    
    // Generate nodes (wallets)
    for (let i = 0; i < nodeCount; i++) {
        const isHighVolume = Math.random() > 0.8;
        const isContract = Math.random() > 0.9;
        
        mockNodes.push({
            id: i,
            label: `0x${Math.random().toString(16).substring(2, 8)}...`,
            color: isContract ? '#51cf66' : isHighVolume ? '#ff6b6b' : '#00d4ff',
            size: isHighVolume ? 30 : isContract ? 35 : 20,
            title: `Wallet ${i}<br>Transactions: ${Math.floor(Math.random() * 100)}`
        });
    }
    
    // Generate edges (transfers)
    const edgeCount = Math.floor(nodeCount * 1.5);
    for (let i = 0; i < edgeCount; i++) {
        const from = Math.floor(Math.random() * nodeCount);
        let to = Math.floor(Math.random() * nodeCount);
        
        // Avoid self-loops
        while (to === from) {
            to = Math.floor(Math.random() * nodeCount);
        }
        
        const amount = (Math.random() * 10000).toFixed(2);
        
        mockEdges.push({
            id: i,
            from: from,
            to: to,
            value: parseFloat(amount),
            title: `${amount} GHST`,
            width: Math.min(Math.max(amount / 1000, 1), 5)
        });
    }
    
    return {
        nodes: mockNodes,
        edges: mockEdges,
        clusters: Math.floor(Math.random() * 5) + 2,
        totalVolume: mockEdges.reduce((sum, e) => sum + e.value, 0)
    };
}

function updateGraphStats(data) {
    document.getElementById('node-count').textContent = data.nodes.length;
    document.getElementById('edge-count').textContent = data.edges.length;
    document.getElementById('cluster-count').textContent = data.clusters;
    document.getElementById('graph-volume').textContent = data.totalVolume.toFixed(2) + ' GHST';
}

function showNodeDetails(nodeId) {
    const node = nodes.get(nodeId);
    const detailsDiv = document.getElementById('node-details');
    const infoDiv = document.getElementById('node-info');
    
    // Get connected edges
    const connectedEdges = network.getConnectedEdges(nodeId);
    const incomingTxs = connectedEdges.filter(edgeId => {
        const edge = edges.get(edgeId);
        return edge.to === nodeId;
    });
    const outgoingTxs = connectedEdges.filter(edgeId => {
        const edge = edges.get(edgeId);
        return edge.from === nodeId;
    });
    
    infoDiv.innerHTML = `
        <p><strong>Address:</strong> ${node.label}</p>
        <p><strong>Incoming Transactions:</strong> ${incomingTxs.length}</p>
        <p><strong>Outgoing Transactions:</strong> ${outgoingTxs.length}</p>
        <p><strong>Total Connections:</strong> ${connectedEdges.length}</p>
    `;
    
    detailsDiv.style.display = 'block';
}

async function detectClusters() {
    showNotification('Detecting transaction clusters...', 'info');
    
    try {
        // TODO: Implement actual TigerGraph cluster detection query
        setTimeout(() => {
            showNotification('Cluster detection completed', 'success');
            
            // Highlight clusters with different colors
            const clusterColors = ['#00d4ff', '#7b68ee', '#51cf66', '#ffd43b', '#ff6b6b'];
            nodes.forEach(node => {
                const clusterId = Math.floor(Math.random() * clusterColors.length);
                nodes.update({
                    id: node.id,
                    color: clusterColors[clusterId]
                });
            });
        }, 1000);
        
    } catch (error) {
        console.error('Error detecting clusters:', error);
        showNotification('Failed to detect clusters', 'error');
    }
}

function exportGraph() {
    const data = {
        nodes: nodes.get(),
        edges: edges.get(),
        timestamp: new Date().toISOString()
    };
    
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ghst-graph-${Date.now()}.json`;
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
        background: ${type === 'success' ? '#51cf66' : type === 'error' ? '#ff6b6b' : '#00d4ff'};
        color: #0a0a0a;
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
