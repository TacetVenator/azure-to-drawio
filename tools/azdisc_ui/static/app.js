/**
 * Azure Discovery UI - Frontend Application
 */

let splitOverviewCache = null;
let inventoryExplorerState = {
    offset: 0,
    limit: 100,
    lastRunId: '',
};

const QUICK_DIAGRAM_FOCUS_PRESETS = {
    'full-balanced': {
        preset: 'full',
        includeDependencies: true,
        dependencyDepth: '1',
        networkScope: 'full',
        diagramType: 'balanced',
    },
    'vm-network-immediate': {
        preset: 'vm-dependencies',
        includeDependencies: true,
        dependencyDepth: '2',
        networkScope: 'immediate-vm-network',
        diagramType: 'network',
    },
    'vm-application-interactions': {
        preset: 'vm-logicapp-integration',
        includeDependencies: true,
        dependencyDepth: '1',
        networkScope: 'full',
        diagramType: 'application',
    },
};

function parseCsv(raw) {
    return String(raw || '')
        .split(',')
        .map(v => v.trim())
        .filter(Boolean);
}

function parseDelimitedList(raw) {
    return String(raw || '')
        .split(/[\n,]/)
        .map(v => v.trim())
        .filter(Boolean);
}

function parseSeedTags(raw) {
    const pairs = String(raw || '')
        .split(/[\n,]/)
        .map(v => v.trim())
        .filter(Boolean);
    const tags = {};

    pairs.forEach(pair => {
        const separator = pair.indexOf('=');
        if (separator <= 0) {
            return;
        }
        const key = pair.slice(0, separator).trim();
        const value = pair.slice(separator + 1).trim();
        if (key && value) {
            tags[key] = value;
        }
    });

    return tags;
}

function parseOptionalInt(raw) {
    const value = String(raw || '').trim();
    if (!value) {
        return null;
    }
    const parsed = Number.parseInt(value, 10);
    return Number.isNaN(parsed) ? null : parsed;
}

function parseOptionalFloat(raw) {
    const value = String(raw || '').trim();
    if (!value) {
        return null;
    }
    const parsed = Number.parseFloat(value);
    return Number.isNaN(parsed) ? null : parsed;
}

function setIfNotNull(target, key, value) {
    if (value !== null && value !== undefined) {
        target[key] = value;
    }
}

