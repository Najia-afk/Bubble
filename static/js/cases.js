// static/js/cases.js
// Cases page — AML investigation skill panel, CRUD, and table rendering.

// ── State ──────────────────────────────────────────────
let casesData = [];
let selectedCaseId = null;
let skillPollInterval = null;

const SKILL_STEPS = [
    { id: 'import',   icon: '📥', label: 'Import Case',      desc: 'Create investigation from case wallets' },
    { id: 'trace',    icon: '🔗', label: 'Trace Transfers',   desc: 'Fetch ERC20 transfers from blockchain' },
    { id: 'expand',   icon: '🕵️', label: 'Follow the Money', desc: 'Discover connected wallets via fund flows' },
    { id: 'classify', icon: '🤖', label: 'ML Classification', desc: 'Run ML models + heuristics on all wallets' },
    { id: 'assess',   icon: '⚠️', label: 'Risk Assessment',  desc: 'Score risk, detect exchanges/mixers/bridges' },
    { id: 'report',   icon: '📊', label: 'Generate Report',   desc: 'Compile investigation findings' },
];

// ── Load Cases ─────────────────────────────────────────
async function loadCases() {
    try {
        const response = await fetch('/api/cases');
        const data = await response.json();
        casesData = data.cases || [];
        updateStats(casesData);
        renderCases(casesData);
    } catch (error) {
        document.getElementById('casesContainer').innerHTML = `
            <div class="loading-spinner" style="color: var(--danger);">Error loading cases: ${error.message}</div>`;
    }
}

function updateStats(cases) {
    const total = cases.length;
    const active = cases.filter(c => c.status === 'active').length;
    const investigating = cases.filter(c => c.status === 'investigating').length;
    const totalLoss = cases.reduce((sum, c) => sum + (c.estimated_loss_usd || c.total_stolen_usd || 0), 0);
    document.getElementById('totalCases').textContent = total;
    document.getElementById('activeCases').textContent = active;
    document.getElementById('investigatingCases').textContent = investigating;
    document.getElementById('totalLoss').textContent = '$' + formatNumber(totalLoss);
}

function formatNumber(num) {
    if (num >= 1e9) return (num / 1e9).toFixed(1) + 'B';
    if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M';
    if (num >= 1e3) return (num / 1e3).toFixed(1) + 'K';
    return num.toLocaleString();
}

function formatDate(dateStr) {
    if (!dateStr) return '-';
    return new Date(dateStr).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
}

function showNotification(message, type = 'info') {
    const n = document.getElementById('notification');
    n.textContent = message;
    n.style.display = 'block';
    n.style.background = type === 'success' ? 'var(--success)' : type === 'error' ? 'var(--danger)' : 'var(--primary)';
    n.style.color = 'white';
    setTimeout(() => { n.style.display = 'none'; }, 4000);
}

// ── Render Table ───────────────────────────────────────
function renderRow(c) {
    const loss = c.estimated_loss_usd || c.total_stolen_usd;
    const lossClass = c.estimated_loss_usd ? 'estimated' : '';
    const chains = (c.chains_involved || []).slice(0, 4);
    const chainBadges = chains.map(ch => `<span class="chain-tag ${ch}">${ch}</span>`).join('');
    const extraChains = c.chains_involved && c.chains_involved.length > 4
        ? `<span class="chain-tag">+${c.chains_involved.length - 4}</span>` : '';

    return `
        <div class="case-table-cell" data-col="case" onclick="openSkillPanel('${c.case_id}')">
            <span class="case-title">${c.title}</span>
            <span class="case-id">${c.case_id}</span>
        </div>
        <div class="case-table-cell" data-col="status">
            <span class="status-badge ${c.status}">${c.status}</span>
        </div>
        <div class="case-table-cell" data-col="reported">${formatDate(c.date_reported)}</div>
        <div class="case-table-cell" data-col="attack">${c.attack_vector || '-'}</div>
        <div class="case-table-cell" data-col="chains">
            <div class="chain-tags">${chainBadges}${extraChains}</div>
        </div>
        <div class="case-table-cell" data-col="victims">
            <span class="wallet-count victims"><span class="icon">👤</span> ${c.victim_wallet_count || 0}</span>
        </div>
        <div class="case-table-cell" data-col="suspects">
            <span class="wallet-count suspects"><span class="icon">🎭</span> ${c.attacker_wallet_count || 0}</span>
        </div>
        <div class="case-table-cell" data-col="exchanges">
            <span class="wallet-count exchanges"><span class="icon">🏦</span> ${c.exchange_wallet_count || 0}</span>
        </div>
        <div class="case-table-cell" data-col="bridges">
            <span class="wallet-count bridges"><span class="icon">🌉</span> ${c.bridge_wallet_count || 0}</span>
        </div>
        <div class="case-table-cell" data-col="mixers">
            <span class="wallet-count mixers"><span class="icon">🌀</span> ${c.mixer_wallet_count || 0}</span>
        </div>
        <div class="case-table-cell" data-col="loss">
            <span class="loss-value ${lossClass}">${loss ? '$' + formatNumber(loss) : '-'}</span>
        </div>
        <div class="case-table-cell" data-col="actions">
            <div class="action-group">
                <button class="action-btn skill-btn" onclick="event.stopPropagation(); openSkillPanel('${c.case_id}')" title="Run AML Investigation">🔍 Investigate</button>
                ${c.investigation_id
                    ? `<a href="/graph?investigation_id=${c.investigation_id}" class="action-btn view-btn" onclick="event.stopPropagation()">📈 Graph</a>`
                    : ''}
            </div>
        </div>
    `;
}

