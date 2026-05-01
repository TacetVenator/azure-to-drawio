/**
 * Azure Discovery UI - Frontend Application
 */

let splitOverviewCache = null;
let inventoryExplorerState = {
    offset: 0,
    limit: 100,
    lastRunId: '',
    tagValuesByKey: {},
};
let diagramStudioState = {
    runId: '',
    diagrams: [],
};
let diagramBetaState = {
    runId: '',
    diagrams: [],
    activeIndex: -1,
    iframeReady: false,
    iframeLastEvent: '',
    viewerAvailable: false,
    viewerUrl: '',
    viewerInitTimer: null,
    viewerPendingPayload: null,
    tagValuesByKey: {},
    previewSetPaths: [],
    livePreviewEnabled: false,
    livePreviewTimer: null,
    livePreviewInFlight: false,
    livePreviewQueued: false,
    suppressLivePreview: false,
};

let resourceDiagramState = {
    offset: 0,
    limit: 100,
    totalRows: 0,
    filteredRows: 0,
    rows: [],
    selectedIds: new Set(),
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

const configPresetByName = {};
let loadedConfigPath = '';
let globalNoticeTimer = null;

function showGlobalNotice(message, isError = true, timeoutMs = 6500) {
    const host = document.getElementById('globalNotice');
    const text = String(message || '').trim();
    if (!text) {
        return;
    }

    if (!host) {
        if (isError) {
            console.error(text);
        } else {
            console.info(text);
        }
        return;
    }

    host.textContent = text;
    host.classList.remove('hidden', 'notice-error', 'notice-success');
    host.classList.add(isError ? 'notice-error' : 'notice-success');

    if (globalNoticeTimer) {
        clearTimeout(globalNoticeTimer);
        globalNoticeTimer = null;
    }
    globalNoticeTimer = setTimeout(() => {
        host.classList.add('hidden');
    }, Math.max(2000, Number(timeoutMs) || 6500));
}

function toCsv(value) {
    return Array.isArray(value) ? value.join(',') : '';
}

function toLines(value) {
    return Array.isArray(value) ? value.join('\n') : '';
}

function tagsToLines(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return '';
    }
    return Object.entries(value)
        .map(([key, val]) => `${key}=${val}`)
        .join('\n');
}

function setValueById(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.value = value;
    }
}

function setCheckedByName(name, checked) {
    const el = document.querySelector(`input[name="${name}"]`);
    if (el) {
        el.checked = Boolean(checked);
    }
}

function showConfigFileStatus(text, isError = false) {
    const el = document.getElementById('configFileStatus');
    if (!el) {
        return;
    }
    el.textContent = text || '';
    el.style.color = isError ? '#c0392b' : '#555';
}

function setLoadedConfigPath(pathValue) {
    loadedConfigPath = String(pathValue || '').trim();
    const pathInput = document.getElementById('existingConfigPath');
    if (pathInput && loadedConfigPath) {
        pathInput.value = loadedConfigPath;
    }
    const saveInput = document.getElementById('configSavePath');
    if (saveInput && !String(saveInput.value || '').trim() && loadedConfigPath) {
        if (loadedConfigPath.toLowerCase().endsWith('.json')) {
            saveInput.value = loadedConfigPath.replace(/\.json$/i, '.modified.json');
        } else {
            saveInput.value = `${loadedConfigPath}.modified.json`;
        }
    }
}

function showConfigPresetDescription(text) {
    const description = document.getElementById('configPresetDescription');
    if (!description) {
        return;
    }
    description.textContent = text || '';
}

function applyConfigObjectToForm(config) {
    const form = document.getElementById('configForm');
    if (!form || !config || typeof config !== 'object') {
        return;
    }

    form.reset();

    setValueById('appName', String(config.app || ''));
    setValueById('outputDir', String(config.outputDir || ''));
    setValueById('subscriptions', toCsv(config.subscriptions));
    setValueById('seedManagementGroups', toCsv(config.seedManagementGroups));
    setValueById('seedResourceGroups', toCsv(config.seedResourceGroups));
    setValueById('seedResourceIds', toLines(config.seedResourceIds));
    setValueById('seedTagKeys', toCsv(config.seedTagKeys));
    setValueById('seedTags', tagsToLines(config.seedTags));

    if (config.layout) setValueById('layout', String(config.layout));
    if (config.diagramMode) setValueById('diagramMode', String(config.diagramMode));
    if (config.spacing) setValueById('spacing', String(config.spacing));
    if (config.expandScope) setValueById('expandScope', String(config.expandScope));

    setCheckedByName('tagFallbackToResourceGroup', config.tagFallbackToResourceGroup);
    setCheckedByName('seedEntireSubscriptions', config.seedEntireSubscriptions);
    setCheckedByName('includeRbac', config.includeRbac);
    setCheckedByName('resolvePrincipalNames', config.resolvePrincipalNames);
    setCheckedByName('includePolicy', config.includePolicy);
    setCheckedByName('includeAdvisor', config.includeAdvisor);
    setCheckedByName('includeQuota', config.includeQuota);
    setCheckedByName('includeVmDetails', config.includeVmDetails);
    setCheckedByName('enableTelemetry', config.enableTelemetry);
    setCheckedByName('edgeLabels', config.edgeLabels);
    setCheckedByName('subnetColors', config.subnetColors);
    setCheckedByName('layoutMagic', config.layoutMagic);

    if (config.inventoryGroupBy) setValueById('inventoryGroupBy', String(config.inventoryGroupBy));
    if (config.networkDetail) setValueById('networkDetail', String(config.networkDetail));
    setValueById('groupByTag', toCsv(config.groupByTag));
    if (config.telemetryLookbackDays !== undefined && config.telemetryLookbackDays !== null) {
        setValueById('telemetryLookbackDays', String(config.telemetryLookbackDays));
    }

    const focus = config.diagramFocus;
    if (focus && typeof focus === 'object') {
        if (focus.preset) setValueById('diagramFocusPreset', String(focus.preset));
        if (focus.resourceTypes) setValueById('diagramFocusResourceTypes', toLines(focus.resourceTypes));
        const includeDepsEl = document.getElementById('diagramFocusIncludeDeps');
        if (includeDepsEl) includeDepsEl.checked = Boolean(focus.includeDependencies);
        if (focus.dependencyDepth !== undefined && focus.dependencyDepth !== null) {
            setValueById('diagramFocusDependencyDepth', String(focus.dependencyDepth));
        }
        if (focus.networkScope) setValueById('diagramFocusNetworkScope', String(focus.networkScope));
        if (focus.diagramType) setValueById('diagramFocusDiagramType', String(focus.diagramType));
    }

    const deepDiscovery = config.deepDiscovery;
    if (deepDiscovery && typeof deepDiscovery === 'object') {
        setCheckedByName('deepDiscoveryEnabled', deepDiscovery.enabled);
        setValueById('deepDiscoverySearchStrings', toLines(deepDiscovery.searchStrings));
        setValueById('deepDiscoveryCandidateFile', String(deepDiscovery.candidateFile || ''));
        setValueById('deepDiscoveryPromotedFile', String(deepDiscovery.promotedFile || ''));
        setValueById('deepDiscoveryOutputDirName', String(deepDiscovery.outputDirName || ''));
        setValueById('deepDiscoveryExtendedOutputDirName', String(deepDiscovery.extendedOutputDirName || ''));
    }

    const split = config.applicationSplit;
    if (split && typeof split === 'object') {
        setCheckedByName('applicationSplitEnabled', split.enabled);
        if (split.mode) setValueById('applicationSplitMode', String(split.mode));
        setValueById('applicationSplitTagKeys', toCsv(split.tagKeys));
        setValueById('applicationSplitValues', toCsv(split.values));
        setCheckedByName('applicationSplitIncludeSharedDependencies', split.includeSharedDependencies);
        if (split.outputLayout) setValueById('applicationSplitOutputLayout', String(split.outputLayout));
    }

    const migration = config.migrationPlan;
    if (migration && typeof migration === 'object') {
        setCheckedByName('migrationPlanEnabled', migration.enabled);
        setValueById('migrationPlanOutputDir', String(migration.outputDir || ''));
        if (migration.audience) setValueById('migrationPlanAudience', String(migration.audience));
        if (migration.applicationScope) setValueById('migrationPlanApplicationScope', String(migration.applicationScope));
        setCheckedByName('migrationPlanIncludeCopilotPrompts', migration.includeCopilotPrompts);
    }

    const local = config.localAnalysis;
    if (local && typeof local === 'object') {
        setCheckedByName('localAnalysisEnabled', local.enabled);
        if (local.provider) setValueById('localAnalysisProvider', String(local.provider));
        setValueById('localAnalysisModel', String(local.model || ''));
        setValueById('localAnalysisOutputDir', String(local.outputDir || ''));
        setValueById('localAnalysisIntents', toLines(local.intents));
        if (local.packScope) setValueById('localAnalysisPackScope', String(local.packScope));
        setValueById('localAnalysisIncludeArtifacts', toCsv(local.includeArtifacts));
        if (local.maxContextTokens !== undefined && local.maxContextTokens !== null) {
            setValueById('localAnalysisMaxContextTokens', String(local.maxContextTokens));
        }
        if (local.maxChunkTokens !== undefined && local.maxChunkTokens !== null) {
            setValueById('localAnalysisMaxChunkTokens', String(local.maxChunkTokens));
        }
        if (local.topK !== undefined && local.topK !== null) {
            setValueById('localAnalysisTopK', String(local.topK));
        }
        if (local.temperature !== undefined && local.temperature !== null) {
            setValueById('localAnalysisTemperature', String(local.temperature));
        }
        setCheckedByName('localAnalysisKeepIntermediate', local.keepIntermediate);
    }

    const showAdvancedToggle = document.getElementById('showAdvancedConfig');
    if (showAdvancedToggle) {
        showAdvancedToggle.checked = true;
        toggleAdvancedConfig(true);
    }

    updateDiagramFocusVisibility();
    setActiveQuickPresetButton('');
}

