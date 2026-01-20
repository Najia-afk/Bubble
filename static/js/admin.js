// Admin JavaScript - Token Management

let selectedChains = new Set();
let currentToken = null;

// Load tokens on page load
document.addEventListener('DOMContentLoaded', () => {
    loadTokens();
    setupEventListeners();
});

function setupEventListeners() {
    // Add token form
    document.getElementById('add-token-form').addEventListener('submit', handleAddToken);
    
    // Schedule form
    document.getElementById('schedule-form').addEventListener('submit', handleScheduleFetch);
    
    // Set today as max date for date inputs
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('end-date').setAttribute('max', today);
}

async function handleAddToken(e) {
    e.preventDefault();
    
    const contractAddress = document.getElementById('contract-address').value;
    const blockchain = document.getElementById('blockchain').value;
    const trigram = document.getElementById('trigram').value;
    
    showNotification('Adding token...', 'info');
    
    try {
        const response = await fetch('/api/tokens/add', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                contract_address: contractAddress,
                blockchain: blockchain,
                trigram: trigram
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification('✓ Token added successfully!', 'success');
            document.getElementById('add-token-form').reset();
            setTimeout(() => loadTokens(), 1000);
        } else {
            showNotification(`Error: ${data.error || 'Failed to add token'}`, 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error adding token', 'error');
    }
}

async function loadTokens() {
    try {
        const response = await fetch('/api/tokens/list');
        const data = await response.json();
        
        const container = document.getElementById('token-list');
        
        if (!data.tokens || data.tokens.length === 0) {
            container.innerHTML = '<p class="placeholder">No tokens registered yet. Add your first token above!</p>';
            return;
        }
        
        container.innerHTML = data.tokens.map(token => `
            <div class="token-card" onclick="selectTokenForSchedule('${token.id}', '${token.symbol}', '${token.name}', '${token.contract_address}', '${token.trigram}')">
                <h4>${token.name}</h4>
                <div class="token-symbol">${token.symbol}</div>
                <div class="token-address">${token.contract_address}</div>
                <div class="token-chain">${token.trigram}</div>
                <div style="margin-top: 1rem; font-size: 0.85rem; color: var(--text-secondary);">
                    ${token.history_tag ? '✓ Price tracked' : '○ Price not tracked'} • 
                    ${token.transfert_erc20_tag ? '✓ Transfers tracked' : '○ Transfers not tracked'}
                </div>
            </div>
        `).join('');
        
    } catch (error) {
        console.error('Error loading tokens:', error);
        document.getElementById('token-list').innerHTML = 
            '<p class="placeholder">Error loading tokens. Check console for details.</p>';
    }
}

function selectTokenForSchedule(tokenId, symbol, name, address, mainTrigram) {
    currentToken = {id: tokenId, symbol, name, address, mainTrigram};
    
    // Show schedule section
    document.getElementById('schedule-section').style.display = 'block';
    
    // Update token info
    document.getElementById('schedule-token-id').value = tokenId;
    document.getElementById('schedule-symbol').value = symbol;
    document.getElementById('schedule-token-name').textContent = `${name} (${symbol})`;
    document.getElementById('schedule-token-address').textContent = address;
    
    // Build chain selector
    const chainSelector = document.getElementById('chain-selector');
    const availableChains = [
        {code: 'ETH', name: 'Ethereum', icon: 'Ξ'},
        {code: 'BSC', name: 'BSC', icon: '🟡'},
        {code: 'POL', name: 'Polygon', icon: '🟣'},
        {code: 'BASE', name: 'Base', icon: '🔵'}
    ];
    
    chainSelector.innerHTML = availableChains.map(chain => `
        <button type="button" 
                class="chain-btn ${chain.code === mainTrigram ? 'selected' : ''}" 
                data-chain="${chain.code}"
                onclick="toggleChain(event, '${chain.code}')">
            ${chain.icon} ${chain.name}
        </button>
    `).join('');
    
    // Pre-select the token's main chain
    selectedChains.clear();
    selectedChains.add(mainTrigram);
    
    // Scroll to schedule section
    document.getElementById('schedule-section').scrollIntoView({behavior: 'smooth'});
}

function toggleChain(event, chainCode) {
    event.preventDefault();
    event.stopPropagation();
    
    const button = event.currentTarget;
    
    if (selectedChains.has(chainCode)) {
        selectedChains.delete(chainCode);
        button.classList.remove('selected');
    } else {
        selectedChains.add(chainCode);
        button.classList.add('selected');
    }
}

async function handleScheduleFetch(e) {
    e.preventDefault();
    
    if (selectedChains.size === 0) {
        showNotification('Please select at least one chain', 'error');
        return;
    }
    
    const tokenId = document.getElementById('schedule-token-id').value;
    const symbol = document.getElementById('schedule-symbol').value;
    const startDate = document.getElementById('start-date').value;
    const endDate = document.getElementById('end-date').value || new Date().toISOString().split('T')[0];
    const fetchMode = document.getElementById('fetch-mode').value;
    
    showNotification('Scheduling fetch tasks...', 'info');
    
    try {
        const response = await fetch('/api/tokens/schedule_fetch', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                token_id: tokenId,
                symbol: symbol,
                chains: Array.from(selectedChains),
                start_date: startDate,
                end_date: endDate,
                fetch_mode: fetchMode
            })
        });
        
        const data = await response.json();
        
        if (response.ok) {
            showNotification(`✓ Fetch tasks scheduled! Task ID: ${data.task_id}`, 'success');
            
            // Add to active tasks display
            addTaskToMonitor(data.task_id, symbol, selectedChains, fetchMode);
            
            // Reset form
            cancelSchedule();
            
            // Monitor the task
            monitorTask(data.task_id);
        } else {
            showNotification(`Error: ${data.error || 'Failed to schedule'}`, 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error scheduling fetch', 'error');
    }
}

function cancelSchedule() {
    document.getElementById('schedule-section').style.display = 'none';
    document.getElementById('schedule-form').reset();
    selectedChains.clear();
    currentToken = null;
}

function addTaskToMonitor(taskId, symbol, chains, mode) {
    const tasksList = document.getElementById('active-tasks');
    
    // Remove placeholder if exists
    const placeholder = tasksList.querySelector('.placeholder');
    if (placeholder) {
        placeholder.remove();
    }
    
    const taskItem = document.createElement('div');
    taskItem.className = 'task-item';
    taskItem.id = `task-${taskId}`;
    taskItem.innerHTML = `
        <div style="display: flex; justify-content: space-between; align-items: center;">
            <div>
                <strong>${symbol}</strong> - ${Array.from(chains).join(', ')}
                <br>
                <small>Mode: ${mode} • Task: ${taskId.substring(0, 8)}...</small>
            </div>
            <div>
                <span class="status-badge" style="background: var(--primary);">RUNNING</span>
            </div>
        </div>
    `;
    
    tasksList.prepend(taskItem);
}

async function monitorTask(taskId) {
    const checkInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/task_status/${taskId}`);
            const data = await response.json();
            
            const taskItem = document.getElementById(`task-${taskId}`);
            if (!taskItem) {
                clearInterval(checkInterval);
                return;
            }
            
            const statusBadge = taskItem.querySelector('.status-badge');
            
            if (data.state === 'SUCCESS') {
                clearInterval(checkInterval);
                taskItem.classList.add('success');
                statusBadge.textContent = 'SUCCESS';
                statusBadge.style.background = 'var(--success)';
                showNotification(`Task ${taskId.substring(0, 8)} completed!`, 'success');
                
                // Reload tokens to show updated tags
                setTimeout(() => loadTokens(), 1000);
            } else if (data.state === 'FAILURE') {
                clearInterval(checkInterval);
                taskItem.classList.add('error');
                statusBadge.textContent = 'FAILED';
                statusBadge.style.background = 'var(--danger)';
                showNotification(`Task ${taskId.substring(0, 8)} failed`, 'error');
            }
        } catch (error) {
            console.error('Error monitoring task:', error);
            clearInterval(checkInterval);
        }
    }, 3000);
}

function showNotification(message, type = 'info') {
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--danger)' : 'var(--primary)'};
        color: ${type === 'info' ? 'var(--bg-dark)' : 'white'};
        border-radius: 8px;
        font-weight: 600;
        z-index: 9999;
        animation: slideIn 0.3s ease-out;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
    `;
    toast.textContent = message;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}