function renderCases(cases) {
    const sections = [
        { key: 'active', label: '🔥 Active' },
        { key: 'investigating', label: '🔍 Investigating' },
        { key: 'monitoring', label: '👁 Monitoring' },
        { key: 'closed', label: '✓ Closed' },
        { key: 'other', label: '📋 Other' }
    ];
    const groups = {};
    sections.forEach(s => groups[s.key] = []);
    cases.forEach(c => {
        const status = c.status || 'other';
        (groups[status] || groups['other']).push(c);
    });

    document.getElementById('casesContainer').innerHTML = sections.map(section => {
        const items = groups[section.key] || [];
        if (items.length === 0) return '';
        return `
            <div class="case-section">
                <div class="case-section-header">
                    <div class="case-section-title">${section.label} <span class="case-section-count">${items.length}</span></div>
                </div>
                <div class="case-table">
                    <div class="case-table-header" data-col="case">Case</div>
                    <div class="case-table-header" data-col="status">Status</div>
                    <div class="case-table-header" data-col="reported">Reported</div>
                    <div class="case-table-header" data-col="attack">Attack Vector</div>
                    <div class="case-table-header" data-col="chains">Chains</div>
                    <div class="case-table-header" data-col="victims">Victims</div>
                    <div class="case-table-header" data-col="suspects">Suspects</div>
                    <div class="case-table-header" data-col="exchanges">CEX</div>
                    <div class="case-table-header" data-col="bridges">Bridge</div>
                    <div class="case-table-header" data-col="mixers">Mixer</div>
                    <div class="case-table-header" data-col="loss">Est. Loss</div>
                    <div class="case-table-header" data-col="actions">Actions</div>
                    ${items.map(renderRow).join('')}
                </div>
            </div>`;
    }).join('');
}

// ── Skill Panel ────────────────────────────────────────
function openSkillPanel(caseId) {
    selectedCaseId = caseId;
    document.getElementById('skillCaseId').textContent = caseId;
    document.getElementById('skillOverlay').classList.add('active');
    document.getElementById('skillPanel').classList.add('active');

    // Render initial steps
    renderSkillSteps(null);
    document.getElementById('findingsPanel').style.display = 'none';
    document.getElementById('skillGraphBtn').style.display = 'none';
    document.getElementById('skillRunBtn').disabled = false;
    document.getElementById('skillRunBtn').textContent = '▶ Run Investigation';

    // Check if there's already a run
    pollSkillStatus();
}

function closeSkillPanel() {
    document.getElementById('skillOverlay').classList.remove('active');
    document.getElementById('skillPanel').classList.remove('active');
    if (skillPollInterval) { clearInterval(skillPollInterval); skillPollInterval = null; }
    selectedCaseId = null;
}