async function loadConfigFromPath() {
    const pathInput = document.getElementById('existingConfigPath');
    const configPath = String(pathInput?.value || '').trim();
    if (!configPath) {
        showConfigFileStatus('Provide a config path before loading.', true);
        return;
    }

    showConfigFileStatus(`Loading ${configPath} ...`);
    try {
        const response = await fetch('/api/config/load', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ config_path: configPath }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load config');
        }

        applyConfigObjectToForm(result.config || {});
        setLoadedConfigPath(result.config_path || configPath);
        showConfigFileStatus(`Loaded config file: ${result.config_path}. You can now edit fields and change Output Directory.`);
    } catch (error) {
        showConfigFileStatus(`Failed to load config file: ${error.message}`, true);
    }
}

async function saveConfigToPath() {
    const form = document.getElementById('configForm');
    if (!form) {
        return;
    }
    const saveInput = document.getElementById('configSavePath');
    const savePath = String(saveInput?.value || '').trim();
    if (!savePath) {
        showConfigFileStatus('Provide a target path in "Save Modified Config As".', true);
        return;
    }

    const formData = new FormData(form);
    const config = buildConfigFromForm(formData);

    showConfigFileStatus(`Saving modified config to ${savePath} ...`);
    try {
        const response = await fetch('/api/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                save_path: savePath,
                config_data: config,
                create_parent: true,
            }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to save config');
        }

        setLoadedConfigPath(result.save_path || savePath);
        showConfigFileStatus(`Saved modified config to ${result.save_path} (${result.bytes_written} bytes).`);
    } catch (error) {
        showConfigFileStatus(`Failed to save config file: ${error.message}`, true);
    }
}

async function hydrateConfigPresets() {
    const select = document.getElementById('configPresetSelect');
    if (!select) {
        return;
    }

    try {
        const response = await fetch('/api/config/presets');
        if (!response.ok) {
            return;
        }
        const payload = await response.json();
        const presets = Array.isArray(payload.presets) ? payload.presets : [];

        select.querySelectorAll('option[data-config-preset="1"]').forEach(opt => opt.remove());
        Object.keys(configPresetByName).forEach(key => delete configPresetByName[key]);

        presets.forEach(preset => {
            if (!preset || typeof preset.name !== 'string' || !preset.name.trim()) {
                return;
            }
            const name = preset.name.trim();
            configPresetByName[name] = preset;

            const option = document.createElement('option');
            option.value = name;
            option.dataset.configPreset = '1';
            option.textContent = preset.title || name;
            select.appendChild(option);
        });
    } catch (error) {
        console.warn('Unable to hydrate config presets:', error);
    }
}

function applySelectedConfigPreset() {
    const select = document.getElementById('configPresetSelect');
    if (!select) {
        return;
    }

    const selectedName = String(select.value || '').trim();
    if (!selectedName) {
        showConfigPresetDescription('');
        return;
    }

    const preset = configPresetByName[selectedName];
    if (!preset || typeof preset !== 'object') {
        showConfigPresetDescription('Selected preset is unavailable. Reload the page and try again.');
        return;
    }

    applyConfigObjectToForm(preset.config || {});
    showConfigPresetDescription(preset.description || '');
}

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

    // Stop any live status refresh when leaving the pipeline tab
    if (tabName !== 'pipeline') {
        _clearStatusRefresh();
    }

    // Auto-load split overview on tab switch if a run is selected
    if (tabName === 'split') {
        const sel = document.getElementById('splitRunIdSelect');
        if (sel && sel.value) {
            loadSplitAndCandidates();
        }
    }

    // Auto-load beta diagram list on tab switch if a run is selected
    if (tabName === 'diagram-beta') {
        const sel = document.getElementById('diagramBetaRunIdSelect');
        if (sel && sel.value) {
            loadDiagramBeta();
        }
    }

    if (tabName === 'resource-diagram') {
        const sel = document.getElementById('resourceDiagramRunIdSelect');
        if (sel && sel.value) {
            loadResourceDiagramInventory(true);
        }
    }

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
        showGlobalNotice('Failed to validate config: ' + error.message);
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
            // Add to run selector
            updateRunSelectors([{ run_id: result.run_id, app: config.app, status: 'running' }], true);

            // Switch to pipeline tab and immediately open live status
            switchToTab('pipeline');
            await loadJobs();
            viewJobStatus(result.run_id);
        } else {
            showGlobalNotice('Failed to start pipeline: ' + result.detail);
        }
    } catch (error) {
        console.error('Pipeline start error:', error);
        showGlobalNotice('Failed to start pipeline: ' + error.message);
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
        showGlobalNotice('Provide at least one local artifact path.');
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
        showGlobalNotice('Failed to import artifacts: ' + error.message);
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
    _clearStatusRefresh();
    await _refreshJobStatus(runId);
}

let _statusRefreshTimer = null;
let _statusRefreshRunId = null;

function _clearStatusRefresh() {
    if (_statusRefreshTimer) {
        clearTimeout(_statusRefreshTimer);
        _statusRefreshTimer = null;
    }
    _statusRefreshRunId = null;
}

async function _refreshJobStatus(runId) {
    try {
        const [statusResp, logsResp] = await Promise.all([
            fetch(`/api/pipeline/status/${runId}`),
            fetch(`/api/pipeline/logs/${runId}?tail=300`),
        ]);
        if (!statusResp.ok) {
            const err = await statusResp.json().catch(() => ({ detail: statusResp.statusText }));
            showGlobalNotice(`Failed to load status: ${err.detail || statusResp.statusText}`);
            return;
        }
        const result = await statusResp.json();
        const logs = logsResp.ok ? await logsResp.text() : '(logs not available)';

        _renderJobStatus(result, logs);

        if (result.status === 'running') {
            _statusRefreshRunId = runId;
            _statusRefreshTimer = setTimeout(() => _refreshJobStatus(runId), 3000);
        }
    } catch (error) {
        showGlobalNotice('Failed to load status: ' + error.message);
    }
}

function _renderJobStatus(result, logs) {
    const statusPanel = document.getElementById('jobStatusPanel');
    const content = document.getElementById('statusContent');
    const logContent = document.getElementById('logContent');
    const logDetails = document.getElementById('logDetails');

    const stageIcons = { running: '⟳', completed: '✓', failed: '✗' };

    const stageRows = (result.stages || []).map(s => {
        const icon = stageIcons[s.status] || '?';
        const errorCell = s.error ? `<span style="color:#c00;">${escapeHtml(s.error)}</span>` : '—';
        return `<tr>
            <td>${icon} ${escapeHtml(s.name)}</td>
            <td><span class="job-badge ${s.status}">${s.status}</span></td>
            <td style="font-size:11px;">${errorCell}</td>
        </tr>`;
    }).join('');

    const fallbackNote = result.fallback_triggered
        ? `<div style="background:#fff8e1;border:1px solid #f0c040;padding:6px 10px;border-radius:4px;font-size:12px;margin-bottom:8px;">
               CLI fallback triggered at stage <strong>${escapeHtml(result.fallback_stage || '?')}</strong>: ${escapeHtml(result.fallback_reason || '')}
           </div>` : '';

    const errorNote = result.error
        ? `<div style="background:#ffe0e0;border:1px solid #f08080;padding:6px 10px;border-radius:4px;font-size:12px;margin-bottom:8px;">${escapeHtml(result.error)}</div>` : '';

    const authLabel = result.auth_mode_effective && result.auth_mode_effective !== 'undefined'
        ? ` &nbsp;·&nbsp; auth: <strong>${escapeHtml(result.auth_mode_effective)}</strong>` : '';

    const refreshNote = result.status === 'running'
        ? `<p style="color:#0078D4;font-size:12px;margin-top:4px;">⟳ Auto-refreshing every 3 s…</p>` : '';

    content.innerHTML = `
        <div style="display:flex;align-items:center;gap:12px;margin-bottom:10px;flex-wrap:wrap;">
            <span class="job-badge ${result.status}" style="font-size:14px;padding:4px 10px;">${result.status}</span>
            <span style="font-size:12px;color:#555;">run: <code>${escapeHtml(result.run_id)}</code>${authLabel}</span>
        </div>
        ${fallbackNote}${errorNote}
        ${stageRows
            ? `<table class="data-table"><thead><tr><th>Stage</th><th>Status</th><th>Error</th></tr></thead><tbody>${stageRows}</tbody></table>`
            : '<p style="color:#888;font-size:13px;">No stages recorded yet.</p>'}
        ${refreshNote}
    `;

    if (logContent) {
        const atBottom = logContent.scrollHeight - logContent.scrollTop <= logContent.clientHeight + 20;
        logContent.textContent = logs || '(no log output)';
        if (atBottom || result.status === 'running') {
            logContent.scrollTop = logContent.scrollHeight;
        }
    }
    if (logDetails) {
        logDetails.open = true;
    }
    statusPanel.style.display = 'block';
}

// Artifact browsing
async function loadArtifacts() {
    const runId = document.getElementById('runIdSelect').value;
    
    if (!runId) {
        document.getElementById('artifactsBrowser').style.display = 'none';
        const panel = document.getElementById('diagramStudioPanel');
        const buttons = document.getElementById('diagramQuickButtons');
        const viewer = document.getElementById('diagramViewer');
        if (panel) panel.style.display = 'none';
        if (buttons) buttons.innerHTML = '';
        if (viewer) viewer.textContent = 'Select a run to browse diagrams.';
        diagramStudioState = { runId: '', diagrams: [] };
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
        await loadDiagramStudio();
    } catch (error) {
        showGlobalNotice('Failed to load artifacts: ' + error.message);
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
        populateInventoryFacetSelect('inventoryTagKeyFilter', result.facets?.tagKeys || []);
        inventoryExplorerState.tagValuesByKey = result.facets?.tagValuesByKey || {};
        onInventoryTagKeyChanged();
    } catch (error) {
        document.getElementById('inventorySummary').textContent = `Failed to load filter facets: ${error.message}`;
    }
}