function buildConfigFromForm(formData) {
    const config = {
        app: String(formData.get('app') || '').trim(),
        subscriptions: parseCsv(formData.get('subscriptions')),
        outputDir: String(formData.get('outputDir') || '').trim(),
        seedManagementGroups: parseCsv(formData.get('seedManagementGroups')),
        seedResourceGroups: parseCsv(formData.get('seedResourceGroups')),
        seedResourceIds: parseDelimitedList(formData.get('seedResourceIds')),
        seedTags: parseSeedTags(formData.get('seedTags')),
        seedTagKeys: parseCsv(formData.get('seedTagKeys')),
        tagFallbackToResourceGroup: formData.get('tagFallbackToResourceGroup') === 'on',
        seedEntireSubscriptions: formData.get('seedEntireSubscriptions') === 'on',
        includeRbac: formData.get('includeRbac') === 'on',
        resolvePrincipalNames: formData.get('resolvePrincipalNames') === 'on',
        includePolicy: formData.get('includePolicy') === 'on',
        includeAdvisor: formData.get('includeAdvisor') === 'on',
        includeQuota: formData.get('includeQuota') === 'on',
        includeVmDetails: formData.get('includeVmDetails') === 'on',
        enableTelemetry: formData.get('enableTelemetry') === 'on',
        layout: String(formData.get('layout') || 'SUB>REGION>RG>NET'),
        diagramMode: String(formData.get('diagramMode') || 'MSFT'),
        spacing: String(formData.get('spacing') || 'compact'),
        expandScope: String(formData.get('expandScope') || 'related'),
        inventoryGroupBy: String(formData.get('inventoryGroupBy') || 'type'),
        networkDetail: String(formData.get('networkDetail') || 'full'),
        edgeLabels: formData.get('edgeLabels') === 'on',
        subnetColors: formData.get('subnetColors') === 'on',
        groupByTag: parseCsv(formData.get('groupByTag')),
        layoutMagic: formData.get('layoutMagic') === 'on',
        deepDiscovery: {
            enabled: formData.get('deepDiscoveryEnabled') === 'on',
            searchStrings: parseDelimitedList(formData.get('deepDiscoverySearchStrings')),
            candidateFile: String(formData.get('deepDiscoveryCandidateFile') || '').trim(),
            promotedFile: String(formData.get('deepDiscoveryPromotedFile') || '').trim(),
            outputDirName: String(formData.get('deepDiscoveryOutputDirName') || '').trim(),
            extendedOutputDirName: String(formData.get('deepDiscoveryExtendedOutputDirName') || '').trim(),
        },
        applicationSplit: {
            enabled: formData.get('applicationSplitEnabled') === 'on',
            mode: String(formData.get('applicationSplitMode') || 'tag-value'),
            tagKeys: parseCsv(formData.get('applicationSplitTagKeys')),
            values: parseCsv(formData.get('applicationSplitValues')),
            includeSharedDependencies: formData.get('applicationSplitIncludeSharedDependencies') === 'on',
            outputLayout: String(formData.get('applicationSplitOutputLayout') || 'subdirs'),
        },
        migrationPlan: {
            enabled: formData.get('migrationPlanEnabled') === 'on',
            outputDir: String(formData.get('migrationPlanOutputDir') || '').trim(),
            audience: String(formData.get('migrationPlanAudience') || 'mixed'),
            applicationScope: String(formData.get('migrationPlanApplicationScope') || 'both'),
            includeCopilotPrompts: formData.get('migrationPlanIncludeCopilotPrompts') === 'on',
        },
        localAnalysis: {
            enabled: formData.get('localAnalysisEnabled') === 'on',
            provider: String(formData.get('localAnalysisProvider') || 'ollama'),
            model: String(formData.get('localAnalysisModel') || '').trim(),
            outputDir: String(formData.get('localAnalysisOutputDir') || '').trim(),
            intents: parseDelimitedList(formData.get('localAnalysisIntents')),
            packScope: String(formData.get('localAnalysisPackScope') || 'both'),
            includeArtifacts: parseCsv(formData.get('localAnalysisIncludeArtifacts')),
            keepIntermediate: formData.get('localAnalysisKeepIntermediate') === 'on',
        },
        diagramFocus: {
            preset: String(formData.get('diagramFocusPreset') || 'full'),
            resourceTypes: parseDelimitedList(formData.get('diagramFocusResourceTypes')),
            includeDependencies: formData.get('diagramFocusIncludeDeps') === 'on',
            dependencyDepth: parseInt(formData.get('diagramFocusDependencyDepth') || '1', 10),
            networkScope: String(formData.get('diagramFocusNetworkScope') || 'full'),
            diagramType: String(formData.get('diagramFocusDiagramType') || 'balanced'),
        },
    };

    setIfNotNull(config, 'telemetryLookbackDays', parseOptionalInt(formData.get('telemetryLookbackDays')));
    setIfNotNull(config.localAnalysis, 'maxContextTokens', parseOptionalInt(formData.get('localAnalysisMaxContextTokens')));
    setIfNotNull(config.localAnalysis, 'maxChunkTokens', parseOptionalInt(formData.get('localAnalysisMaxChunkTokens')));
    setIfNotNull(config.localAnalysis, 'topK', parseOptionalInt(formData.get('localAnalysisTopK')));
    setIfNotNull(config.localAnalysis, 'temperature', parseOptionalFloat(formData.get('localAnalysisTemperature')));

    return config;
}

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
        const needle = `switchTab('${tabName}')`;
        const button = Array.from(document.querySelectorAll('.tab-button')).find(btn =>
            String(btn.getAttribute('onclick') || '').includes(needle)
        );
        if (button) {
            button.classList.add('active');
        }
    }
}

