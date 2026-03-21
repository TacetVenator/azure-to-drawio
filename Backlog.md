# Backlog

Planned improvements and future work for azure-to-drawio, roughly ordered by priority.

## Migration Discovery

### Read-only migration assessment mode

**Priority:** High

Add a migration-focused reporting mode for teams documenting an existing Azure estate before moving into a landing zone.

This mode must work within these constraints:
- No new Python dependencies
- No writes or configuration changes in Azure
- Usable from VDI / hardened corporate laptops
- Expected access level is often Global Reader only
- Entra ID visibility may or may not be available

**Goals:**
- Answer "what is deployed?"
- Answer "what appears to talk to what?"
- Answer "how is it exposed?"
- Answer "what is missing from the evidence?"
- Provide advice on what to check next when visibility is incomplete

**Work:**
- Add a migration-oriented report that consolidates inventory, edges, routing, and exposure hints into a single decision-friendly document
- Clearly distinguish `discovered`, `inferred`, and `unknown` facts
- Add a "confidence / evidence" marker per relationship source:
  - ARG / ARM configuration
  - RBAC visibility
  - Telemetry-derived
  - unresolved external reference
- Add a "next checks" section when permissions or logging gaps limit the output

---

### Tag-seeded discovery (`seedTag` / app-tag discovery)

**Priority:** High

Support starting discovery from one or more tags instead of only `seedResourceGroups`.

This is critical for migration work where an application is scattered across multiple resource groups and subscriptions but consistently tagged, for example:
- `Application=checkout`
- `App=my-api`
- `Workload=crm`

**Work:**
- Add config support for tag-based seeds, for example:
  - `seedTags`: exact tag/value pairs
  - `seedTagKeys`: any resource carrying one of these keys
- Add an ARG query path that seeds from tags rather than RG names
- Allow combining tag seeds and RG seeds
- Document precedence and expected noise level
- Add app grouping support so diagrams and reports can show a likely application boundary

**Nice-to-have heuristics:**
- Special handling for `groupByTag=["any"]`
- Common app tag aliases: `Application`, `App`, `Service`, `Workload`, `System`, `Product`

---

### Exposure report

**Priority:** High

Add a dedicated report for "how is this exposed?" aimed at migration and security review.

**Work:**
- Identify public entry points where visible from ARM / ARG:
  - Public IPs
  - Public load balancers
  - Application Gateways
  - Front Door / CDN
  - Traffic Manager
  - App Service public endpoints
  - Storage / Key Vault / SQL public network access settings
- Summarize private exposure:
  - Private Endpoints
  - Private DNS zones
  - VNet integration
  - NSG / UDR context already visible in the graph
- For each exposed service, show:
  - entry resource
  - backend / dependent target if inferable
  - subnet / NSG / route table context if available
  - whether the evidence is direct or inferred
- Flag ambiguous cases where the current permissions are insufficient

---

### Missing telemetry and logging advisory

**Priority:** High

Do not assume telemetry exists. Instead, detect likely observability gaps and tell the user what to verify or enable later.

**Work:**
- Add a report section that checks for the presence of:
  - Log Analytics workspaces
  - Application Insights
  - NSG flow log evidence where visible
  - Diagnostic settings / monitor resources where discoverable
- If telemetry is missing or inaccessible, output advisory guidance rather than failing
- Add clear text such as:
  - "No App Insights components found in scope"
  - "No Log Analytics workspace found for this application"
  - "Unable to confirm NSG flow logs with current permissions"
- Recommend next checks without attempting to change Azure

**Important:**
- This project should remain read-only
- Recommendations must be phrased as follow-up guidance, not automated actions

---

### Shared service and migration-wave analysis

**Priority:** High

Help migration teams understand what must move together and what is shared platform infrastructure.

**Work:**
- Detect probable shared services:
  - hub VNets
  - shared private DNS
  - shared Log Analytics
  - shared Key Vaults
  - shared App Configuration / registries / monitoring
- Flag cross-RG and cross-subscription dependencies prominently
- Add a "migration blockers / coupling" view:
  - shared dependencies
  - unresolved external references
  - dependencies outside the seed scope