function renderSkillSteps(state) {
    const container = document.getElementById('skillSteps');
    container.innerHTML = SKILL_STEPS.map((step, i) => {
        const stepState = state?.steps?.[step.id] || { status: 'pending' };
        const statusClass = stepState.status;
        const indicator = statusClass === 'completed' ? '✓'
            : statusClass === 'running' ? '◉'
            : statusClass === 'failed' ? '✕'
            : (i + 1);

        let resultHtml = '';
        if (stepState.result?.message) {
            resultHtml = `<div class="step-result">${stepState.result.message}</div>`;
        }
        if (stepState.error) {
            resultHtml = `<div class="step-error">Error: ${stepState.error}</div>`;
        }

        let timeHtml = '';
        if (stepState.elapsed_seconds) {
            timeHtml = `<div class="step-time">${stepState.elapsed_seconds}s</div>`;
        }

        return `
            <div class="skill-step ${statusClass}">
                <div class="step-indicator">${indicator}</div>
                <div class="step-content">
                    <div class="step-label">${step.icon} ${step.label}</div>
                    <div class="step-desc">${step.desc}</div>
                    ${resultHtml}
                    ${timeHtml}
                </div>
            </div>`;
    }).join('');
}

function renderFindings(state) {
    if (!state?.findings || Object.keys(state.findings).length === 0) return;

    const f = state.findings;
    const riskClass = (f.risk_label || '').toLowerCase();
    const panel = document.getElementById('findingsPanel');
    panel.style.display = 'block';

    document.getElementById('findingsContent').innerHTML = `
        <div class="findings-grid">
            <div class="finding-item">
                <div class="finding-label">Total Wallets</div>
                <div class="finding-value">${f.total_wallets || 0}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Transfers Fetched</div>
                <div class="finding-value">${(f.transfers_fetched || 0).toLocaleString()}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Trace Depth</div>
                <div class="finding-value">${f.trace_depth || 0} hops</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Wallets Discovered</div>
                <div class="finding-value">${f.wallets_discovered || 0}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Exchanges Found</div>
                <div class="finding-value" style="color: var(--info)">${f.exchange_count || 0}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Mixers Detected</div>
                <div class="finding-value" style="color: var(--warning)">${f.mixer_count || 0}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Bridges Used</div>
                <div class="finding-value" style="color: #a855f7">${f.bridge_count || 0}</div>
            </div>
            <div class="finding-item">
                <div class="finding-label">Flagged Wallets</div>
                <div class="finding-value" style="color: var(--danger)">${f.flagged_wallets || 0}</div>
            </div>
        </div>

        <div class="risk-meter">
            <div style="display:flex; justify-content:space-between; margin-bottom:0.3rem;">
                <span style="font-size:0.75rem; font-weight:600; color:var(--text-primary);">Risk Score</span>
                <span style="font-size:0.85rem; font-weight:700; color:${riskClass === 'critical' ? '#ef4444' : riskClass === 'high' ? '#f59e0b' : riskClass === 'medium' ? '#eab308' : '#22c55e'};">
                    ${f.risk_label || '—'} (${f.risk_score || 0}/100)
                </span>
            </div>
            <div class="risk-bar-bg">
                <div class="risk-bar-fill ${riskClass}" style="width: ${f.risk_score || 0}%"></div>
            </div>
            <div class="risk-label-row">
                <span style="color: #22c55e">LOW</span>
                <span style="color: #eab308">MEDIUM</span>
                <span style="color: #f59e0b">HIGH</span>
                <span style="color: #ef4444">CRITICAL</span>
            </div>
        </div>

        ${f.classification ? `
        <div style="margin-top:1rem;">
            <div style="font-size:0.7rem; color:var(--text-muted); text-transform:uppercase; margin-bottom:0.4rem;">Classification Breakdown</div>
            <div style="display:flex; flex-wrap:wrap; gap:0.35rem;">
                ${Object.entries(f.classification).map(([k, v]) => `
                    <span style="padding:0.2rem 0.5rem; border-radius:4px; font-size:0.65rem; font-weight:600;
                           background:rgba(99,102,241,0.1); border:1px solid rgba(99,102,241,0.2); color:var(--text-primary);">
                        ${k}: ${v}
                    </span>`).join('')}
            </div>
        </div>` : ''}
    `;
}