// Config validation
async function validateConfig() {
    const form = document.getElementById('configForm');
    const formData = new FormData(form);
    const config = buildConfigFromForm(formData);
    
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
    const config = buildConfigFromForm(formData);
    const continueOnError = Boolean(document.getElementById('continueOnError')?.checked);
    const authMode = String(document.getElementById('authMode')?.value || 'auto').toLowerCase();
    const allowAuthorizationFallback = Boolean(document.getElementById('allowAuthorizationFallback')?.checked);
    const tokenAvailable = authMode === 'token';
    
    try {
        const response = await fetch('/api/pipeline/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                config_data: config,
                execution_options: {
                    continueOnError,
                    authMode,
                    allowAuthorizationFallback,
                    tokenAvailable,
                },
            }),
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

async function importArtifacts() {
    const app = document.getElementById('importAppName').value.trim() || 'imported-run';
    const subscriptions = parseCsv(document.getElementById('importSubscriptions').value);
    const outputDir = document.getElementById('importOutputDir').value.trim();
    const seedPath = document.getElementById('importSeedPath').value.trim();
    const inventoryPath = document.getElementById('importInventoryPath').value.trim();

    const sourceFiles = [];
    if (seedPath) {
        sourceFiles.push({ artifactType: 'seed', path: seedPath });
    }
    if (inventoryPath) {
        sourceFiles.push({ artifactType: 'inventory', path: inventoryPath });
    }

    if (sourceFiles.length === 0) {
        alert('Provide at least one local artifact path.');
        return;
    }

    const payload = {
        app,
        subscriptions,
        outputDir,
        sourceFiles,
    };

    try {
        const response = await fetch('/api/import/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const result = await response.json();

        if (!response.ok) {
            throw new Error(result.detail || 'Import failed');
        }

        const panel = document.getElementById('importResult');
        const content = document.getElementById('importResultContent');
        content.textContent = JSON.stringify(result, null, 2);
        panel.style.display = 'block';

        updateRunSelectors([{ run_id: result.run_id, app, status: result.status, source_mode: 'imported' }], true);
        switchToTab('artifacts');
        loadJobs();
    } catch (error) {
        alert('Failed to import artifacts: ' + error.message);
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
                    <span class="job-meta">${escapeHtml(job.source_mode || 'pipeline')}${job.continue_on_error ? ' | continue-on-error' : ''}${job.auth_mode_effective ? ` | auth:${escapeHtml(job.auth_mode_effective)}` : ''}${job.fallback_triggered ? ' | cli-fallback' : ''}</span>
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
        const previewPanel = document.getElementById('artifactPreviewPanel');
        const previewMedia = document.getElementById('artifactPreviewMedia');
        const previewContent = document.getElementById('artifactPreviewContent');
        previewPanel.style.display = 'none';
        if (previewMedia) {
            previewMedia.style.display = 'none';
            previewMedia.innerHTML = '';
        }
        if (previewContent) {
            previewContent.textContent = '';
        }
        
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
                        <div class="artifact-actions">
                    ` : ''}
                    ${artifact.type === 'file' && getPreviewKind(artifact.name) ? `
                        <button type="button" onclick="previewArtifact('${escapeHtml(runId)}', '${encodeArtifactPath(artifact.path)}')">Preview</button>
                    ` : ''}
                    ${artifact.type === 'file' ? `
                        <a href="/api/artifacts/download/${escapeHtml(runId)}/${encodeArtifactPath(artifact.path)}" target="_blank">
                            Download
                        </a>
                        </div>
                    ` : ''}
                </div>
            `).join('');
        }
        
        document.getElementById('artifactsBrowser').style.display = 'block';
        inventoryExplorerState.lastRunId = runId;
        inventoryExplorerState.offset = 0;
        await loadInventoryFacets();
        runInventorySearch(true);
    } catch (error) {
        alert('Failed to load artifacts: ' + error.message);
    }
}

function onInventoryArtifactChanged() {
    inventoryExplorerState.offset = 0;
    loadInventoryFacets().then(() => runInventorySearch(true));
}

