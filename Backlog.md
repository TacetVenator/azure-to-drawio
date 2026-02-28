# Backlog

Planned improvements and future work for azure-to-drawio, roughly ordered by priority.

---

## Icon Coverage

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

### Auto-generated legend

**Priority:** Medium

Add a legend box to the generated diagram that maps each icon to its resource type. Should be auto-generated from the icons actually used in the diagram (from `icons_used.json`).

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
