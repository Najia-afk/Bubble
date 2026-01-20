// Dashboard JavaScript

let activeTasks = new Map();

// Sync functions
async function syncTokens() {
    showNotification('Syncing tokens to TigerGraph...', 'info');
    
    try {
        const response = await fetch('/api/sync/tokens', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        const data = await response.json();
        
        if (response.ok) {
            activeTasks.set(data.task_id, 'Token Sync');
            monitorTask(data.task_id);
            showNotification(`Task submitted: ${data.task_id}`, 'success');
        } else {
            showNotification('Failed to start sync', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error starting sync', 'error');
    }
}

async function syncGHST() {
    showNotification('Fetching GHST transfers...', 'info');
    
    try {
        const response = await fetch('/api/sync/ghst', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({chains: ['POL', 'BASE']})
        });
        
        const data = await response.json();
        
        if (response.ok) {
            activeTasks.set(data.task_id, 'GHST Transfer Sync');
            monitorTask(data.task_id);
            showNotification(`Task submitted: ${data.task_id}`, 'success');
        } else {
            showNotification('Failed to start sync', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error starting sync', 'error');
    }
}

async function syncFull() {
    showNotification('Starting full sync...', 'info');
    
    try {
        const response = await fetch('/api/sync/full', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        
        const data = await response.json();
        
        if (response.ok) {
            activeTasks.set(data.task_id, 'Full Sync');
            monitorTask(data.task_id);
            showNotification(`Full sync started: ${data.task_id}`, 'success');
        } else {
            showNotification('Failed to start full sync', 'error');
        }
    } catch (error) {
        console.error('Error:', error);
        showNotification('Error starting full sync', 'error');
    }
}

// Monitor task status
async function monitorTask(taskId) {
    const checkInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/task_status/${taskId}`);
            const data = await response.json();
            
            updateTaskStatus(taskId, data);
            
            if (data.state === 'SUCCESS' || data.state === 'FAILURE') {
                clearInterval(checkInterval);
                activeTasks.delete(taskId);
                
                if (data.state === 'SUCCESS') {
                    showNotification(`Task ${taskId} completed successfully`, 'success');
                    refreshStats();
                } else {
                    showNotification(`Task ${taskId} failed`, 'error');
                }
            }
        } catch (error) {
            console.error('Error checking task status:', error);
            clearInterval(checkInterval);
        }
    }, 2000);
}

function updateTaskStatus(taskId, data) {
    const container = document.getElementById('task-status');
    
    if (activeTasks.size === 0) {
        container.innerHTML = '<p class="placeholder">No active tasks</p>';
        return;
    }
    
    let html = '';
    for (const [id, name] of activeTasks) {
        const status = id === taskId ? data.state : 'PENDING';
        const color = status === 'SUCCESS' ? 'var(--success)' : 
                     status === 'FAILURE' ? 'var(--danger)' : 
                     'var(--primary)';
        
        html += `
            <div style="padding: 0.5rem; margin: 0.5rem 0; background: var(--bg-dark); border-left: 3px solid ${color}; border-radius: 4px;">
                <strong>${name}</strong> <span style="color: var(--text-secondary);">(${id.substring(0, 8)}...)</span>
                <br>
                <span style="color: ${color};">${status}</span>
            </div>
        `;
    }
    
    container.innerHTML = html;
}

function showNotification(message, type = 'info') {
    // Simple notification (you can enhance this)
    console.log(`[${type.toUpperCase()}] ${message}`);
    
    // Create toast notification
    const toast = document.createElement('div');
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 1rem 1.5rem;
        background: ${type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--danger)' : 'var(--primary)'};
        color: var(--bg-dark);
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

async function refreshStats() {
    // TODO: Implement stats fetching from TigerGraph
    console.log('Refreshing stats...');
}

// Load stats on page load
document.addEventListener('DOMContentLoaded', () => {
    refreshStats();
});

// Add CSS animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from {
            transform: translateX(100%);
            opacity: 0;
        }
        to {
            transform: translateX(0);
            opacity: 1;
        }
    }
    
    @keyframes slideOut {
        from {
            transform: translateX(0);
            opacity: 1;
        }
        to {
            transform: translateX(100%);
            opacity: 0;
        }
    }
`;
document.head.appendChild(style);