async function loadInventoryFacets() {
    const runId = document.getElementById('runIdSelect').value;
    if (!runId) {
        return;
    }

    const artifact = document.getElementById('inventoryArtifactType').value;
    try {
        const response = await fetch(`/api/inventory/facets/${runId}?artifact=${encodeURIComponent(artifact)}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load inventory facets');
        }

        populateInventoryFacetSelect('inventoryTypeFilter', result.facets?.resourceTypes || []);
        populateInventoryFacetSelect('inventoryRgFilter', result.facets?.resourceGroups || []);
        populateInventoryFacetSelect('inventorySubFilter', result.facets?.subscriptions || []);
    } catch (error) {
        document.getElementById('inventorySummary').textContent = `Failed to load filter facets: ${error.message}`;
    }
}

function populateInventoryFacetSelect(selectId, values) {
    const select = document.getElementById(selectId);
    if (!select) {
        return;
    }

    const current = select.value;
    const options = ['<option value="">All</option>']
        .concat((values || []).map(value => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`));
    select.innerHTML = options.join('');
    if (current && (values || []).includes(current)) {
        select.value = current;
    }
}

async function runInventorySearch(resetOffset = false) {
    const runId = document.getElementById('runIdSelect').value;
    if (!runId) {
        return;
    }

    if (resetOffset || inventoryExplorerState.lastRunId !== runId) {
        inventoryExplorerState.offset = 0;
    }
    inventoryExplorerState.lastRunId = runId;

    const artifact = document.getElementById('inventoryArtifactType').value;
    const query = document.getElementById('inventoryQuery').value.trim();
    const resourceType = document.getElementById('inventoryTypeFilter').value.trim();
    const resourceGroup = document.getElementById('inventoryRgFilter').value.trim();
    const subscription = document.getElementById('inventorySubFilter').value.trim();
    inventoryExplorerState.limit = Number.parseInt(document.getElementById('inventoryPageSize').value, 10) || 100;

    const params = new URLSearchParams({
        artifact,
        offset: String(inventoryExplorerState.offset),
        limit: String(inventoryExplorerState.limit),
        query,
        resource_type: resourceType,
        resource_group: resourceGroup,
        subscription,
    });

    try {
        const response = await fetch(`/api/inventory/explore/${runId}?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Inventory query failed');
        }
        renderInventoryResults(result);
    } catch (error) {
        document.getElementById('inventorySummary').textContent = `Inventory query failed: ${error.message}`;
        document.getElementById('inventoryResults').innerHTML = '';
    }
}

function previousInventoryPage() {
    inventoryExplorerState.offset = Math.max(0, inventoryExplorerState.offset - inventoryExplorerState.limit);
    runInventorySearch(false);
}

function nextInventoryPage() {
    inventoryExplorerState.offset += inventoryExplorerState.limit;
    runInventorySearch(false);
}

function renderInventoryResults(result) {
    const summary = document.getElementById('inventorySummary');
    const results = document.getElementById('inventoryResults');

    const end = Math.min(result.offset + result.rows.length, result.filteredRows);
    summary.textContent =
        `Artifact: ${result.artifactPath} | Showing ${result.rows.length === 0 ? 0 : result.offset + 1}-${end} of ${result.filteredRows} filtered rows (${result.totalRows} total)`;

    if (!result.rows || result.rows.length === 0) {
        results.innerHTML = '<p class="placeholder">No rows match the current inventory filters.</p>';
        return;
    }

    const rows = result.rows.map(row => `
        <tr>
            <td>${escapeHtml(row.name || '-')}</td>
            <td>${escapeHtml(row.type || '-')}</td>
            <td>${escapeHtml(row.resourceGroup || '-')}</td>
            <td>${escapeHtml(row.subscriptionId || '-')}</td>
            <td>${escapeHtml(row.location || '-')}</td>
            <td>${escapeHtml(row.id || '-')}</td>
        </tr>
    `).join('');

    results.innerHTML = `
        <div class="data-table-wrap" style="margin-top: 10px;">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Type</th><th>Resource Group</th><th>Subscription</th><th>Location</th><th>ID</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>
        </div>
    `;
}

async function previewArtifact(runId, encodedArtifactPath) {
    try {
        const artifactPath = decodeArtifactPath(encodedArtifactPath);
        const kind = getPreviewKind(artifactPath);
        const panel = document.getElementById('artifactPreviewPanel');
        const media = document.getElementById('artifactPreviewMedia');
        const content = document.getElementById('artifactPreviewContent');

        if (media) {
            media.style.display = 'none';
            media.innerHTML = '';
        }

        if (kind === 'image' && media && content) {
            const imgSrc = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodedArtifactPath}`;
            media.innerHTML = `<img src="${imgSrc}" alt="Artifact preview">`;
            media.style.display = 'block';
            content.textContent = `Image preview: ${artifactPath}`;
            panel.style.display = 'block';
            return;
        }

        const response = await fetch(`/api/artifacts/preview/${encodeURIComponent(runId)}/${encodedArtifactPath}?limit=50`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Preview failed');
        }

        if (!content) {
            panel.style.display = 'block';
            return;
        }

        if (result.kind === 'xml') {
            const downloadUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodedArtifactPath}`;
            content.textContent =
                `XML preview (${result.lineCount || 0} lines, ${formatBytes(result.fileSize || 0)})\n` +
                `Download full file: ${downloadUrl}\n\n` +
                `${result.previewText || ''}`;
        } else {
            content.textContent = JSON.stringify(result, null, 2);
        }

        panel.style.display = 'block';
    } catch (error) {
        alert('Failed to preview artifact: ' + error.message);
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

function getPreviewKind(fileName) {
    const lower = String(fileName || '').toLowerCase();
    if (lower.endsWith('.json')) return 'json';
    if (lower.endsWith('.svg') || lower.endsWith('.png')) return 'image';
    if (lower.endsWith('.drawio') || lower.endsWith('.xml') || lower.endsWith('.mxlibrary')) return 'xml';
    return '';
}

function encodeArtifactPath(path) {
    return String(path || '')
        .split('/')
        .map(segment => encodeURIComponent(segment))
        .join('/');
}

function decodeArtifactPath(path) {
    return String(path || '')
        .split('/')
        .map(segment => decodeURIComponent(segment))
        .join('/');
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

function toggleAdvancedConfig(showAdvanced) {
    const sections = document.querySelectorAll('.advanced-section');
    sections.forEach(section => {
        if (showAdvanced) {
            section.classList.remove('hidden');
        } else {
            section.classList.add('hidden');
        }
    });
}

function updateDiagramFocusVisibility() {
    const focusPreset = document.getElementById('diagramFocusPreset');
    const focusCustomTypes = document.getElementById('diagramFocusCustomTypes');
    if (!focusPreset || !focusCustomTypes) {
        return;
    }
    focusCustomTypes.style.display = focusPreset.value === 'custom' ? '' : 'none';
}

function setActiveQuickPresetButton(activeKey) {
    const presetButtons = document.querySelectorAll('.quick-preset-btn[data-preset-key]');
    presetButtons.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.presetKey === activeKey);
    });
}

function applyQuickDiagramFocusPreset(key) {
    const presetValues = QUICK_DIAGRAM_FOCUS_PRESETS[key];
    if (!presetValues) {
        return;
    }

    const presetEl = document.getElementById('diagramFocusPreset');
    const includeDepsEl = document.getElementById('diagramFocusIncludeDeps');
    const depthEl = document.getElementById('diagramFocusDependencyDepth');
    const scopeEl = document.getElementById('diagramFocusNetworkScope');
    const diagramTypeEl = document.getElementById('diagramFocusDiagramType');

    if (presetEl) presetEl.value = presetValues.preset;
    if (includeDepsEl) includeDepsEl.checked = Boolean(presetValues.includeDependencies);
    if (depthEl) depthEl.value = String(presetValues.dependencyDepth);
    if (scopeEl) scopeEl.value = presetValues.networkScope;
    if (diagramTypeEl) diagramTypeEl.value = presetValues.diagramType;

    updateDiagramFocusVisibility();
    setActiveQuickPresetButton(key);
}

// ============================================================================
// Scenario Generation (Beta-Dumb-AI)
// ============================================================================

const scenarioTemplateTextByName = {};

function prettifyScenarioTemplateName(name) {
    return String(name || '')
        .split('-')
        .filter(Boolean)
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(' ');
}

async function hydrateScenarioTemplates() {
    const select = document.getElementById('scenarioTemplateSelect');
    if (!select) return;

    try {
        const resp = await fetch('/api/scenario/templates');
        if (!resp.ok) {
            return;
        }
        const data = await resp.json();
        const templates = Array.isArray(data.templates) ? data.templates : [];

        // Preserve the custom option while rebuilding dynamic template entries.
        select.querySelectorAll('option[data-scenario-template="1"]').forEach(opt => opt.remove());

        templates.forEach(item => {
            if (!item || typeof item.name !== 'string') return;
            const name = item.name.trim();
            if (!name) return;
            const text = typeof item.text === 'string' ? item.text : '';
            scenarioTemplateTextByName[name] = text;

            const option = document.createElement('option');
            option.value = name;
            option.dataset.scenarioTemplate = '1';
            option.textContent = prettifyScenarioTemplateName(name);
            select.appendChild(option);
        });
    } catch (e) {
        console.warn('Unable to hydrate scenario templates:', e);
    }
}

async function loadScenarioTemplate() {
    const select = document.getElementById('scenarioTemplateSelect');
    const textarea = document.getElementById('scenarioText');
    if (!select || !textarea) return;

    const templateName = select.value;
    if (!templateName) {
        return;
    }

    if (!scenarioTemplateTextByName[templateName]) {
        await hydrateScenarioTemplates();
    }

    const templateText = scenarioTemplateTextByName[templateName];
    if (templateText) {
        textarea.value = templateText;
    }

    const errEl = document.getElementById('scenarioError');
    if (errEl) {
        errEl.style.display = 'none';
        errEl.textContent = '';
    }

    const section = document.getElementById('scenarioResultSection');
    if (section) {
        section.style.display = 'none';
    }
}

async function runScenarioGenerate() {
    const textarea = document.getElementById('scenarioText');
    const select = document.getElementById('scenarioTemplateSelect');
    if (!textarea) return;

    const text = textarea.value.trim();
    const templateName = select ? select.value : '';

    if (!text && !templateName) {
        showScenarioError('Please enter a scenario description or pick a template.');
        return;
    }

    const payload = text ? { text } : { template: templateName };

    try {
        const resp = await fetch('/api/scenario/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            showScenarioResult(await resp.json());
        } else {
            const err = await resp.json().catch(() => ({}));
            showScenarioError(err.detail || 'Generation failed');
        }
    } catch (e) {
        showScenarioError('Network error: ' + e.message);
    }
}

function showScenarioResult(data) {
    const section = document.getElementById('scenarioResultSection');
    const summary = document.getElementById('scenarioParsedSummary');
    const pre = document.getElementById('scenarioGraphJson');
    const errEl = document.getElementById('scenarioError');

    if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }

    if (summary) {
        const s = data.parsed_summary || {};
        summary.textContent =
            `${s.total_nodes ?? '?'} nodes | ` +
            `${s.total_edges ?? '?'} edges | ` +
            `${s.actor_nodes ?? '?'} synthetic actors | ` +
            `${s.connections ?? '?'} connection chains`;
    }

    if (pre) {
        pre.textContent = JSON.stringify(data.graph || data, null, 2);
    }

    if (section) { section.style.display = ''; }
}

function showScenarioError(message) {
    const errEl = document.getElementById('scenarioError');
    const section = document.getElementById('scenarioResultSection');
    if (section) { section.style.display = 'none'; }
    if (errEl) {
        errEl.textContent = message;
        errEl.style.display = '';
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    console.log('Azure Discovery UI initialized');
    const toggle = document.getElementById('showAdvancedConfig');
    toggleAdvancedConfig(Boolean(toggle && toggle.checked));
    loadJobs();
    hydrateScenarioTemplates();

    // Diagram Focus: custom type visibility and quick one-click presets
    const focusPreset = document.getElementById('diagramFocusPreset');
    if (focusPreset) {
        focusPreset.addEventListener('change', () => {
            updateDiagramFocusVisibility();
            // Manual dropdown changes move away from one-click preset state.
            setActiveQuickPresetButton('');
        });
    }

    const quickPresetButtons = document.querySelectorAll('.quick-preset-btn[data-preset-key]');
    quickPresetButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            applyQuickDiagramFocusPreset(btn.dataset.presetKey || '');
        });
    });

    updateDiagramFocusVisibility();
});