- Add a first-pass move-group report:
  - application resources
  - shared platform dependencies
  - ambiguous / unknown dependencies

---

### Optional Entra ID enrichment with graceful fallback

**Priority:** Medium

If Entra ID visibility is available, enrich the output. If it is not, report the gap and continue.

**Work:**
- Detect and document managed identities and service principals where visible from ARM-side data
- If Graph / Entra access is available, optionally resolve principal display names and app registrations
- If not available, continue with object IDs and explicitly say identity detail is incomplete
- Add documentation around expected limitations under Global Reader-only access

---

### Migration-focused master report

**Priority:** Medium

Extend the existing reporting into a single migration-ready document for stakeholders with low Azure familiarity.

**Sections to add:**
- What was discovered
- Application boundary / tag grouping
- External exposure
- Key dependencies
- Shared platform dependencies
- Missing visibility / missing telemetry
- Recommended manual validation steps before migration
- Landing-zone fit observations

**Design goal:**
- The report should be understandable by delivery teams, architects, and project managers, not just Azure specialists.

---

## Icon Coverage

### Use Azure icons for unresolved resources when type is inferable

**Priority:** High

Unresolved / external placeholder nodes currently render as generic red ellipses even when the ARM ID is specific enough to infer an Azure resource type such as VNet, subnet, storage account, or Key Vault.

This loses useful visual context during migration analysis, especially when a dependency points to a shared platform resource outside the current subscription scope.

**Work:**
- Keep the external / unresolved semantics, but allow icon rendering when `_infer_type_from_id()` yields a known Azure resource type
- Preserve a clear visual distinction from in-scope resources, for example via border color, badge, or label suffix
- Fall back to the current external ellipse only when the type remains unknown
- Add tests covering inferred-type external nodes in the diagram output

---

### Expand `azure_icon_map.json` to cover all draw.io `azure2` icons

**Priority:** High

The built-in draw.io `azure2` shape library (`img/lib/azure2/`) ships SVGs for hundreds of Azure resource types. The current `azure_icon_map.json` only maps 18 types. Every unmapped type renders as a generic blue rectangle, which makes diagrams harder to read.

**Work:**
- Enumerate all SVGs available under `img/lib/azure2/` in draw.io desktop (compute, networking, databases, AI, IoT, integration, management, security, DevOps, identity, containers, storage, etc.)
- Map each SVG to its corresponding ARM resource type (e.g., `microsoft.documentdb/databaseaccounts` → `img/lib/azure2/databases/Azure_Cosmos_DB.svg`)
- Add entries to `assets/azure_icon_map.json`

**Types to add (non-exhaustive):**
- `microsoft.documentdb/databaseaccounts` — Cosmos DB
- `microsoft.eventhub/namespaces` — Event Hubs
- `microsoft.servicebus/namespaces` — Service Bus
- `microsoft.web/functions` / `microsoft.web/sites` (kind=functionapp) — Azure Functions
- `microsoft.apimanagement/service` — API Management
- `microsoft.cdn/profiles` — Front Door / CDN
- `microsoft.network/azurefirewalls` — Azure Firewall
- `microsoft.network/bastionhosts` — Bastion
- `microsoft.insights/components` — Application Insights
- `microsoft.operationalinsights/workspaces` — Log Analytics
- `microsoft.managedidentity/userassignedidentities` — Managed Identity
- `microsoft.dbformysql/flexibleservers` — MySQL Flexible Server
- `microsoft.dbforpostgresql/flexibleservers` — PostgreSQL Flexible Server
- `microsoft.cache/redis` — Azure Cache for Redis
- `microsoft.signalrservice/signalr` — SignalR
- `microsoft.cognitiveservices/accounts` — Cognitive Services / Azure OpenAI
- `microsoft.machinelearningservices/workspaces` — Machine Learning
- `microsoft.datafactory/factories` — Data Factory
- `microsoft.synapse/workspaces` — Synapse Analytics
- `microsoft.logic/workflows` — Logic Apps
- `microsoft.automation/automationaccounts` — Automation Account
- `microsoft.recoveryservices/vaults` — Recovery Services Vault
- `microsoft.devices/iothubs` — IoT Hub
- `microsoft.containerregistry/registries` — Container Registry
- `microsoft.app/containerapps` — Container Apps
- `microsoft.network/dnszones` — DNS Zone
- `microsoft.network/privatednszones` — Private DNS Zone
- `microsoft.network/trafficmanagerprofiles` — Traffic Manager
- `microsoft.network/expressroutecircuits` — ExpressRoute
- `microsoft.network/vpngateways` — VPN Gateway
- `microsoft.network/natgateways` — NAT Gateway
- `microsoft.monitor/accounts` — Azure Monitor