function onInventoryTagKeyChanged() {
    const key = document.getElementById('inventoryTagKeyFilter')?.value || '';
    const values = key ? (inventoryExplorerState.tagValuesByKey[key] || []) : [];
    populateInventoryFacetSelect('inventoryTagValueFilter', values);
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
    const tagKey = document.getElementById('inventoryTagKeyFilter')?.value.trim() || '';
    const tagValue = document.getElementById('inventoryTagValueFilter')?.value.trim() || '';
    inventoryExplorerState.limit = Number.parseInt(document.getElementById('inventoryPageSize').value, 10) || 100;

    const params = new URLSearchParams({
        artifact,
        offset: String(inventoryExplorerState.offset),
        limit: String(inventoryExplorerState.limit),
        query,
        resource_type: resourceType,
        resource_group: resourceGroup,
        subscription,
        tag_key: tagKey,
        tag_value: tagValue,
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
            <td>${escapeHtml(Object.entries(row.tags || {}).map(([k, v]) => `${k}=${v}`).join(', ') || '-')}</td>
            <td>${escapeHtml(row.id || '-')}</td>
        </tr>
    `).join('');

    results.innerHTML = `
        <div class="data-table-wrap" style="margin-top: 10px;">
            <table class="data-table">
                <thead><tr><th>Name</th><th>Type</th><th>Resource Group</th><th>Subscription</th><th>Location</th><th>Tags</th><th>ID</th></tr></thead>
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
        showGlobalNotice('Failed to preview artifact: ' + error.message);
    }
}

async function loadDiagramStudio() {
    const runId = document.getElementById('runIdSelect').value;
    const panel = document.getElementById('diagramStudioPanel');
    const buttons = document.getElementById('diagramQuickButtons');
    const viewer = document.getElementById('diagramViewer');

    if (!runId || !panel || !buttons || !viewer) {
        return;
    }

    try {
        const response = await fetch(`/api/artifacts/diagrams/${encodeURIComponent(runId)}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load diagram artifacts');
        }

        const diagrams = Array.isArray(result.diagrams) ? result.diagrams : [];
        diagramStudioState = { runId, diagrams };
        panel.style.display = 'block';

        if (diagrams.length === 0) {
            buttons.innerHTML = '';
            viewer.innerHTML = '<p class="placeholder">No .drawio/.mxlibrary/.svg/.png diagram artifacts found for this run.</p>';
            return;
        }

        buttons.innerHTML = diagrams.map((diagram, index) => `
            <button type="button" onclick="previewStudioDiagram(${index})">
                ${escapeHtml(diagram.label || diagram.path || diagram.name || `diagram ${index + 1}`)}
            </button>
        `).join('');

        previewStudioDiagram(0);
    } catch (error) {
        panel.style.display = 'block';
        buttons.innerHTML = '';
        viewer.innerHTML = `<p class="placeholder">Failed to load diagrams: ${escapeHtml(error.message)}</p>`;
    }
}

async function previewStudioDiagram(index) {
    const { runId, diagrams } = diagramStudioState;
    const viewer = document.getElementById('diagramViewer');
    if (!viewer || !runId || !Array.isArray(diagrams) || index < 0 || index >= diagrams.length) {
        return;
    }

    const diagram = diagrams[index];
    const encodedPath = encodeArtifactPath(diagram.path || '');
    const downloadUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodedPath}`;
    const header = `<div class="diagram-header"><strong>${escapeHtml(diagram.label || diagram.name || diagram.path || 'diagram')}</strong> · ${escapeHtml(diagram.path || '')}</div>`;

    if (diagram.kind === 'image') {
        viewer.innerHTML = `${header}<img src="${downloadUrl}" alt="${escapeHtml(diagram.name || 'diagram preview')}">`;
        return;
    }

    try {
        const response = await fetch(`/api/artifacts/preview/${encodeURIComponent(runId)}/${encodedPath}?limit=120`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to preview draw.io artifact');
        }

        const intro = `<p class="placeholder" style="margin-bottom: 8px;">Embedded draw.io source preview. Use Download/Open to edit in your local draw.io/diagrams.net app.</p>`;
        const openLinks = `<div style="margin-bottom: 8px;"><a href="${downloadUrl}" target="_blank">Open Raw File</a></div>`;
        const xml = escapeHtml(result.previewText || '(no preview text returned)');
        viewer.innerHTML = `${header}${intro}${openLinks}<pre>${xml}</pre>`;
    } catch (error) {
        viewer.innerHTML = `${header}<p class="placeholder">Failed to preview diagram: ${escapeHtml(error.message)}</p>`;
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
        showGlobalNotice('Choose a run first.');
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
        showGlobalNotice('Choose a run first.');
        return;
    }

    const raw = document.getElementById('armKeywordSearch').value;
    const keywords = raw.split(',').map(v => v.trim()).filter(Boolean);
    if (keywords.length === 0) {
        showGlobalNotice('Add at least one keyword.');
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
    const selectors = ['runIdSelect', 'splitRunIdSelect', 'migrationRunIdSelect', 'diagramBetaRunIdSelect', 'resourceDiagramRunIdSelect'];
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

async function loadDiagramBeta() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const buttonsHost = document.getElementById('diagramBetaButtons');
    const statusEl = document.getElementById('diagramBetaStatus');
    const iframe = document.getElementById('diagramBetaIframe');
    const imageHost = document.getElementById('diagramBetaImageHost');
    const exportHost = document.getElementById('diagramBetaExportActions');
    if (!buttonsHost || !statusEl || !iframe || !imageHost) {
        return;
    }

    if (!runId) {
        diagramBetaState = {
            runId: '',
            diagrams: [],
            activeIndex: -1,
            iframeReady: diagramBetaState.iframeReady,
            iframeLastEvent: diagramBetaState.iframeLastEvent,
            viewerAvailable: diagramBetaState.viewerAvailable,
            viewerUrl: diagramBetaState.viewerUrl,
            viewerInitTimer: diagramBetaState.viewerInitTimer,
            viewerPendingPayload: diagramBetaState.viewerPendingPayload,
            tagValuesByKey: diagramBetaState.tagValuesByKey,
            previewSetPaths: [],
            livePreviewEnabled: diagramBetaState.livePreviewEnabled,
            livePreviewTimer: diagramBetaState.livePreviewTimer,
            livePreviewInFlight: diagramBetaState.livePreviewInFlight,
            livePreviewQueued: diagramBetaState.livePreviewQueued,
            suppressLivePreview: diagramBetaState.suppressLivePreview,
        };
        buttonsHost.innerHTML = '';
        if (exportHost) exportHost.innerHTML = '';
        statusEl.textContent = 'Select a run to load diagram artifacts.';
        imageHost.style.display = 'none';
        iframe.style.display = diagramBetaState.viewerAvailable ? '' : 'none';
        const scopeSelect = document.getElementById('diagramGenerateScope');
        if (scopeSelect) {
            scopeSelect.innerHTML = '<option value="">-- Choose scope --</option>';
        }
        return;
    }

    try {
        statusEl.textContent = 'Loading diagram artifacts...';
        const response = await fetch(`/api/artifacts/diagrams/${encodeURIComponent(runId)}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load diagram artifacts');
        }

        const diagrams = Array.isArray(result.diagrams) ? result.diagrams : [];
        diagramBetaState = {
            runId,
            diagrams,
            activeIndex: -1,
            iframeReady: diagramBetaState.iframeReady,
            iframeLastEvent: diagramBetaState.iframeLastEvent,
            viewerAvailable: diagramBetaState.viewerAvailable,
            viewerUrl: diagramBetaState.viewerUrl,
            viewerInitTimer: diagramBetaState.viewerInitTimer,
            viewerPendingPayload: diagramBetaState.viewerPendingPayload,
            tagValuesByKey: diagramBetaState.tagValuesByKey,
            previewSetPaths: diagramBetaState.previewSetPaths,
            livePreviewEnabled: diagramBetaState.livePreviewEnabled,
            livePreviewTimer: diagramBetaState.livePreviewTimer,
            livePreviewInFlight: diagramBetaState.livePreviewInFlight,
            livePreviewQueued: diagramBetaState.livePreviewQueued,
            suppressLivePreview: diagramBetaState.suppressLivePreview,
        };

        if (!diagrams.length) {
            buttonsHost.innerHTML = '';
            if (exportHost) exportHost.innerHTML = '';
            statusEl.textContent = 'No diagram artifacts (.drawio/.mxlibrary/.svg/.png) found for this run.';
            imageHost.style.display = 'none';
            iframe.style.display = diagramBetaState.viewerAvailable ? '' : 'none';
            return;
        }

        buttonsHost.innerHTML = diagrams.map((diagram, idx) => {
            const badge = diagramMetaBadgeText(diagram.meta);
            const classText = diagram.diagramClass ? String(diagram.diagramClass) : 'diagram';
            const hover = escapeHtml(diagram.hover || `${diagram.path || ''}`);
            const badgeHtml = badge ? `<div class="placeholder" style="font-size: 11px; margin-top: 2px;">${escapeHtml(badge)}</div>` : '';
            const title = escapeHtml(diagram.label || diagram.path || `diagram ${idx + 1}`);
            const sub = `<div class="placeholder" style="font-size: 11px; margin-top: 2px;">${escapeHtml(classText)} · ${escapeHtml(diagram.path || '')}</div>`;
            return `<button type="button" title="${hover}" onclick="previewDiagramBeta(${idx})">${title}${sub}${badgeHtml}</button>`;
        }).join('');

        statusEl.textContent = `Found ${diagrams.length} diagram artifact(s).`;
        await previewDiagramBeta(0);
        await loadDiagramTagFacets();
        await loadDiagramScopeOptionsForCurrentTarget();
    } catch (error) {
        buttonsHost.innerHTML = '';
        statusEl.textContent = `Failed to load diagram artifacts: ${error.message}`;
    }
}

async function loadDiagramScopeOptionsForCurrentTarget() {
    const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
    if (target === 'resource') {
        await loadVmScopeOptions();
    } else {
        await loadDiagramScopeOptions();
    }
}

async function loadDiagramTagFacets() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    if (!runId) {
        return;
    }
    try {
        const response = await fetch(`/api/inventory/facets/${encodeURIComponent(runId)}?artifact=inventory`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load diagram tag facets');
        }
        const tagKeys = result.facets?.tagKeys || [];
        diagramBetaState.tagValuesByKey = result.facets?.tagValuesByKey || {};
        populateInventoryFacetSelect('diagramGenerateTagKey', tagKeys);
        onDiagramTagKeyChanged();
    } catch {
        populateInventoryFacetSelect('diagramGenerateTagKey', []);
        populateInventoryFacetSelect('diagramGenerateTagValue', []);
    }
}

function onDiagramTagKeyChanged() {
    const key = document.getElementById('diagramGenerateTagKey')?.value || '';
    const values = key ? (diagramBetaState.tagValuesByKey[key] || []) : [];
    populateInventoryFacetSelect('diagramGenerateTagValue', values);
}

async function loadDiagramScopeOptions() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
    const tagKey = document.getElementById('diagramGenerateTagKey')?.value.trim() || '';
    const tagValue = document.getElementById('diagramGenerateTagValue')?.value.trim() || '';
    const scopeSelect = document.getElementById('diagramGenerateScope');
    const statusEl = document.getElementById('diagramBetaStatus');
    if (!scopeSelect) {
        return;
    }

    if (!runId) {
        scopeSelect.innerHTML = '<option value="">-- Choose scope --</option>';
        return;
    }

    try {
        scopeSelect.innerHTML = '<option value="">Loading scope options...</option>';
        const params = new URLSearchParams({ target, limit: '1000', tag_key: tagKey, tag_value: tagValue });
        const response = await fetch(`/api/diagram/scope-options/${encodeURIComponent(runId)}?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load scope options');
        }

        const options = Array.isArray(result.options) ? result.options : [];
        if (!options.length) {
            scopeSelect.innerHTML = '<option value="">-- No scope values found --</option>';
            if (statusEl) {
                statusEl.textContent = `No scope options found for target ${target}.`;
            }
            return;
        }

        scopeSelect.innerHTML = '';
        const placeholderOption = document.createElement('option');
        placeholderOption.value = '';
        placeholderOption.textContent = '-- Choose scope --';
        scopeSelect.appendChild(placeholderOption);
        options.forEach(item => {
            const option = document.createElement('option');
            option.value = String(item.value || '');
            option.textContent = String(item.label || item.value || '');
            if (typeof item.count === 'number') {
                option.dataset.count = String(item.count);
            }
            scopeSelect.appendChild(option);
        });
    } catch (error) {
        scopeSelect.innerHTML = '<option value="">-- Failed to load scope options --</option>';
        if (statusEl) {
            statusEl.textContent = `Failed to load scope options: ${error.message}`;
        }
    }
}

async function loadVmScopeOptions() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const vmSelect = document.getElementById('diagramVmSelect');
    const statusEl = document.getElementById('diagramVmScopeStatus');
    if (!vmSelect) {
        return;
    }
    if (!runId) {
        vmSelect.innerHTML = '<option value="">-- Choose a run first --</option>';
        return;
    }
    try {
        vmSelect.innerHTML = '<option value="">Loading VMs...</option>';
        if (statusEl) statusEl.textContent = '';
        const params = new URLSearchParams({ target: 'resource', limit: '5000', type_filter: 'microsoft.compute/virtualmachines' });
        const response = await fetch(`/api/diagram/scope-options/${encodeURIComponent(runId)}?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load VM list');
        }
        const options = Array.isArray(result.options) ? result.options : [];
        vmSelect.innerHTML = '';
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = options.length ? `-- Select a VM (${options.length} found) --` : '-- No VMs found in this run --';
        vmSelect.appendChild(placeholder);
        options.forEach(item => {
            const opt = document.createElement('option');
            opt.value = String(item.value || '');
            const name = String(item.name || item.value?.split('/').pop() || '');
            const rg = String(item.resourceGroup || '');
            opt.textContent = rg ? `${name}  (${rg})` : name;
            opt.title = String(item.value || '');
            vmSelect.appendChild(opt);
        });
        if (statusEl) statusEl.textContent = options.length ? `${options.length} virtual machine(s) found.` : 'No VMs found in the inventory for this run.';
    } catch (error) {
        vmSelect.innerHTML = '<option value="">-- Failed to load VMs --</option>';
        if (statusEl) statusEl.textContent = `Failed to load VMs: ${error.message}`;
    }
}

function onDiagramVmSelectChanged() {
    const vmSelect = document.getElementById('diagramVmSelect');
    const vmInput = document.getElementById('diagramVmResourceId');
    if (!vmSelect || !vmInput) {
        return;
    }
    const selected = vmSelect.value;
    if (selected) {
        vmInput.value = selected;
    }
    scheduleDiagramLivePreview('VM selection');
}

function onDiagramGenerateTargetChanged() {
    const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
    const tagKeyGroup = document.getElementById('diagramGenerateTagKeyGroup');
    const tagValueGroup = document.getElementById('diagramGenerateTagValueGroup');
    const vmQuickGroup = document.getElementById('diagramVmQuickGroup');
    const scopeGroup = document.getElementById('diagramGenerateScopeGroup');
    const isTagTarget = target === 'tag' || target === 'application' || target === 'resourcegroup-tag';
    const isVmTarget = target === 'resource';
    if (tagKeyGroup) {
        tagKeyGroup.style.display = isTagTarget ? '' : 'none';
    }
    if (tagValueGroup) {
        tagValueGroup.style.display = isTagTarget ? '' : 'none';
    }
    if (vmQuickGroup) {
        vmQuickGroup.style.display = isVmTarget ? '' : 'none';
    }
    // Hide the generic scope dropdown for VM mode — VMs have their own picker
    if (scopeGroup) {
        scopeGroup.style.display = isVmTarget ? 'none' : '';
    }

    const includeNeighborsEl = document.getElementById('diagramIncludeNeighbors');
    const depthEl = document.getElementById('diagramRelationshipDepth');
    if (includeNeighborsEl && depthEl) {
        if (target === 'resourcegroup' || target === 'resourcegroup-tag') {
            includeNeighborsEl.value = 'false';
            depthEl.value = '0';
        } else {
            includeNeighborsEl.value = 'true';
            if (depthEl.value === '0') {
                depthEl.value = '1';
            }
        }
    }
    onDiagramNeighborModeChanged();
    syncDiagramShortcutButtons();
    if (isVmTarget) {
        loadVmScopeOptions();
    } else {
        loadDiagramScopeOptions();
    }
    scheduleDiagramLivePreview('target change');
}

function onDiagramNeighborModeChanged() {
    const includeNeighborsEl = document.getElementById('diagramIncludeNeighbors');
    const depthEl = document.getElementById('diagramRelationshipDepth');
    if (!includeNeighborsEl || !depthEl) {
        return;
    }
    const enabled = includeNeighborsEl.value === 'true';
    depthEl.disabled = !enabled;
    if (!enabled) {
        depthEl.value = '0';
    } else if (depthEl.value === '0') {
        depthEl.value = '1';
    }
    syncDiagramShortcutButtons();
    scheduleDiagramLivePreview('relationship settings');
}

function spacingPresetFromSlider(value) {
    const numeric = Number.parseInt(String(value || '20'), 10);
    return numeric >= 50 ? 'spacious' : 'compact';
}

function spacingLabelForPreset(preset) {
    return preset === 'spacious' ? 'Spacious' : 'Compact';
}

function diagramMetaBadgeText(meta) {
    if (!meta || typeof meta !== 'object') {
        return '';
    }
    const parts = [];
    if (meta.diagramMode) parts.push(String(meta.diagramMode));
    if (meta.spacingPreset) parts.push(spacingLabelForPreset(String(meta.spacingPreset).toLowerCase()));
    if (typeof meta.layoutMagic === 'boolean') parts.push(meta.layoutMagic ? 'Smart' : 'Manual');
    return parts.join(' | ');
}

function onDiagramSpacingChanged() {
    const slider = document.getElementById('diagramSpacingSlider');
    const value = document.getElementById('diagramSpacingValue');
    if (!slider || !value) {
        return;
    }
    value.textContent = spacingLabelForPreset(spacingPresetFromSlider(slider.value));
    syncDiagramShortcutButtons();
    scheduleDiagramLivePreview('spacing change');
}

function onResourceDiagramSpacingChanged() {
    const slider = document.getElementById('resourceDiagramSpacingSlider');
    const value = document.getElementById('resourceDiagramSpacingValue');
    if (!slider || !value) {
        return;
    }
    value.textContent = spacingLabelForPreset(spacingPresetFromSlider(slider.value));
}

function setDiagramControlValue(id, value) {
    const element = document.getElementById(id);
    if (element) {
        element.value = value;
    }
}

function updateDiagramShortcutButtonState(selector, attributeName, activeValue) {
    document.querySelectorAll(selector).forEach(button => {
        button.classList.toggle('active', String(button.getAttribute(attributeName) || '') === String(activeValue || ''));
    });
}

function currentDiagramDepthShortcut() {
    const includeNeighbors = (document.getElementById('diagramIncludeNeighbors')?.value || 'false') === 'true';
    const depth = document.getElementById('diagramRelationshipDepth')?.value || '0';
    if (!includeNeighbors || depth === '0') {
        return 'isolated';
    }
    if (depth === '1') {
        return 'immediate';
    }
    if (depth === '2') {
        return 'expanded';
    }
    return 'deep';
}

function currentDiagramStyleShortcut() {
    const mode = document.getElementById('diagramGenerateMode')?.value || 'MSFT';
    const spacing = spacingPresetFromSlider(document.getElementById('diagramSpacingSlider')?.value || '20');
    const layoutMagic = (document.getElementById('diagramLayoutMagic')?.value || 'true') === 'true';
    const edgeLabels = (document.getElementById('diagramEdgeLabels')?.value || 'false') === 'true';
    const subnetColors = (document.getElementById('diagramSubnetColors')?.value || 'false') === 'true';

    if (mode === 'L2R' && spacing === 'spacious' && layoutMagic && !edgeLabels) {
        return 'flow';
    }
    if (mode === 'HUB-SPOKE' && layoutMagic && subnetColors) {
        return 'hub-spoke';
    }
    if (mode === 'MSFT' && spacing === 'spacious' && layoutMagic && !edgeLabels && !subnetColors) {
        return 'presentation';
    }
    if (mode === 'MSFT' && spacing === 'compact' && layoutMagic && edgeLabels && subnetColors) {
        return 'diagnostic';
    }
    if (mode === 'MSFT' && spacing === 'compact' && layoutMagic && !edgeLabels && subnetColors) {
        return 'architecture';
    }
    return '';
}

function syncDiagramShortcutButtons() {
    updateDiagramShortcutButtonState('.diagram-shortcut-btn[data-depth-shortcut]', 'data-depth-shortcut', currentDiagramDepthShortcut());
    updateDiagramShortcutButtonState('.diagram-shortcut-btn[data-style-shortcut]', 'data-style-shortcut', currentDiagramStyleShortcut());
}

function applyDiagramDepthShortcut(presetKey) {
    if (presetKey === 'isolated') {
        setDiagramControlValue('diagramIncludeNeighbors', 'false');
        setDiagramControlValue('diagramRelationshipDepth', '0');
    } else if (presetKey === 'immediate') {
        setDiagramControlValue('diagramIncludeNeighbors', 'true');
        setDiagramControlValue('diagramRelationshipDepth', '1');
    } else if (presetKey === 'expanded') {
        setDiagramControlValue('diagramIncludeNeighbors', 'true');
        setDiagramControlValue('diagramRelationshipDepth', '2');
    } else if (presetKey === 'deep') {
        setDiagramControlValue('diagramIncludeNeighbors', 'true');
        setDiagramControlValue('diagramRelationshipDepth', '3');
    }
    onDiagramNeighborModeChanged();
    syncDiagramShortcutButtons();
    scheduleDiagramLivePreview('depth preset');
}

function applyDiagramStyleShortcut(presetKey) {
    if (presetKey === 'architecture') {
        setDiagramControlValue('diagramGenerateMode', 'MSFT');
        setDiagramControlValue('diagramSpacingSlider', '20');
        setDiagramControlValue('diagramLayoutMagic', 'true');
        setDiagramControlValue('diagramEdgeLabels', 'false');
        setDiagramControlValue('diagramSubnetColors', 'true');
    } else if (presetKey === 'presentation') {
        setDiagramControlValue('diagramGenerateMode', 'MSFT');
        setDiagramControlValue('diagramSpacingSlider', '80');
        setDiagramControlValue('diagramLayoutMagic', 'true');
        setDiagramControlValue('diagramEdgeLabels', 'false');
        setDiagramControlValue('diagramSubnetColors', 'false');
    } else if (presetKey === 'flow') {
        setDiagramControlValue('diagramGenerateMode', 'L2R');
        setDiagramControlValue('diagramSpacingSlider', '70');
        setDiagramControlValue('diagramLayoutMagic', 'true');
        setDiagramControlValue('diagramEdgeLabels', 'false');
        setDiagramControlValue('diagramSubnetColors', 'false');
    } else if (presetKey === 'hub-spoke') {
        setDiagramControlValue('diagramGenerateMode', 'HUB-SPOKE');
        setDiagramControlValue('diagramSpacingSlider', '25');
        setDiagramControlValue('diagramLayoutMagic', 'true');
        setDiagramControlValue('diagramEdgeLabels', 'false');
        setDiagramControlValue('diagramSubnetColors', 'true');
    } else if (presetKey === 'diagnostic') {
        setDiagramControlValue('diagramGenerateMode', 'MSFT');
        setDiagramControlValue('diagramSpacingSlider', '20');
        setDiagramControlValue('diagramLayoutMagic', 'true');
        setDiagramControlValue('diagramEdgeLabels', 'true');
        setDiagramControlValue('diagramSubnetColors', 'true');
    }
    onDiagramSpacingChanged();
    syncDiagramShortcutButtons();
    scheduleDiagramLivePreview('style preset');
}

function canRunDiagramLivePreview() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
    if (!runId) {
        return false;
    }
    if (target === 'resource') {
        return Boolean(document.getElementById('diagramVmResourceId')?.value.trim());
    }
    return Boolean(document.getElementById('diagramGenerateScope')?.value || '');
}

function onDiagramLivePreviewToggleChanged() {
    const enabled = Boolean(document.getElementById('diagramLivePreviewToggle')?.checked);
    diagramBetaState.livePreviewEnabled = enabled;
    if (!enabled && diagramBetaState.livePreviewTimer) {
        clearTimeout(diagramBetaState.livePreviewTimer);
        diagramBetaState.livePreviewTimer = null;
    }
    const statusEl = document.getElementById('diagramBetaStatus');
    if (statusEl) {
        statusEl.textContent = enabled
            ? 'Live preview enabled. Diagram Beta will auto-regenerate when generation controls change.'
            : 'Live preview disabled. Use Generate or Refresh Preview Now to update diagrams.';
    }
    if (enabled) {
        scheduleDiagramLivePreview('live preview enabled');
    }
}

function scheduleDiagramLivePreview(reason = 'settings updated') {
    if (!diagramBetaState.livePreviewEnabled || diagramBetaState.suppressLivePreview || !canRunDiagramLivePreview()) {
        return;
    }
    if (diagramBetaState.livePreviewTimer) {
        clearTimeout(diagramBetaState.livePreviewTimer);
    }
    const statusEl = document.getElementById('diagramBetaStatus');
    if (statusEl) {
        statusEl.textContent = `Live preview queued after ${reason}...`;
    }
    diagramBetaState.livePreviewTimer = setTimeout(() => {
        diagramBetaState.livePreviewTimer = null;
        runDiagramLivePreview(reason);
    }, 850);
}

async function refreshDiagramLivePreviewNow() {
    await runDiagramLivePreview('manual refresh');
}

async function runDiagramLivePreview(reason = 'settings updated') {
    if (!canRunDiagramLivePreview()) {
        showGlobalNotice('Choose a run and a valid scope before refreshing Diagram Beta preview.');
        return null;
    }
    if (diagramBetaState.livePreviewInFlight) {
        diagramBetaState.livePreviewQueued = true;
        return null;
    }

    diagramBetaState.livePreviewInFlight = true;
    const statusEl = document.getElementById('diagramBetaStatus');
    if (statusEl) {
        statusEl.textContent = `Live preview updating after ${reason}...`;
    }

    try {
        const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
        if (target === 'resource') {
            return await generateVmQuickDiagram();
        }
        return await generateScopedNetworkDiagram();
    } finally {
        diagramBetaState.livePreviewInFlight = false;
        if (diagramBetaState.livePreviewQueued) {
            diagramBetaState.livePreviewQueued = false;
            scheduleDiagramLivePreview('queued changes');
        }
    }
}

function autoTuneDiagramSettings() {
    const scopeEl = document.getElementById('diagramGenerateScope');
    const modeEl = document.getElementById('diagramGenerateMode');
    const includeNeighborsEl = document.getElementById('diagramIncludeNeighbors');
    const depthEl = document.getElementById('diagramRelationshipDepth');
    const spacingEl = document.getElementById('diagramSpacingSlider');
    const layoutMagicEl = document.getElementById('diagramLayoutMagic');
    const edgeLabelsEl = document.getElementById('diagramEdgeLabels');
    const subnetColorsEl = document.getElementById('diagramSubnetColors');

    const selected = scopeEl?.selectedOptions?.[0];
    const count = Number.parseInt(selected?.dataset?.count || '0', 10) || 0;

    if (count >= 200) {
        if (modeEl) modeEl.value = 'L2R';
        if (includeNeighborsEl) includeNeighborsEl.value = 'false';
        if (depthEl) depthEl.value = '0';
        if (spacingEl) spacingEl.value = '80';
        if (layoutMagicEl) layoutMagicEl.value = 'true';
        if (edgeLabelsEl) edgeLabelsEl.value = 'false';
        if (subnetColorsEl) subnetColorsEl.value = 'false';
    } else if (count >= 80) {
        if (modeEl) modeEl.value = 'MSFT';
        if (includeNeighborsEl) includeNeighborsEl.value = 'true';
        if (depthEl) depthEl.value = '1';
        if (spacingEl) spacingEl.value = '70';
        if (layoutMagicEl) layoutMagicEl.value = 'true';
        if (edgeLabelsEl) edgeLabelsEl.value = 'false';
        if (subnetColorsEl) subnetColorsEl.value = 'true';
    } else {
        if (modeEl) modeEl.value = 'MSFT';
        if (includeNeighborsEl) includeNeighborsEl.value = 'true';
        if (depthEl) depthEl.value = '2';
        if (spacingEl) spacingEl.value = '20';
        if (layoutMagicEl) layoutMagicEl.value = 'true';
        if (edgeLabelsEl) edgeLabelsEl.value = 'true';
        if (subnetColorsEl) subnetColorsEl.value = 'true';
    }

    onDiagramSpacingChanged();
    syncDiagramShortcutButtons();
    scheduleDiagramLivePreview('auto tune');
}

async function generateResourceGroupGraphQuick() {
    const targetEl = document.getElementById('diagramGenerateTarget');
    const includeNeighborsEl = document.getElementById('diagramIncludeNeighbors');
    const depthEl = document.getElementById('diagramRelationshipDepth');
    if (targetEl) {
        targetEl.value = 'resourcegroup';
    }
    if (includeNeighborsEl) {
        includeNeighborsEl.value = 'false';
    }
    if (depthEl) {
        depthEl.value = '0';
    }
    await loadDiagramScopeOptions();
    const scope = document.getElementById('diagramGenerateScope')?.value || '';
    if (!scope) {
        showGlobalNotice('Choose a resource group scope first.');
        return;
    }
    await generateScopedNetworkDiagram();
}

async function generateTagGraphQuick() {
    const targetEl = document.getElementById('diagramGenerateTarget');
    const includeNeighborsEl = document.getElementById('diagramIncludeNeighbors');
    const depthEl = document.getElementById('diagramRelationshipDepth');
    if (targetEl) {
        targetEl.value = 'tag';
    }
    if (includeNeighborsEl) {
        includeNeighborsEl.value = 'true';
    }
    if (depthEl) {
        depthEl.value = '1';
    }
    await loadDiagramScopeOptions();
    const scope = document.getElementById('diagramGenerateScope')?.value || '';
    if (!scope) {
        showGlobalNotice('Choose a tag scope first.');
        return;
    }
    await generateScopedNetworkDiagram();
}

async function generateScopedNetworkDiagram() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const target = document.getElementById('diagramGenerateTarget')?.value || 'resourcegroup';
    const scope = document.getElementById('diagramGenerateScope')?.value || '';
    const diagramMode = document.getElementById('diagramGenerateMode')?.value || 'MSFT';
    const spacingPreset = spacingPresetFromSlider(document.getElementById('diagramSpacingSlider')?.value || '20');
    const layoutMagic = (document.getElementById('diagramLayoutMagic')?.value || 'true') === 'true';
    const edgeLabels = (document.getElementById('diagramEdgeLabels')?.value || 'false') === 'true';
    const subnetColors = (document.getElementById('diagramSubnetColors')?.value || 'false') === 'true';
    const tagKey = document.getElementById('diagramGenerateTagKey')?.value.trim() || '';
    const tagValue = document.getElementById('diagramGenerateTagValue')?.value.trim() || '';
    const includeNeighbors = (document.getElementById('diagramIncludeNeighbors')?.value || 'false') === 'true';
    const relationshipDepth = Number.parseInt(document.getElementById('diagramRelationshipDepth')?.value || '0', 10) || 0;
    const statusEl = document.getElementById('diagramBetaStatus');

    if (!runId) {
        showGlobalNotice('Choose a run first.');
        return;
    }
    if (!scope) {
        showGlobalNotice('Choose a scope value first.');
        return;
    }

    try {
        if (statusEl) {
            statusEl.textContent = `Generating scoped network diagram for ${target}: ${scope}...`;
        }

        const response = await fetch('/api/diagram/generate-scoped', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                run_id: runId,
                target,
                scope,
                diagram_mode: diagramMode,
                spacing_preset: spacingPreset,
                layout_magic: layoutMagic,
                edge_labels: edgeLabels,
                subnet_colors: subnetColors,
                include_neighbors: includeNeighbors,
                relationship_depth: relationshipDepth,
                tag_key: tagKey,
                tag_value: tagValue,
            }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Scoped diagram generation failed');
        }

        if (statusEl) {
            statusEl.textContent = `Generated scoped diagram (${result.nodeCount} nodes / ${result.edgeCount} edges): ${result.diagramPath}`;
        }

        await loadDiagramBeta();
        const idx = diagramBetaState.diagrams.findIndex(item => item.path === result.diagramPath);
        if (idx >= 0) {
            await previewDiagramBeta(idx);
        }
        return result;
    } catch (error) {
        if (statusEl) {
            statusEl.textContent = `Scoped diagram generation failed: ${error.message}`;
        }
        return null;
    }
}

async function generateVmQuickDiagram() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const vmResourceId = document.getElementById('diagramVmResourceId')?.value.trim() || '';
    const diagramMode = document.getElementById('diagramGenerateMode')?.value || 'MSFT';
    const spacingPreset = spacingPresetFromSlider(document.getElementById('diagramSpacingSlider')?.value || '20');
    const layoutMagic = (document.getElementById('diagramLayoutMagic')?.value || 'true') === 'true';
    const edgeLabels = (document.getElementById('diagramEdgeLabels')?.value || 'false') === 'true';
    const subnetColors = (document.getElementById('diagramSubnetColors')?.value || 'true') === 'true';
    const statusEl = document.getElementById('diagramBetaStatus');

    if (!runId) {
        showGlobalNotice('Choose a run first.');
        return;
    }
    if (!vmResourceId) {
        showGlobalNotice('Provide a VM resource ID.');
        return;
    }

    try {
        if (statusEl) {
            statusEl.textContent = 'Generating VM quick diagram (immediate related resources)...';
        }
        const response = await fetch('/api/diagram/generate-vm-quick', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                run_id: runId,
                vm_resource_id: vmResourceId,
                include_neighbors: true,
                relationship_depth: 2,
                diagram_mode: diagramMode,
                spacing_preset: spacingPreset,
                layout_magic: layoutMagic,
                edge_labels: edgeLabels,
                subnet_colors: subnetColors,
            }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'VM quick diagram generation failed');
        }

        if (statusEl) {
            statusEl.textContent = `Generated VM quick diagram (${result.nodeCount} nodes / ${result.edgeCount} edges): ${result.diagramPath}`;
        }

        await loadDiagramBeta();
        const idx = diagramBetaState.diagrams.findIndex(item => item.path === result.diagramPath);
        if (idx >= 0) {
            await previewDiagramBeta(idx);
        }
        return result;
    } catch (error) {
        if (statusEl) {
            statusEl.textContent = `VM quick diagram generation failed: ${error.message}`;
        }
        return null;
    }
}

async function generateStylePreviewSet() {
    const presets = [
        { diagramMode: 'MSFT', spacingValue: '20', layoutMagic: 'true', edgeLabels: 'false', subnetColors: 'true' },
        { diagramMode: 'MSFT', spacingValue: '80', layoutMagic: 'true', edgeLabels: 'false', subnetColors: 'false' },
        { diagramMode: 'L2R', spacingValue: '70', layoutMagic: 'true', edgeLabels: 'false', subnetColors: 'false' },
        { diagramMode: 'HUB-SPOKE', spacingValue: '20', layoutMagic: 'true', edgeLabels: 'false', subnetColors: 'true' },
    ];

    const statusEl = document.getElementById('diagramBetaStatus');
    const modeEl = document.getElementById('diagramGenerateMode');
    const spacingEl = document.getElementById('diagramSpacingSlider');
    const layoutMagicEl = document.getElementById('diagramLayoutMagic');
    const edgeLabelsEl = document.getElementById('diagramEdgeLabels');
    const subnetColorsEl = document.getElementById('diagramSubnetColors');
    const generatedPaths = [];

    for (let i = 0; i < presets.length; i += 1) {
        const preset = presets[i];
        if (modeEl) modeEl.value = preset.diagramMode;
        if (spacingEl) spacingEl.value = preset.spacingValue;
        if (layoutMagicEl) layoutMagicEl.value = preset.layoutMagic;
        if (edgeLabelsEl) edgeLabelsEl.value = preset.edgeLabels;
        if (subnetColorsEl) subnetColorsEl.value = preset.subnetColors;
        onDiagramSpacingChanged();

        if (statusEl) {
            statusEl.textContent = `Generating preview ${i + 1}/${presets.length} (${preset.diagramMode}, ${spacingLabelForPreset(spacingPresetFromSlider(preset.spacingValue))})...`;
        }
        const result = await generateScopedNetworkDiagram();
        if (result && result.diagramPath) {
            generatedPaths.push(String(result.diagramPath));
        }
    }

    diagramBetaState.previewSetPaths = generatedPaths;
}

async function exportPreviewSetZip() {
    const runId = document.getElementById('diagramBetaRunIdSelect')?.value || '';
    const statusEl = document.getElementById('diagramBetaStatus');
    const candidatePaths = Array.isArray(diagramBetaState.previewSetPaths) && diagramBetaState.previewSetPaths.length
        ? diagramBetaState.previewSetPaths
        : (Array.isArray(diagramBetaState.diagrams) ? diagramBetaState.diagrams.map(item => item.path).filter(Boolean) : []);

    if (!runId) {
        showGlobalNotice('Choose a run first.');
        return;
    }
    if (!candidatePaths.length) {
        showGlobalNotice('No preview set diagrams available yet. Generate style previews first.');
        return;
    }

    try {
        if (statusEl) {
            statusEl.textContent = `Bundling ${candidatePaths.length} diagram artifacts...`;
        }

        const response = await fetch('/api/artifacts/export-bundle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                run_id: runId,
                diagram_paths: candidatePaths,
                include_related: true,
            }),
        });

        if (!response.ok) {
            const result = await response.json().catch(() => ({}));
            throw new Error(result.detail || 'Failed to create zip bundle');
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const disposition = response.headers.get('Content-Disposition') || '';
        const match = disposition.match(/filename=([^;]+)/i);
        const fileName = match ? match[1].replace(/["']/g, '') : `diagram-preview-bundle-${runId}.zip`;

        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = fileName;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(url);

        if (statusEl) {
            statusEl.textContent = `Exported preview bundle: ${fileName}`;
        }
    } catch (error) {
        if (statusEl) {
            statusEl.textContent = `Preview bundle export failed: ${error.message}`;
        }
    }
}

function renderDiagramExportActions(runId, diagram) {
    const host = document.getElementById('diagramBetaExportActions');
    if (!host) {
        return;
    }
    if (!runId || !diagram || !diagram.path) {
        host.innerHTML = '';
        return;
    }

    const drawioPath = String(diagram.path || '');
    const basePath = drawioPath.replace(/\.drawio$/i, '');
    const drawioUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodeArtifactPath(drawioPath)}`;
    const svgUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodeArtifactPath(basePath + '.svg')}`;
    const pngUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodeArtifactPath(basePath + '.png')}`;
    const available = new Set((diagramBetaState.diagrams || []).map(item => String(item.path || '').toLowerCase()));
    const hasSvg = available.has((basePath + '.svg').toLowerCase());
    const hasPng = available.has((basePath + '.png').toLowerCase());

    const links = [
        `<a class="btn-primary" href="${drawioUrl}" download>Export .drawio</a>`,
    ];

    if (hasSvg) {
        links.push(`<a class="btn-primary" href="${svgUrl}" download>Export .svg</a>`);
    } else {
        links.push(`<button class="btn-primary" type="button" disabled title="SVG export not available for this diagram.">Export .svg</button>`);
    }

    if (hasPng) {
        links.push(`<a class="btn-primary" href="${pngUrl}" download>Export .png</a>`);
    } else {
        links.push(`<button class="btn-primary" type="button" disabled title="PNG export not available. Install drawio CLI on the server/container to enable PNG export.">Export .png</button>`);
    }

    host.innerHTML = links.join('');
}

function renderDiagramBetaXmlFallback(diagram, xmlText, reasonText) {
    const imageHost = document.getElementById('diagramBetaImageHost');
    const iframe = document.getElementById('diagramBetaIframe');
    const statusEl = document.getElementById('diagramBetaStatus');
    if (!imageHost || !iframe || !statusEl) {
        return;
    }
    iframe.style.display = 'none';
    imageHost.style.display = '';
    imageHost.innerHTML = `
        <div class="diagram-header"><strong>${escapeHtml(diagram.label || diagram.name || 'draw.io')}</strong></div>
        <p class="placeholder" style="margin-bottom: 8px;">${escapeHtml(reasonText)}</p>
        <pre>${escapeHtml(xmlText.slice(0, 25000))}${xmlText.length > 25000 ? '\n... (truncated)' : ''}</pre>
    `;
    statusEl.textContent = reasonText;
}

function queueDiagramViewerPayload(payload, statusText) {
    const iframe = document.getElementById('diagramBetaIframe');
    const hint = document.getElementById('diagramBetaViewerHint');
    if (!iframe || !diagramBetaState.viewerAvailable) {
        return false;
    }
    diagramBetaState.viewerPendingPayload = payload;
    if (diagramBetaState.iframeReady && iframe.contentWindow) {
        iframe.contentWindow.postMessage(JSON.stringify(payload), '*');
        if (hint) {
            hint.textContent = 'Rendering diagram in embedded viewer...';
        }
        return true;
    }
    if (hint) {
        hint.textContent = 'Embedded viewer booting. Diagram queued for render...';
    }
    if (statusText) {
        const statusEl = document.getElementById('diagramBetaStatus');
        if (statusEl) {
            statusEl.textContent = statusText;
        }
    }
    return true;
}

async function previewDiagramBeta(index) {
    try {
        const { runId, diagrams } = diagramBetaState;
        const statusEl = document.getElementById('diagramBetaStatus');
        const iframe = document.getElementById('diagramBetaIframe');
        const imageHost = document.getElementById('diagramBetaImageHost');

        if (!runId || !Array.isArray(diagrams) || index < 0 || index >= diagrams.length || !statusEl || !iframe || !imageHost) {
            return;
        }

        const diagram = diagrams[index];
        diagramBetaState.activeIndex = index;
        const encodedPath = encodeArtifactPath(diagram.path || '');
        const downloadUrl = `/api/artifacts/download/${encodeURIComponent(runId)}/${encodedPath}`;
        renderDiagramExportActions(runId, diagram);

        if (diagram.kind === 'image' || !diagramBetaState.viewerAvailable) {
            iframe.style.display = 'none';
            imageHost.style.display = '';
            if (!diagramBetaState.viewerAvailable && diagram.kind !== 'image') {
                const xmlResp = await fetch(downloadUrl);
                if (!xmlResp.ok) {
                    throw new Error(`Unable to fetch diagram XML (${xmlResp.status})`);
                }
                const xmlText = await xmlResp.text();
                renderDiagramBetaXmlFallback(
                    diagram,
                    xmlText,
                    `Viewer unavailable; showing draw.io XML preview: ${diagram.path}`
                );
                return;
            }
            imageHost.innerHTML = `
                <div class="diagram-header"><strong>${escapeHtml(diagram.label || diagram.name || 'image')}</strong></div>
                <img src="${downloadUrl}" alt="${escapeHtml(diagram.name || 'diagram image')}" />
            `;
            statusEl.textContent = `Previewing image diagram: ${diagram.path}`;
            return;
        }

        iframe.style.display = '';
        imageHost.style.display = 'none';
        imageHost.innerHTML = '';
        statusEl.textContent = `Loading draw.io diagram: ${diagram.path}`;

        const xmlResp = await fetch(downloadUrl);
        if (!xmlResp.ok) {
            throw new Error(`Unable to fetch diagram XML (${xmlResp.status})`);
        }
        const xmlText = await xmlResp.text();
        const payload = {
            action: 'load',
            xml: xmlText,
            name: diagram.name || diagram.path || 'diagram.drawio',
            autosave: 0,
            modified: 'unsavedChanges',
            saveAndExit: '0',
        };

        const queued = queueDiagramViewerPayload(
            payload,
            `Waiting for embedded viewer readiness before rendering ${diagram.path}...`
        );
        if (!queued) {
            renderDiagramBetaXmlFallback(
                diagram,
                xmlText,
                `Embedded viewer unavailable; showing draw.io XML preview: ${diagram.path}`
            );
            return;
        }

        statusEl.textContent = diagramBetaState.iframeReady
            ? `Rendering draw.io diagram: ${diagram.path}`
            : `Queued draw.io diagram for embedded viewer: ${diagram.path}`;
    } catch (error) {
        const statusEl = document.getElementById('diagramBetaStatus');
        if (statusEl) {
            statusEl.textContent = `Failed to preview diagram: ${error.message}`;
        }
    }
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

async function loadResourceDiagramInventory(resetOffset = false) {
    const runId = document.getElementById('resourceDiagramRunIdSelect')?.value || '';
    const statusEl = document.getElementById('resourceDiagramStatus');
    const resultsEl = document.getElementById('resourceDiagramResults');
    if (!statusEl || !resultsEl) {
        return;
    }
    if (!runId) {
        statusEl.textContent = 'Choose a run to load resources.';
        resultsEl.innerHTML = '';
        return;
    }

    if (resetOffset) {
        resourceDiagramState.offset = 0;
    }
    resourceDiagramState.limit = Number.parseInt(document.getElementById('resourceDiagramPageSize')?.value || '100', 10) || 100;
    const query = document.getElementById('resourceDiagramQuery')?.value.trim() || '';
    const tagKey = document.getElementById('resourceDiagramTagKey')?.value.trim() || '';
    const tagValue = document.getElementById('resourceDiagramTagValue')?.value.trim() || '';

    const params = new URLSearchParams({
        artifact: 'inventory',
        offset: String(resourceDiagramState.offset),
        limit: String(resourceDiagramState.limit),
        query,
        tag_key: tagKey,
        tag_value: tagValue,
    });

    try {
        const response = await fetch(`/api/inventory/explore/${encodeURIComponent(runId)}?${params.toString()}`);
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to load resource inventory');
        }
        resourceDiagramState.rows = Array.isArray(result.rows) ? result.rows : [];
        resourceDiagramState.totalRows = Number(result.totalRows || 0);
        resourceDiagramState.filteredRows = Number(result.filteredRows || 0);
        const end = Math.min(result.offset + resourceDiagramState.rows.length, resourceDiagramState.filteredRows);
        statusEl.textContent =
            `Selected ${resourceDiagramState.selectedIds.size} resources | ` +
            `Showing ${resourceDiagramState.rows.length === 0 ? 0 : result.offset + 1}-${end} of ${resourceDiagramState.filteredRows}`;

        const previewRows = resourceDiagramState.rows.map(row => {
            const rid = String(row.id || '');
            const checked = resourceDiagramState.selectedIds.has(rid) ? 'checked' : '';
            return `
            <tr>
                <td><input type="checkbox" ${checked} onchange="toggleResourceDiagramSelection('${escapeHtml(rid)}', this.checked)"></td>
                <td>${escapeHtml(row.name || '-')}</td>
                <td>${escapeHtml(row.type || '-')}</td>
                <td>${escapeHtml(row.resourceGroup || '-')}</td>
                <td>${escapeHtml(row.id || '-')}</td>
            </tr>
        `;
        }).join('');

        resultsEl.innerHTML = `
            <div class="data-table-wrap" style="margin-top: 10px;">
                <table class="data-table">
                    <thead><tr><th>Select</th><th>Name</th><th>Type</th><th>Resource Group</th><th>ID</th></tr></thead>
                    <tbody>${previewRows}</tbody>
                </table>
            </div>
        `;
    } catch (error) {
        statusEl.textContent = `Failed to load resource inventory: ${error.message}`;
        resultsEl.innerHTML = '';
    }
}

function toggleResourceDiagramSelection(resourceId, checked) {
    const rid = String(resourceId || '');
    if (!rid) {
        return;
    }
    if (checked) {
        resourceDiagramState.selectedIds.add(rid);
    } else {
        resourceDiagramState.selectedIds.delete(rid);
    }
    const statusEl = document.getElementById('resourceDiagramStatus');
    if (statusEl) {
        statusEl.textContent =
            `Selected ${resourceDiagramState.selectedIds.size} resources | ` +
            `Showing ${resourceDiagramState.rows.length} on current page`;
    }
}

function selectAllVisibleResourceDiagramRows() {
    resourceDiagramState.rows.forEach(row => {
        const rid = String(row.id || '');
        if (rid) {
            resourceDiagramState.selectedIds.add(rid);
        }
    });
    loadResourceDiagramInventory(false);
}

function clearResourceDiagramSelection() {
    resourceDiagramState.selectedIds.clear();
    loadResourceDiagramInventory(false);
}

function resourceDiagramPreviousPage() {
    resourceDiagramState.offset = Math.max(0, resourceDiagramState.offset - resourceDiagramState.limit);
    loadResourceDiagramInventory(false);
}

function resourceDiagramNextPage() {
    resourceDiagramState.offset += resourceDiagramState.limit;
    loadResourceDiagramInventory(false);
}

async function generateResourceSelectionDiagram() {
    const runId = document.getElementById('resourceDiagramRunIdSelect')?.value || '';
    const statusEl = document.getElementById('resourceDiagramStatus');
    if (!runId) {
        showGlobalNotice('Choose a run first.');
        return;
    }
    const resourceIds = Array.from(resourceDiagramState.selectedIds);
    if (!resourceIds.length) {
        showGlobalNotice('Select at least one resource first.');
        return;
    }

    const includeNeighbors = (document.getElementById('resourceDiagramIncludeNeighbors')?.value || 'true') === 'true';
    const relationshipDepth = Number.parseInt(document.getElementById('resourceDiagramRelationshipDepth')?.value || '1', 10) || 1;
    const diagramMode = document.getElementById('resourceDiagramMode')?.value || 'MSFT';
    const spacingPreset = spacingPresetFromSlider(document.getElementById('resourceDiagramSpacingSlider')?.value || '20');
    const layoutMagic = (document.getElementById('resourceDiagramLayoutMagic')?.value || 'true') === 'true';
    const edgeLabels = (document.getElementById('resourceDiagramEdgeLabels')?.value || 'false') === 'true';
    const subnetColors = (document.getElementById('resourceDiagramSubnetColors')?.value || 'false') === 'true';

    try {
        if (statusEl) {
            statusEl.textContent = `Generating diagram from ${resourceIds.length} selected resources...`;
        }
        const response = await fetch('/api/diagram/generate-selection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                run_id: runId,
                resource_ids: resourceIds,
                diagram_mode: diagramMode,
                spacing_preset: spacingPreset,
                layout_magic: layoutMagic,
                edge_labels: edgeLabels,
                subnet_colors: subnetColors,
                include_neighbors: includeNeighbors,
                relationship_depth: relationshipDepth,
            }),
        });
        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.detail || 'Failed to generate selection diagram');
        }

        if (statusEl) {
            statusEl.textContent =
                `Generated selection diagram (${result.nodeCount} nodes / ${result.edgeCount} edges): ${result.diagramPath}`;
        }

        const betaRunSelect = document.getElementById('diagramBetaRunIdSelect');
        if (betaRunSelect) {
            betaRunSelect.value = runId;
        }
        await loadDiagramBeta();
        switchTab('diagram-beta');
    } catch (error) {
        if (statusEl) {
            statusEl.textContent = `Selection diagram generation failed: ${error.message}`;
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
    hydrateConfigPresets();
    hydrateScenarioTemplates();

    const configPresetSelect = document.getElementById('configPresetSelect');
    if (configPresetSelect) {
        configPresetSelect.addEventListener('change', () => {
            const selectedName = String(configPresetSelect.value || '').trim();
            const preset = configPresetByName[selectedName];
            showConfigPresetDescription(preset && preset.description ? preset.description : '');
        });
    }

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

    window.addEventListener('message', (event) => {
        const iframe = document.getElementById('diagramBetaIframe');
        if (iframe && event.source && iframe.contentWindow && event.source !== iframe.contentWindow) {
            return;
        }
        let payload = event.data;
        if (typeof payload === 'string') {
            try {
                payload = JSON.parse(payload);
            } catch {
                return;
            }
        }
        if (!payload || typeof payload !== 'object') {
            return;
        }
        if (payload.source && payload.source !== 'diagram-beta-viewer') {
            return;
        }
        const eventName = String(payload.event || '').toLowerCase();
        const hint = document.getElementById('diagramBetaViewerHint');
        const statusEl = document.getElementById('diagramBetaStatus');
        diagramBetaState.iframeLastEvent = eventName;
        if (eventName === 'booting') {
            if (hint) {
                hint.textContent = 'Embedded viewer booting...';
            }
            return;
        }
        if (eventName === 'queued') {
            if (hint) {
                hint.textContent = 'Embedded viewer queued the next diagram payload.';
            }
            return;
        }
        if (eventName === 'init' || eventName === 'ready') {
            diagramBetaState.iframeReady = true;
            if (hint && diagramBetaState.viewerAvailable) {
                hint.textContent = 'Embedded viewer ready.';
            }
            if (diagramBetaState.viewerInitTimer) {
                clearTimeout(diagramBetaState.viewerInitTimer);
                diagramBetaState.viewerInitTimer = null;
            }
            if (diagramBetaState.viewerPendingPayload && iframe?.contentWindow) {
                iframe.contentWindow.postMessage(JSON.stringify(diagramBetaState.viewerPendingPayload), '*');
            }
            return;
        }
        if (eventName === 'rendered' || eventName === 'load') {
            diagramBetaState.viewerPendingPayload = null;
            if (hint) {
                const renderedName = payload.name || diagramBetaState.diagrams?.[diagramBetaState.activeIndex]?.name;
                hint.textContent = renderedName
                    ? `Embedded viewer rendered ${renderedName}.`
                    : 'Embedded viewer rendered the active diagram.';
            }
            if (statusEl) {
                const activeDiagram = diagramBetaState.diagrams?.[diagramBetaState.activeIndex];
                statusEl.textContent = activeDiagram?.path
                    ? `Previewing draw.io diagram: ${activeDiagram.path}`
                    : 'Previewing draw.io diagram.';
            }
            return;
        }
        if (eventName === 'error') {
            const message = payload.message || 'Embedded viewer reported an error.';
            diagramBetaState.viewerAvailable = false;
            diagramBetaState.iframeReady = false;
            diagramBetaState.viewerPendingPayload = null;
            if (hint) {
                hint.textContent = `Embedded viewer failed: ${message}`;
            }
            showGlobalNotice(`Diagram Beta viewer error: ${message}`);
            if (Number.isInteger(diagramBetaState.activeIndex) && diagramBetaState.activeIndex >= 0) {
                previewDiagramBeta(diagramBetaState.activeIndex);
            }
        }
    });

    [
        'diagramGenerateMode',
        'diagramLayoutMagic',
        'diagramEdgeLabels',
        'diagramSubnetColors',
        'diagramRelationshipDepth',
        'diagramGenerateScope',
        'diagramVmResourceId',
        'diagramVmSelect',
        'diagramGenerateTagKey',
        'diagramGenerateTagValue'
    ].forEach(id => {
        const element = document.getElementById(id);
        if (element) {
            element.addEventListener('change', () => {
                syncDiagramShortcutButtons();
                scheduleDiagramLivePreview(`${id} change`);
            });
        }
    });

    initDiagramBetaViewer();
    onDiagramGenerateTargetChanged();
    onDiagramSpacingChanged();
    onResourceDiagramSpacingChanged();
    syncDiagramShortcutButtons();
});

