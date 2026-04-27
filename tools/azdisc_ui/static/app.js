/**
 * Azure Discovery UI - Frontend Application
 */

let splitOverviewCache = null;

// Tab switching
function switchTab(eventOrName, maybeTabName) {
    const tabName = typeof eventOrName === 'string' ? eventOrName : maybeTabName;

    // Hide all tabs
    const tabs = document.querySelectorAll('.tab-content');
    tabs.forEach(tab => tab.classList.remove('active'));
    
    // Remove active state from all buttons
    const buttons = document.querySelectorAll('.tab-button');
    buttons.forEach(btn => btn.classList.remove('active'));
    
    // Show selected tab
    const selectedTab = document.getElementById(tabName);
    if (selectedTab) {
        selectedTab.classList.add('active');
    }

    // Mark button as active
    if (eventOrName && eventOrName.target) {
        eventOrName.target.classList.add('active');
    } else {
        const button = Array.from(document.querySelectorAll('.tab-button')).find(btn => btn.textContent.toLowerCase().includes(tabName.toLowerCase()));
        if (button) {
            button.classList.add('active');
        }
    }
}

// Config validation
async function validateConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    
    // Convert form data to config object
    const config = {
        app: formData.get('app'),
        subscriptions: formData.get('subscriptions')
            .split(',')
            .map(s => s.trim())
            .filter(s => s),
        outputDir: formData.get('outputDir'),
        seedResourceGroups: formData.get('seedResourceGroups')
            .split(',')
            .map(s => s.trim())
            .filter(s => s),
        seedEntireSubscriptions: formData.get('seedEntireSubscriptions') === 'on',
        includeRbac: formData.get('includeRbac') === 'on',
        includePolicy: formData.get('includePolicy') === 'on',
    };
    
    // Add optional features
    if (formData.get('applicationSplitEnabled') === 'on') {
        config.applicationSplit = { enabled: true };
    }
    
    if (formData.get('migrationPlanEnabled') === 'on') {
        config.migrationPlan = { enabled: true };
    }
    
    try {
        const response = await fetch('/api/config/validate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        
        const result = await response.json();
        displayValidationResult(result);
    } catch (error) {
        console.error('Validation error:', error);
        alert('Failed to validate config: ' + error.message);
    }
}

function displayValidationResult(result) {
    const resultDiv = document.getElementById('validationResult');
    const content = document.getElementById('resultContent');
    
    if (result.valid) {
        content.textContent = 'Config is VALID\n\n' + JSON.stringify(result.preview, null, 2);
        resultDiv.style.backgroundColor = '#E7F3E1';
    } else {
        content.textContent = 'Config is INVALID\n\n' + result.errors.join('\n');
        resultDiv.style.backgroundColor = '#FFE7DC';
    }
    
    resultDiv.style.display = 'block';
}

// Pipeline execution
async function startPipeline() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    
    // Convert form data to config object
    const config = {
        app: formData.get('app'),
        subscriptions: formData.get('subscriptions')
            .split(',')
            .map(s => s.trim())
            .filter(s => s),
        outputDir: formData.get('outputDir'),
        seedResourceGroups: formData.get('seedResourceGroups')
            .split(',')
            .map(s => s.trim())
            .filter(s => s),
        seedEntireSubscriptions: formData.get('seedEntireSubscriptions') === 'on',
        includeRbac: formData.get('includeRbac') === 'on',
        includePolicy: formData.get('includePolicy') === 'on',
    };

    if (formData.get('applicationSplitEnabled') === 'on') {
        config.applicationSplit = { enabled: true };
    }

    if (formData.get('migrationPlanEnabled') === 'on') {
        config.migrationPlan = { enabled: true };
    }
    
    try {
        const response = await fetch('/api/pipeline/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_data: config }),
        });
        
        const result = await response.json();
        
        if (response.ok) {
            alert('Pipeline started with run ID: ' + result.run_id);
            
            // Add to run selector
            updateRunSelectors([{ run_id: result.run_id, app: config.app, status: 'running' }], true);
            
            // Switch to pipeline tab
            switchToTab('pipeline');
            loadJobs();
        } else {
            alert('Failed to start pipeline: ' + result.detail);
        }
    } catch (error) {
        console.error('Pipeline start error:', error);
        alert('Failed to start pipeline: ' + error.message);
    }
}