// ── Skill Execution ────────────────────────────────────
async function runSkill() {
    if (!selectedCaseId) return;

    const maxDepth = parseInt(document.getElementById('skillMaxDepth').value) || 3;
    const maxWallets = parseInt(document.getElementById('skillMaxWallets').value) || 100;

    const btn = document.getElementById('skillRunBtn');
    btn.disabled = true;
    btn.textContent = '⏳ Launching...';

    try {
        const response = await fetch(`/api/cases/${selectedCaseId}/run-skill`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_depth: maxDepth, max_wallets: maxWallets })
        });
        const data = await response.json();

        if (response.ok) {
            showNotification(`Investigation skill launched for ${selectedCaseId}`, 'success');
            btn.textContent = '◉ Running...';
            startPolling();
        } else {
            showNotification(`Failed: ${data.error}`, 'error');
            btn.disabled = false;
            btn.textContent = '▶ Run Investigation';
        }
    } catch (error) {
        showNotification(`Error: ${error.message}`, 'error');
        btn.disabled = false;
        btn.textContent = '▶ Run Investigation';
    }
}

function startPolling() {
    if (skillPollInterval) clearInterval(skillPollInterval);
    skillPollInterval = setInterval(pollSkillStatus, 3000);
}

async function pollSkillStatus() {
    if (!selectedCaseId) return;

    try {
        const response = await fetch(`/api/cases/${selectedCaseId}/skill-status`);
        const state = await response.json();

        if (state.status === 'none') {
            renderSkillSteps(null);
            return;
        }

        renderSkillSteps(state);

        const btn = document.getElementById('skillRunBtn');

        if (state.status === 'running' || state.status === 'queued') {
            btn.disabled = true;
            btn.textContent = '◉ Running...';
            if (!skillPollInterval) startPolling();
        } else if (state.status === 'completed') {
            btn.disabled = false;
            btn.textContent = '↻ Re-run Investigation';
            if (skillPollInterval) { clearInterval(skillPollInterval); skillPollInterval = null; }

            renderFindings(state);

            if (state.investigation_id) {
                const graphBtn = document.getElementById('skillGraphBtn');
                graphBtn.style.display = 'block';
                graphBtn.onclick = () => window.location.href = `/graph?investigation_id=${state.investigation_id}`;
            }

            loadCases();
        } else if (state.status === 'failed') {
            btn.disabled = false;
            btn.textContent = '↻ Retry Investigation';
            if (skillPollInterval) { clearInterval(skillPollInterval); skillPollInterval = null; }
            renderFindings(state);
        }
    } catch (e) {
        // Silently ignore poll errors
    }
}

// ── Create Case ────────────────────────────────────────
function openCreateCaseModal() { document.getElementById('createCaseModal').classList.add('active'); }
function closeCreateCaseModal() { document.getElementById('createCaseModal').classList.remove('active'); document.getElementById('createCaseForm').reset(); }

async function createCase(event) {
    event.preventDefault();
    const form = event.target;
    const formData = new FormData(form);

    const walletsRaw = formData.get('wallets') || '';
    const walletLines = walletsRaw.split('\n').filter(line => line.trim());
    const wallets = walletLines.map(line => {
        const parts = line.split(',').map(p => p.trim());
        return { address: parts[0] || '', chain_code: parts[1] || 'ETH', role: parts[2] || 'related', label: parts[3] || '' };
    }).filter(w => w.address);

    const payload = {
        case_id: formData.get('case_id'),
        title: formData.get('title'),
        source: formData.get('source'),
        status: formData.get('status'),
        severity: formData.get('severity'),
        date_reported: formData.get('date_reported') || null,
        date_incident: formData.get('date_incident') || null,
        total_stolen_usd: parseFloat(formData.get('total_stolen_usd')) || null,
        attack_vector: formData.get('attack_vector') || null,
        victim_count: parseInt(formData.get('victim_count')) || null,
        summary: formData.get('summary') || null,
        wallets
    };

    try {
        const response = await fetch('/api/cases', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (response.ok) {
            showNotification('Case created: ' + data.case_id, 'success');
            closeCreateCaseModal();
            loadCases();
        } else {
            showNotification('Error: ' + data.error, 'error');
        }
    } catch (error) {
        showNotification('Error: ' + error.message, 'error');
    }
}

function refreshCases() { loadCases(); showNotification('Refreshing cases...', 'info'); }

// ── Init ───────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', loadCases);
document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && selectedCaseId) closeSkillPanel();
});