---

### Implement Microsoft icon ZIP fallback

**Priority:** High

When a resource type has no entry in `azure_icon_map.json` and no match in draw.io's built-in `azure2` library, the tool should fall back to Microsoft's official Azure Architecture Icons.

Microsoft publishes a ZIP of SVG icons at:
https://learn.microsoft.com/en-us/azure/architecture/icons/

**Work:**
- Download and extract the Microsoft icon ZIP into `assets/microsoft-azure-icons/` (or reference via config)
- Build an automated mapping from the SVG filenames in the ZIP to ARM resource types
- In `drawio.py`, when `_node_style()` finds no match in `azure_icon_map.json`, look up the Microsoft icon set
- Embed matched SVGs as base64 `data:image/svg+xml` in the draw.io cell style so the diagram is self-contained
- Populate `assets/azure-fallback.mxlibrary` (currently empty `[]`) with the fallback icons

---

## Layout Modes

### Add `SUBSCRIPTION>RG` layout mode

**Priority:** Medium

A subscription-centric view that groups resources by subscription, then by resource group. Useful for multi-subscription environments where the organizational hierarchy matters more than network topology.

### Force-directed layout option

**Priority:** Low

For complex topologies with many cross-cutting edges, a force-directed (spring) layout may produce more readable diagrams than the grid-based approaches. Could use a simple Fruchterman-Reingold implementation or integrate with an external layout engine.

---

## Diagram Enhancements

### ~~Spacing presets to fix label overlap~~ (Done)

**Priority:** ~~High~~ Completed

Added a `spacing` config field accepting `"compact"` (default) or `"spacious"` (1.8x gaps/padding). Spacious mode increases whitespace between icons in all three layout modes (BANDS, VNET>SUBNET, MSFT) without changing icon sizes. Tested with 50+ new tests covering config validation, gap scaling, label gap sufficiency, and no-overlap guarantees.

### ~~Production-grade AI architecture test fixture~~ (Done)

**Priority:** ~~High~~ Completed

Added `app_ai_chatbot.json` fixture modeling a Container Apps + Azure OpenAI + hub-spoke networking architecture (~30 resources across 2 resource groups). Exercises private endpoints, VNet peering, route tables, NSGs, and AI-specific resource types. Includes 31 tests covering graph construction, edge extraction, and diagram generation across all layout modes.

### Auto-generated legend

**Priority:** Medium

Add a legend box to the generated diagram that maps each icon to its resource type. Should be auto-generated from the icons actually used in the diagram (from `icons_used.json`).

### Additional spacing presets

**Priority:** Low

The current `spacing` field supports `"compact"` and `"spacious"`. Future presets could include:
- `"presentation"` — Extra-wide gaps optimized for slides and screen-sharing (e.g., 2.5x)
- `"wide"` — Wider horizontal gaps only, keeping vertical gaps compact (useful for very long resource names)
- Custom numeric multiplier override for power users (e.g., `"spacing": 1.5`)

### Configurable grid column count

**Priority:** Low

Allow `config.json` to override the default 6-column wrap limit in the `REGION>RG>TYPE` layout. Useful for very wide or very narrow diagrams.

### Subscription and region containers in VNET>SUBNET mode

**Priority:** Medium

Wrap VNet containers in subscription and/or region containers for multi-subscription, multi-region environments.

---

## Diff and Change Tracking

### Diff mode

**Priority:** Medium

Compare two `inventory.json` snapshots and produce a diagram that highlights added (green), removed (red), and changed (yellow) resources. Useful for reviewing infrastructure changes before and after a deployment.