async function initDiagramBetaViewer() {
    const iframe = document.getElementById('diagramBetaIframe');
    const hint = document.getElementById('diagramBetaViewerHint');
    if (!iframe || !hint) {
        return;
    }

    try {
        const response = await fetch('/api/diagram-beta/viewer');
        const result = await response.json();
        if (!response.ok || !result.available || !result.url) {
            diagramBetaState.viewerAvailable = false;
            diagramBetaState.viewerUrl = '';
            diagramBetaState.iframeReady = false;
            diagramBetaState.iframeLastEvent = '';
            diagramBetaState.viewerPendingPayload = null;
            iframe.style.display = 'none';
            hint.textContent = 'Local embedded viewer not found. Beta tab will use XML/image fallback only.';
            return;
        }

        diagramBetaState.viewerAvailable = true;
        diagramBetaState.viewerUrl = String(result.url);
        diagramBetaState.iframeReady = false;
        diagramBetaState.iframeLastEvent = 'loading';
        diagramBetaState.viewerPendingPayload = null;
        if (diagramBetaState.viewerInitTimer) {
            clearTimeout(diagramBetaState.viewerInitTimer);
            diagramBetaState.viewerInitTimer = null;
        }
        iframe.onload = () => {
            diagramBetaState.iframeLastEvent = 'iframe-load';
            window.setTimeout(() => {
                if (iframe.contentWindow) {
                    iframe.contentWindow.postMessage(JSON.stringify({ action: 'ping' }), '*');
                }
            }, 200);
        };
        iframe.src = diagramBetaState.viewerUrl;
        iframe.style.display = '';
        hint.textContent = `Using local viewer (${result.source}). Waiting for readiness signal...`;
        diagramBetaState.viewerInitTimer = setTimeout(() => {
            if (!diagramBetaState.iframeReady) {
                diagramBetaState.viewerAvailable = false;
                diagramBetaState.viewerPendingPayload = null;
                iframe.style.display = 'none';
                hint.textContent = 'Embedded viewer did not report ready state. Using XML/image fallback.';
                if (Number.isInteger(diagramBetaState.activeIndex) && diagramBetaState.activeIndex >= 0) {
                    previewDiagramBeta(diagramBetaState.activeIndex);
                }
            }
        }, 15000);
    } catch (error) {
        diagramBetaState.viewerAvailable = false;
        diagramBetaState.viewerUrl = '';
        diagramBetaState.iframeReady = false;
        diagramBetaState.iframeLastEvent = '';
        diagramBetaState.viewerPendingPayload = null;
        iframe.style.display = 'none';
        hint.textContent = `Local viewer detection failed: ${error.message}`;
    }
}