// Load job list
async function loadJobs() {
    try {
        const response = await fetch('/api/pipeline/jobs');
        const result = await response.json();
        
        const jobsList = document.getElementById('jobsList');
        
        if (result.jobs.length === 0) {
            jobsList.innerHTML = '<p>No runs yet.</p>';
            updateRunSelectors([]);
            return;
        }

        updateRunSelectors(result.jobs);
        
        jobsList.innerHTML = result.jobs.map(job => `
            <div class="job-item">
                <div>
                    <strong>${job.run_id}</strong> - ${job.app}
                    <span class="job-badge ${job.status}">${job.status}</span>
                </div>
                <small>${job.created_at}</small>
                <button onclick="viewJobStatus('${job.run_id}')" style="margin-left: 10px;">Details</button>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load jobs:', error);
    }
}

async function viewJobStatus(runId) {
    try {
        const response = await fetch(`/api/pipeline/status/${runId}`);
        const result = await response.json();
        
        const statusPanel = document.getElementById('jobStatusPanel');
        const content = document.getElementById('statusContent');
        
        content.textContent = JSON.stringify(result, null, 2);
        statusPanel.style.display = 'block';
    } catch (error) {
        alert('Failed to load status: ' + error.message);
    }
}

// Artifact browsing
async function loadArtifacts() {
    const runId = document.getElementById('runIdSelect').value;
    
    if (!runId) {
        document.getElementById('artifactsBrowser').style.display = 'none';
        return;
    }
    
    try {
        const response = await fetch(`/api/artifacts/list/${runId}`);
        const result = await response.json();
        
        const artifactsList = document.getElementById('artifactsList');
        
        if (result.artifacts.length === 0) {
            artifactsList.innerHTML = '<p>No artifacts available.</p>';
        } else {
            artifactsList.innerHTML = result.artifacts.map(artifact => `
                <div class="artifact-item">
                    <span>
                        ${artifact.type === 'dir' ? '📁' : '📄'} 
                        ${artifact.name}
                        ${artifact.size ? ` (${formatBytes(artifact.size)})` : ''}
                    </span>
                    ${artifact.type === 'file' ? `
                        <a href="/api/artifacts/download/${runId}/${artifact.path}" target="_blank">
                            Download
                        </a>
                    ` : ''}
                </div>
            `).join('');
        }
        
        document.getElementById('artifactsBrowser').style.display = 'block';
    } catch (error) {
        alert('Failed to load artifacts: ' + error.message);
    }
}

async function loadSplitAndCandidates() {
    const runId = document.getElementById('splitRunIdSelect').value;
    const splitOverview = document.getElementById('splitOverview');
    const candidatesOverview = document.getElementById('candidatesOverview');

    splitOverviewCache = null;
    splitOverview.innerHTML = '';
    candidatesOverview.innerHTML = '';

    if (!runId) {
        return;
    }

    try {
        const splitResp = await fetch(`/api/split/overview/${runId}`);
        const splitData = await splitResp.json();
        splitOverviewCache = splitData;
        renderSplitOverview(splitData, splitData.applications || []);
    } catch (error) {
        splitOverview.innerHTML = `<p class="placeholder">Failed to load split overview: ${error.message}</p>`;
    }

    try {
        const relatedResp = await fetch(`/api/candidates/related/${runId}`);
        const relatedData = await relatedResp.json();
        populateCandidateFilterOptions(relatedData);
        renderCandidatesOverview(relatedData);
    } catch (error) {
        candidatesOverview.innerHTML = `<p class="placeholder">Failed to load candidate overview: ${error.message}</p>`;
    }
}

function applySplitFilters() {
    const splitOverview = document.getElementById('splitOverview');
    if (!splitOverviewCache || !Array.isArray(splitOverviewCache.applications)) {
        splitOverview.innerHTML = '<p class="placeholder">No split overview loaded yet.</p>';
        return;
    }

    const ambiguity = document.getElementById('splitAmbiguityFilter').value;
    const minConfidenceRaw = document.getElementById('splitMinConfidence').value.trim();
    const minConfidence = minConfidenceRaw ? Number(minConfidenceRaw) : null;

    let filtered = splitOverviewCache.applications.slice();

    if (ambiguity) {
        filtered = filtered.filter(app => String(app.ambiguityLevel || '').toLowerCase() === ambiguity.toLowerCase());
    }
    if (!Number.isNaN(minConfidence) && minConfidence !== null) {
        filtered = filtered.filter(app => Number(app.confidence || 0) >= minConfidence);
    }

    renderSplitOverview(splitOverviewCache, filtered);
}

async function applyCandidateFilters() {
    const runId = document.getElementById('splitRunIdSelect').value;
    if (!runId) {
        alert('Choose a run first.');
        return;
    }

    const query = document.getElementById('candidateQuery').value.trim();
    const typeFilter = document.getElementById('candidateTypeFilter').value;
    const termFilter = document.getElementById('candidateTermFilter').value;
    const evidenceFilter = document.getElementById('candidateEvidenceFieldFilter').value;

    const payload = {
        query,
        resourceTypes: typeFilter ? [typeFilter] : [],
        matchedTerms: termFilter ? [termFilter] : [],
        evidenceFields: evidenceFilter ? [evidenceFilter] : [],
        limit: 300,
    };

    try {
        const response = await fetch(`/api/candidates/filter/${runId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();
        renderCandidatesFilterResult(result);
    } catch (error) {
        document.getElementById('candidatesOverview').innerHTML = `<p class="placeholder">Failed to filter candidates: ${error.message}</p>`;
    }
}

async function loadMigrationAndArm() {
    const runId = document.getElementById('migrationRunIdSelect').value;
    const migrationOverview = document.getElementById('migrationOverview');
    const armDeployments = document.getElementById('armDeployments');
    const armSearchResults = document.getElementById('armSearchResults');

    migrationOverview.innerHTML = '';
    armDeployments.innerHTML = '';
    armSearchResults.innerHTML = '';

    if (!runId) {
        return;
    }

    try {
        const response = await fetch(`/api/migration/overview/${runId}`);
        const result = await response.json();
        renderMigrationOverview(result);
    } catch (error) {
        migrationOverview.innerHTML = `<p class="placeholder">Failed to load migration overview: ${error.message}</p>`;
    }

    try {
        const response = await fetch(`/api/arm/deployments/${runId}`);
        const result = await response.json();
        renderArmDeployments(result);
    } catch (error) {
        armDeployments.innerHTML = `<p class="placeholder">Failed to load ARM deployments: ${error.message}</p>`;
    }
}

async function searchArmDeployments() {
    const runId = document.getElementById('migrationRunIdSelect').value;
    if (!runId) {
        alert('Choose a run first.');
        return;
    }

    const raw = document.getElementById('armKeywordSearch').value;
    const keywords = raw.split(',').map(v => v.trim()).filter(Boolean);
    if (keywords.length === 0) {
        alert('Add at least one keyword.');
        return;
    }

    try {
        const response = await fetch(`/api/arm/search/${runId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ keywords, limit: 200 }),
        });
        const result = await response.json();
        renderArmSearchResults(result);
    } catch (error) {
        document.getElementById('armSearchResults').innerHTML = `<p class="placeholder">Search failed: ${error.message}</p>`;
    }
}

function renderSplitOverview(data, applications) {
    const target = document.getElementById('splitOverview');
    if (!data || !data.available) {
        target.innerHTML = '<p class="placeholder">Split overview not available for this run.</p>';
        return;
    }

    if (!applications || applications.length === 0) {
        target.innerHTML = '<p class="placeholder">No applications match the current split filters.</p>';
        return;
    }

    const rows = applications.map(app => `
        <tr>
            <td>${app.name || '-'}</td>
            <td>${app.resourceCount || 0}</td>
            <td>${Number(app.confidence || 0).toFixed(2)}</td>
            <td><span class="chip ${(app.ambiguityLevel || 'low').toLowerCase()}">${app.ambiguityLevel || 'low'}</span></td>
            <td>${app.ambiguousResourceGroupCount || 0}</td>
        </tr>
    `).join('');

    target.innerHTML = `
        <div class="summary-grid">
            <div class="summary-card"><h4>Total Applications</h4><p>${data.applicationCount || 0}</p></div>
            <div class="summary-card"><h4>Displayed</h4><p>${applications.length}</p></div>
            <div class="summary-card"><h4>Report</h4><p>${data.applicationsReportPath || '-'}</p></div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Application</th><th>Resources</th><th>Confidence</th><th>Ambiguity</th><th>Ambiguous RGs</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function populateCandidateFilterOptions(data) {
    const typeSelect = document.getElementById('candidateTypeFilter');
    const termSelect = document.getElementById('candidateTermFilter');
    const evidenceSelect = document.getElementById('candidateEvidenceFieldFilter');

    const setOptions = (select, values) => {
        select.innerHTML = '<option value="">All</option>' + (values || []).map(v => `<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join('');
    };

    setOptions(typeSelect, data.filters ? data.filters.resourceTypes : []);
    setOptions(termSelect, data.filters ? data.filters.matchedTerms : []);
    setOptions(evidenceSelect, data.filters ? data.filters.evidenceFields : []);
}

function renderCandidatesOverview(data) {
    const target = document.getElementById('candidatesOverview');
    if (!data || !data.available) {
        target.innerHTML = '<p class="placeholder">Related candidates are not available for this run.</p>';
        return;
    }

    renderCandidatesTable(
        target,
        data.candidates || [],
        `Showing ${Math.min((data.candidates || []).length, data.candidateCount || 0)} of ${data.candidateCount || 0} candidates`
    );
}

function renderCandidatesFilterResult(data) {
    const target = document.getElementById('candidatesOverview');
    if (!data || !data.available) {
        target.innerHTML = '<p class="placeholder">No candidate data found.</p>';
        return;
    }

    renderCandidatesTable(
        target,
        data.candidates || [],
        `Filtered ${data.filtered || 0} of ${data.total || 0} candidates`
    );
}

function renderCandidatesTable(target, rows, caption) {
    if (!rows || rows.length === 0) {
        target.innerHTML = `<p class="placeholder">${caption}. No rows match.</p>`;
        return;
    }

    const body = rows.map(item => `
        <tr>
            <td>${escapeHtml(item.name || '-')}</td>
            <td>${escapeHtml(item.type || '-')}</td>
            <td>${escapeHtml(item.resourceGroup || '-')}</td>
            <td>${escapeHtml(item.subscriptionId || '-')}</td>
            <td>${(item.matchedSearchStrings || []).map(t => `<span class="chip">${escapeHtml(t)}</span>`).join('')}</td>
        </tr>
    `).join('');

    target.innerHTML = `
        <div class="summary-card" style="margin-bottom: 12px;"><h4>Candidate Filter Result</h4><p style="font-size: 14px; font-weight: 500;">${escapeHtml(caption)}</p></div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Type</th><th>Resource Group</th><th>Subscription</th><th>Matched Terms</th></tr></thead>
                <tbody>${body}</tbody>
            </table>
        </div>
    `;
}

function renderMigrationOverview(data) {
    const target = document.getElementById('migrationOverview');
    if (!data || !data.available) {
        target.innerHTML = '<p class="placeholder">Migration overview not available for this run.</p>';
        return;
    }

    const waveRows = (data.waves || []).map(w => `
        <tr>
            <td>${escapeHtml(w.name || '-')}</td>
            <td>${escapeHtml(w.description || '-')}</td>
            <td>${w.applicationCount || 0}</td>
        </tr>
    `).join('');

    target.innerHTML = `
        <div class="summary-grid">
            <div class="summary-card"><h4>Wave Count</h4><p>${data.waveCount || 0}</p></div>
            <div class="summary-card"><h4>Pack Count</h4><p>${data.packCount || 0}</p></div>
            <div class="summary-card"><h4>Audience</h4><p>${escapeHtml((data.summary || {}).audience || '-')}</p></div>
            <div class="summary-card"><h4>Scope</h4><p>${escapeHtml((data.summary || {}).applicationScope || '-')}</p></div>
        </div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Wave</th><th>Description</th><th>Applications</th></tr></thead>
                <tbody>${waveRows || '<tr><td colspan="3">No wave data.</td></tr>'}</tbody>
            </table>
        </div>
    `;
}

function renderArmDeployments(data) {
    const target = document.getElementById('armDeployments');
    if (!data || !data.available) {
        target.innerHTML = '<p class="placeholder">No deployment-history resources found in inventory artifacts.</p>';
        return;
    }

    const rows = (data.deployments || []).map(dep => `
        <tr>
            <td>${escapeHtml(dep.name || '-')}</td>
            <td>${escapeHtml(dep.resourceGroup || '-')}</td>
            <td>${escapeHtml(dep.subscriptionId || '-')}</td>
            <td>${escapeHtml(dep.templateLinkUri || '-')}</td>
            <td>${dep.parameterCount || 0}</td>
        </tr>
    `).join('');

    target.innerHTML = `
        <div class="summary-card" style="margin-bottom: 12px;"><h4>Deployment Records</h4><p>${data.deploymentCount || 0}</p></div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Resource Group</th><th>Subscription</th><th>Template Link</th><th>Parameters</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderArmSearchResults(data) {
    const target = document.getElementById('armSearchResults');
    if (!data || !data.available || !Array.isArray(data.results) || data.results.length === 0) {
        target.innerHTML = '<p class="placeholder">No deployment-history matches found for current keywords.</p>';
        return;
    }

    const rows = data.results.map(dep => `
        <tr>
            <td>${escapeHtml(dep.name || '-')}</td>
            <td>${(dep.matchedKeywords || []).map(k => `<span class="chip">${escapeHtml(k)}</span>`).join('')}</td>
            <td>${(dep.matchedFields || []).map(f => `<span class="chip">${escapeHtml(f)}</span>`).join('')}</td>
            <td>${renderLinkedCandidates(dep)}</td>
            <td>${escapeHtml(dep.templateLinkUri || '-')}</td>
            <td>${escapeHtml(dep.sourceInventory || '-')}</td>
        </tr>
    `).join('');

    target.innerHTML = `
        <div class="summary-card" style="margin-top: 12px; margin-bottom: 12px;"><h4>Search Matches</h4><p>${data.resultCount || 0}</p></div>
        <div class="data-table-wrap">
            <table class="data-table">
                <thead><tr><th>Deployment</th><th>Matched Keywords</th><th>Matched Fields</th><th>Linked Candidates</th><th>Template Link</th><th>Inventory Source</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

function renderLinkedCandidates(deployment) {
    const count = Number(deployment.linkedCandidateCount || 0);
    const linked = Array.isArray(deployment.linkedCandidates) ? deployment.linkedCandidates : [];

    if (count === 0 || linked.length === 0) {
        return '<span class="chip">0</span>';
    }

    const lines = linked.map(candidate => {
        const reasonText = (candidate.reasons || []).map(reason => {
            if (reason.kind === 'shared-arm-id') {
                return `shared ARM ID (${reason.count || 0})`;
            }
            if (reason.kind === 'shared-search-term') {
                return `shared term: ${(reason.terms || []).join(', ')}`;
            }
            return reason.kind || 'related';
        }).join('; ');

        return `<div><strong>${escapeHtml(candidate.name || candidate.id || 'candidate')}</strong><br><small>${escapeHtml(reasonText)}</small></div>`;
    }).join('');

    return `${lines}<div><small>Total links: ${count}</small></div>`;
}

function updateRunSelectors(jobs, appendOnly = false) {
    const selectors = ['runIdSelect', 'splitRunIdSelect', 'migrationRunIdSelect'];
    selectors.forEach(id => {
        const select = document.getElementById(id);
        if (!select) {
            return;
        }

        const current = select.value;
        const options = appendOnly ? Array.from(select.options).map(o => ({ value: o.value, text: o.textContent })) : [{ value: '', text: '-- Choose a run --' }];

        if (appendOnly) {
            options.shift();
            options.unshift({ value: '', text: '-- Choose a run --' });
        }

        jobs.forEach(job => {
            const exists = options.some(o => o.value === job.run_id);
            if (!exists) {
                options.push({ value: job.run_id, text: `${job.run_id} (${job.app || 'app'})` });
            }
        });

        select.innerHTML = options.map(o => `<option value="${escapeHtml(o.value)}">${escapeHtml(o.text)}</option>`).join('');
        if (current && options.some(o => o.value === current)) {
            select.value = current;
        }
    });
}

function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// Utility
function formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

function switchToTab(tabName) {
    const tab = document.getElementById(tabName);
    if (tab) {
        const button = Array.from(document.querySelectorAll('.tab-button'))
            .find(btn => btn.textContent.toLowerCase().includes(tabName.toLowerCase()));
        if (button) {
            button.click();
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Azure Discovery UI initialized');
    loadJobs();
});