---

## RBAC Enhancements

### Resolve role definition IDs to role names

**Priority:** Medium

When `includeRbac` is enabled, the tool queries `authorizationresources` for role assignments and creates `rbac_assignment` edges in the graph. However, the role assignments only contain the raw role definition ID (e.g., `/subscriptions/.../providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7`), not the human-readable role name (e.g., "Reader").

**Work:**
- Query `authorizationresources` for `microsoft.authorization/roledefinitions` to build a role definition ID → role name lookup table
- Enrich each role assignment node with the resolved role name (e.g., "Contributor", "Reader", "Network Contributor")
- Display the role name as a node label or attribute in the diagram instead of the raw GUID
- Include role names in `rbac.json` output

### Generate a Markdown RBAC report

**Priority:** Medium

Add a dedicated section in `docs.py` that generates a Markdown RBAC summary (similar to how `routing.md` documents UDRs and NSGs). This would make role assignments easy to review without inspecting raw JSON.

**Work:**
- Add an `_write_rbac()` function in `docs.py` that reads `rbac.json` and produces `rbac.md`
- Include a summary (total assignments, unique principals, unique roles)
- Group assignments by scope (resource group or resource) with a table showing principal ID, role name, and assignment type (direct vs inherited)
- Depends on role definition ID resolution (above) for human-readable role names

---

## Data Enrichment

### Cost annotations

**Priority:** Medium

Integrate with Azure Cost Management API to annotate resources with their monthly spend. Could show cost as a label, tooltip, or color gradient.

### Tag-based filtering and coloring

**Priority:** Medium

Allow `config.json` to specify tag filters (include/exclude resources by tag) and color rules (e.g., `"environment=prod"` → red border, `"environment=dev"` → green border).

### Observed-vs-inferred dependency evidence

**Priority:** Medium

Add metadata to relationships so reports can distinguish:
- configuration-derived dependencies
- telemetry-observed dependencies
- RBAC / identity relationships
- unresolved or external references

This would make migration reports more trustworthy for teams with limited Azure knowledge.

---

## Edge Extraction

### Custom edge rules

**Priority:** Low

Allow users to define additional edge extraction rules in `config.json` for resource types not yet supported by the built-in `extract_edges()` function. For example:

```json
{
  "customEdges": [
    {
      "sourceType": "microsoft.network/frontdoors",
      "propertyPath": "properties.backendPools[].backends[].address",
      "kind": "frontDoor->backend"
    }
  ]
}
```

---

## Export and Integration

### Multi-format export

**Priority:** Low

Generate diagrams in additional formats beyond draw.io XML:
- Mermaid (for GitHub/GitLab Markdown rendering)
- PlantUML
- Terraform graph-compatible DOT format
- Visio (VSDX)

### Live sync

**Priority:** Low

Watch for Azure resource changes (via Azure Event Grid or polling) and auto-update diagrams. Could run as a daemon or scheduled GitHub Action.

### Web UI

**Priority:** Low

Browser-based interface for:
- Uploading/editing `config.json`
- Previewing diagrams without the CLI
- Selecting layout modes interactively
- Filtering resources by type, tag, or region

---

## Security and Compliance Visualization

### Policy visualization

**Priority:** Low

Overlay Azure Policy assignments and compliance state onto the diagram. Non-compliant resources could be highlighted with a warning badge.

### Private link topology view

**Priority:** Low

A dedicated layout mode showing private endpoint chains across VNets and subscriptions, with DNS resolution paths and private DNS zone associations.


---
# Brain dump prompts. 

```
Add a feature to create a master report that consolidates, links, and explains all discovery output for architecture documentation or migration preparation.
It needs to:
Identify all relevant discovery outputs and their formats (e.g., JSON, diagrams, logs).
Structure the report with clear sections for each type of information (inventory, topology, dependencies, routing, etc.).
Link to or embed each output, with explanations for context.
Ensure the report is easy to navigate and suitable for migration or architecture review.
Start by exploring the discover.py and related files to understand what outputs are generated, then draft a plan for the report structure.
```
