# azure-to-drawio

Automatically discover Azure resources via [Azure Resource Graph](https://learn.microsoft.com/en-us/azure/governance/resource-graph/) and generate fully-editable [draw.io](https://app.diagrams.net) architecture diagrams — complete with official Azure icons, relationship edges, and network topology containers.

## How It Works

```
Azure Resource Graph  ──►  Seed  ──►  Expand  ──►  RBAC  ──►  Graph  ──►  Draw.io  ──►  Docs
    (az graph query)       │           │            │          │            │              │
                           ▼           ▼            ▼          ▼            ▼              ▼
                       seed.json   inventory.json  rbac.json  graph.json  diagram.drawio  catalog.md
                                   unresolved.json                        diagram.svg     edges.md
                                                                          diagram.png     routing.md
                                                                          icons_used.json
```

The tool runs a six-stage pipeline. Each stage reads the previous stage's output from the configured `outputDir`, so stages can be re-run independently:

1. **Seed** — Queries Azure Resource Graph (ARG) for all resources in the configured resource groups. Writes `seed.json`.
2. **Expand** — Reads `seed.json`, recursively extracts ARM ID references from resource properties, and fetches any resources not yet collected. Iterates up to 50 rounds until no new IDs are found. Writes `inventory.json` (the full resource set) and `unresolved.json` (IDs referenced but not found in Azure).
3. **RBAC** *(optional, `includeRbac: true`)* — Reads `inventory.json`, queries `authorizationresources` for role assignments scoped to discovered resources, and writes `rbac.json`.
4. **Graph** — Reads `inventory.json`, `unresolved.json`, and optionally `rbac.json`. Builds a normalized graph model: separates parent and child resources, merges children (VM extensions, SQL firewall rules, etc.) into parent node attributes, extracts typed edges from resource properties, and adds placeholder nodes for unresolved external references. Writes `graph.json`.
5. **Draw.io** — Reads `graph.json` and the icon map from `assets/azure_icon_map.json`. Computes a deterministic layout (either `REGION>RG>TYPE` or `VNET>SUBNET`), generates draw.io XML with positioned nodes, styled icons, edges, UDR callout boxes, and attribute info boxes. Writes `diagram.drawio` and `icons_used.json`. If the `drawio` CLI is on `PATH`, also exports `diagram.svg` and `diagram.png`.
6. **Docs** — Reads `graph.json` and `unresolved.json`. Generates three Markdown reports: `catalog.md`, `edges.md`, and `routing.md`.

---

## Prerequisites

- **Python 3.11+** — no third-party packages required (uses only the standard library)
- **Azure CLI** (`az`) — authenticated with access to your target subscriptions. The tool calls `az graph query` under the hood.
- **draw.io Desktop CLI** *(optional)* — for automatic SVG/PNG export. Install [drawio-desktop](https://github.com/jgraph/drawio-desktop/releases) and ensure the `drawio` binary is on your `PATH`.

---

## Usage

### Synopsis

```
python3 -m tools.azdisc [-v] <command> <config.json>
```

### Global Options

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable debug-level logging (outputs to stderr). Without this flag, only INFO and above are shown. |

### Commands

#### `run` — Run the full pipeline

Executes all six stages in order: seed, expand, rbac, graph, drawio, docs.

```bash
python3 -m tools.azdisc run app/myapp/config.json
```

This is the most common way to use the tool. A single command produces the complete diagram and all documentation from scratch.

#### `seed` — Seed resources from resource groups

Queries Azure Resource Graph for all resources in the configured `seedResourceGroups` and writes `seed.json` to the output directory.

```bash
python3 -m tools.azdisc seed app/myapp/config.json
```

The underlying Kusto query is:

```kusto
resources
| where resourceGroup in~ ('rg-app-dev', 'rg-app-prod')
| project id, name, type, location, subscriptionId, resourceGroup, properties
```

ARG results are automatically paged (1000 rows per page) and batched across all configured subscriptions.

**Requires:** Azure CLI authenticated (`az login`).
**Produces:** `seed.json`

#### `expand` — Transitively expand resources

Reads `seed.json` and recursively discovers related resources by scanning all ARM ID references embedded in resource properties. Resources referenced but not yet collected are fetched from ARG in batches of 200 IDs. This loop repeats (up to 50 iterations) until convergence — i.e., no new IDs are found.

```bash
python3 -m tools.azdisc expand app/myapp/config.json
```

This stage is what makes the tool discover resources across resource group boundaries. For example, if a NIC in `rg-app-prod` references a subnet in `rg-network-shared`, the expand stage will automatically fetch that subnet even though it was not in the seed list.

IDs that match non-resource patterns (marketplace image references, location metadata, role/policy definitions) are automatically filtered out.

**Requires:** `seed.json` in the output directory, Azure CLI authenticated.
**Produces:** `inventory.json`, `unresolved.json`

#### `graph` — Build graph model

Reads `inventory.json` and builds a normalized graph of nodes and edges.

```bash
python3 -m tools.azdisc graph app/myapp/config.json
```

This stage:
- Separates child resources (e.g., `microsoft.compute/virtualmachines/extensions`) from parent resources and merges them as attributes on the parent node
- Extracts typed edges from each resource's `properties` (see [Relationship Edges](#relationship-edges))
- Collects display attributes for each node (VM size, OS image, SQL SKU, etc.)
- Adds placeholder nodes (marked `isExternal: true`) for any IDs in `unresolved.json`
- If `rbac.json` exists, adds `rbac_assignment` edges

**Requires:** `inventory.json` in the output directory.
**Produces:** `graph.json`

#### `drawio` — Generate draw.io diagram

Reads `graph.json` and produces the draw.io XML diagram.

```bash
python3 -m tools.azdisc drawio app/myapp/config.json
```

The layout algorithm is determined by the `layout` field in your config file (see [Layout Modes](#layout-modes)). If the `drawio` CLI is available on `PATH`, SVG and PNG exports are produced automatically.

**Requires:** `graph.json` in the output directory.
**Produces:** `diagram.drawio`, `icons_used.json`, and optionally `diagram.svg`, `diagram.png`

#### `docs` — Generate documentation

Reads `graph.json` and produces three Markdown reports.

```bash
python3 -m tools.azdisc docs app/myapp/config.json
```

**Requires:** `graph.json` in the output directory.
**Produces:** `catalog.md`, `edges.md`, `routing.md`

### Typical Workflows

**Full run from scratch:**

```bash
python3 -m tools.azdisc run app/myapp/config.json
```

**Re-generate diagram after changing layout mode (no Azure re-query):**

```bash
# Edit config.json to change layout from REGION>RG>TYPE to VNET>SUBNET
python3 -m tools.azdisc drawio app/myapp/config.json
```

**Re-build graph and diagram after manually editing inventory.json:**

```bash
python3 -m tools.azdisc graph app/myapp/config.json
python3 -m tools.azdisc drawio app/myapp/config.json
```

**Generate only documentation, skip diagram:**

```bash
python3 -m tools.azdisc seed app/myapp/config.json
python3 -m tools.azdisc expand app/myapp/config.json
python3 -m tools.azdisc graph app/myapp/config.json
python3 -m tools.azdisc docs app/myapp/config.json
```

**Verbose mode for debugging:**

```bash
python3 -m tools.azdisc -v run app/myapp/config.json
```

---

## Configuration

### Config File Format

The tool reads a JSON configuration file. An example is provided at `app/myapp/config.json`:

```json
{
  "app": "myapp",
  "subscriptions": ["<sub1>", "<sub2>"],
  "seedResourceGroups": ["rg-app-dev", "rg-app-prod"],
  "outputDir": "app/myapp/out",
  "includeRbac": true,
  "layout": "REGION>RG>TYPE"
}
```

### Config Fields

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `app` | `string` | Yes | — | Application name. Used as the diagram tab label in draw.io. |
| `subscriptions` | `string[]` | Yes | — | List of Azure subscription IDs to query. Passed to `az graph query --subscriptions`. |
| `seedResourceGroups` | `string[]` | Yes | — | Resource group names to seed initial discovery from. All resources in these RGs are fetched. |
| `outputDir` | `string` | Yes | — | Directory where all output files are written. Created automatically if it does not exist. |
| `includeRbac` | `bool` | No | `false` | When `true`, the RBAC stage queries `authorizationresources` for role assignments and adds `rbac_assignment` edges to the graph. |
| `layout` | `string` | No | `"REGION>RG>TYPE"` | Diagram layout mode. Must be one of: `"REGION>RG>TYPE"`, `"VNET>SUBNET"`. See [Layout Modes](#layout-modes). |

---

## Layout Modes

### `REGION>RG>TYPE` (Default)

Organizes resources in a hierarchical grid:

```
Region
└── Resource Group
    └── Resource Type Band
        └── Resources (left-to-right grid, wrapping at 6 columns)
```

Resources are grouped by region, then by resource group, then by Azure resource type. Within each type band, individual resources are laid out left-to-right in a grid that wraps after 6 columns. Resource groups are placed side by side; regions stack vertically.

**Best for:** General-purpose infrastructure overviews, multi-region deployments, resource auditing.

### `VNET>SUBNET`

Organizes resources by network topology using nested container boxes:

```
┌─ VNet: vnet-prod ─────────────────────────────────┐
│  ┌─ Subnet: snet-web ──┐  ┌─ Subnet: snet-app ─┐ │
│  │  vm-web-01           │  │  vm-app-01          │ │
│  │  nic-web-01          │  │  nic-app-01         │ │
│  │  nsg-web             │  │  nsg-app            │ │
│  └──────────────────────┘  └─────────────────────┘ │
└────────────────────────────────────────────────────┘
┌─ Other Resources ──────┐
│  kv-prod   stprod       │
└─────────────────────────┘
```

VNets become large container boxes; subnets become nested container boxes inside their VNet. Individual resources are placed inside the subnet they belong to, using edge relationships to determine membership:

| Resource Type | Placement Rule |
|---------------|----------------|
| VMs | Placed via VM → NIC → Subnet chain |
| NICs | Placed via NIC → Subnet IP configuration reference |
| Private Endpoints | Placed via their `subnet` property |
| Web Apps | Placed via VNet integration `virtualNetworkSubnetId` |
| NSGs | Placed in the subnet they're associated with (via `subnet->nsg` edge) |
| Route Tables | Placed in the subnet they're associated with (via `subnet->routeTable` edge) |
| Load Balancers | Placed in the subnet of their backend NIC |
| Public IPs | Placed in the subnet of their attached NIC |
| PE targets (e.g., SQL Server) | Placed in the same subnet as the Private Endpoint that connects to them |

Resources not attached to any subnet are collected into an "Other Resources" container.

In this mode, VNet and subnet nodes are rendered as containers rather than icons — they do not appear as separate icon cells.

**Best for:** Network architecture diagrams, security reviews, subnet capacity planning.

---

## Output Artifacts

All output files are written to the directory specified by `outputDir` in your config. Below is an exhaustive description of every file produced by the pipeline.

### `seed.json`

**Produced by:** `seed` stage
**Format:** JSON array of Azure resource objects

Contains the raw resources returned by the initial Azure Resource Graph query. Each object has the fields projected by ARG: `id`, `name`, `type`, `location`, `subscriptionId`, `resourceGroup`, `properties`.

```json
[
  {
    "id": "/subscriptions/.../resourceGroups/rg-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01",
    "name": "vm-web-01",
    "type": "Microsoft.Compute/virtualMachines",
    "location": "eastus",
    "subscriptionId": "...",
    "resourceGroup": "rg-prod",
    "properties": { "hardwareProfile": { "vmSize": "Standard_D4s_v3" }, ... }
  },
  ...
]
```

### `inventory.json`

**Produced by:** `expand` stage
**Format:** JSON array of Azure resource objects (same schema as `seed.json`)

The complete, deduplicated set of all discovered resources — both seeded and transitively expanded. Sorted by normalized resource ID. This file is the primary input for the `graph` stage.

### `unresolved.json`

**Produced by:** `expand` stage
**Format:** JSON array of ARM ID strings

Lists ARM resource IDs that were referenced in resource properties but could not be found via ARG queries. These typically represent resources in other subscriptions you don't have access to, recently deleted resources, or cross-tenant references. Sorted alphabetically.

```json
[
  "/subscriptions/abc/resourcegroups/rg-shared/providers/microsoft.network/virtualnetworks/vnet-hub",
  ...
]
```

In the `graph` stage, these IDs become placeholder nodes marked `isExternal: true` and rendered as red ellipses in the diagram.

### `rbac.json`

**Produced by:** `run` (RBAC sub-stage, only when `includeRbac: true`)
**Format:** JSON array of role assignment resource objects

Contains Azure role assignments (`microsoft.authorization/roleassignments`) whose scope matches any discovered resource or resource group. Each object has `id`, `name`, `type`, and `properties` (which includes `scope`, `roleDefinitionId`, `principalId`, etc.).

### `graph.json`

**Produced by:** `graph` stage
**Format:** JSON object with two top-level keys: `nodes` and `edges`

The normalized graph model consumed by the `drawio` and `docs` stages.

**Node schema:**
```json
{
  "id": "/subscriptions/.../providers/microsoft.compute/virtualmachines/vm-web-01",
  "stableId": "a1b2c3d4e5f67890",
  "name": "vm-web-01",
  "type": "microsoft.compute/virtualmachines",
  "location": "eastus",
  "resourceGroup": "rg-prod",
  "subscriptionId": "...",
  "properties": { ... },
  "isExternal": false,
  "childResources": [
    { "name": "MDE.Linux", "type": "microsoft.compute/virtualmachines/extensions", "properties": { ... } }
  ],
  "attributes": ["SKU: Standard_D4s_v3", "Image: Canonical/UbuntuServer/18.04-LTS", "OS: Linux", "extensions: MDE.Linux"]
}
```

- `stableId` — A deterministic 16-character hex hash of the lowercase resource ID, used as the cell ID in draw.io XML to ensure stable diagrams across re-runs.
- `isExternal` — `true` for unresolved placeholder nodes.
- `childResources` — Child resources merged into this parent (VM extensions, SQL firewall rules, SQL administrators, NSG security rules).
- `attributes` — Human-readable display strings shown in the attribute info box on the diagram.

**Edge schema:**
```json
{
  "source": "/subscriptions/.../virtualmachines/vm-web-01",
  "target": "/subscriptions/.../networkinterfaces/nic-web-01",
  "kind": "vm->nic"
}
```

Edges are sorted by `(source, target, kind)` and deduplicated.

### `diagram.drawio`

**Produced by:** `drawio` stage
**Format:** draw.io XML (`mxfile` format)

The main diagram output. This is a standard draw.io file that can be opened in:
- [app.diagrams.net](https://app.diagrams.net) (online editor)
- [draw.io Desktop](https://github.com/jgraph/drawio-desktop/releases) (offline)
- VS Code with the [Draw.io Integration](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio) extension

The file contains:
- **Vertex cells** — One per resource, positioned by the layout engine, styled with the Azure icon from `azure_icon_map.json` (or a generic rounded rectangle for unmapped types, or a red ellipse for external references).
- **Edge cells** — Orthogonal connector lines labeled with the edge kind (e.g., `vm->nic`). Route table edges are excluded from direct rendering — they are shown as UDR callout boxes instead.
- **Container cells** *(VNET>SUBNET mode only)* — Non-connectable group cells for VNets and subnets that visually nest their member resources.
- **UDR callout boxes** — For each route table that has defined routes, a callout shape listing each route's `addressPrefix → nextHopType`. Connected to the associated subnet with a "UDR" labeled edge.
- **Attribute info boxes** — Purple rounded rectangles placed to the left of resource icons, showing key properties (VM SKU, OS image, SQL tier, child resource names). Connected to the resource with a dashed edge.

### `diagram.svg`

**Produced by:** `drawio` stage (only if the `drawio` CLI is on `PATH`)
**Format:** SVG image

An SVG vector export of the diagram, suitable for embedding in wikis, docs, or web pages.

### `diagram.png`

**Produced by:** `drawio` stage (only if the `drawio` CLI is on `PATH`)
**Format:** PNG image

A rasterized export of the diagram, suitable for embedding in Markdown, Confluence pages, or slide decks.

### `icons_used.json`

**Produced by:** `drawio` stage
**Format:** JSON object with three keys

Reports which Azure icon styles were used, for auditing and extending icon coverage:

```json
{
  "mapped": {
    "microsoft.compute/virtualmachines": 2,
    "microsoft.network/networkinterfaces": 2,
    ...
  },
  "fallback": [],
  "unknown": ["microsoft.insights/components"]
}
```

- `mapped` — Resource types that matched an entry in `azure_icon_map.json`, with instance counts.
- `fallback` — Types matched via partial suffix matching (last path segment of the type string).
- `unknown` — Types with no icon match at all, rendered with the generic rounded-rectangle style. Use this list to identify which types to add to `azure_icon_map.json`.

### `catalog.md`

**Produced by:** `docs` stage
**Format:** Markdown

A resource catalog table listing every resource type discovered, with columns for count, regions, resource groups, and subscriptions. Titled with the app name from config.

Example output:

```markdown
# Resource Catalog — myapp

| type | count | regions | resource groups | subscriptions |
|------|-------|---------|-----------------|---------------|
| `microsoft.compute/disks` | 3 | eastus | rg-prod | sub-1 |
| `microsoft.compute/virtualmachines` | 2 | eastus | rg-prod | sub-1 |
| ...  | ...   | ...     | ...             | ...           |
```

### `edges.md`

**Produced by:** `docs` stage
**Format:** Markdown

Edge analysis report containing:

1. **Edge Counts by Kind** — Table of each edge type and how many instances were found.
2. **Top 20 Nodes by Degree** — Table of the 20 most-connected resources (by total in-degree + out-degree), showing name, full ARM ID, and degree count.
3. **External Placeholders** — Count of external/unresolved nodes.
4. **Unresolved References** — The first 50 unresolved ARM IDs (from `unresolved.json`).

### `routing.md`

**Produced by:** `docs` stage
**Format:** Markdown

Network routing and security details:

1. **User-Defined Routes (UDR)** — For each subnet that has an associated route table, lists the route table ID and a table of all routes with `destination`, `nextHopType`, and `nextHopIp`.
2. **Network Security Groups** — For each NSG, lists inbound and outbound security rules in a table with `name`, `priority`, `protocol`, `src`, `dst`, and `action`. Rules are sorted by priority.

---

## Diagram Features

### Relationship Edges

The graph builder extracts 15 typed edge kinds from resource properties:

| Edge Kind | Source Type | Meaning |
|-----------|-------------|---------|
| `vm->nic` | `virtualmachines` | VM references a network interface in `networkProfile.networkInterfaces` |
| `vm->disk` | `virtualmachines` | VM references OS or data disk in `storageProfile.osDisk.managedDisk` or `storageProfile.dataDisks[].managedDisk` |
| `nic->subnet` | `networkinterfaces` | NIC IP configuration references a subnet in `ipConfigurations[].properties.subnet` |
| `nic->nsg` | `networkinterfaces` | NIC references an NSG in `networkSecurityGroup` |
| `subnet->vnet` | `subnets` | Subnet belongs to a VNet (derived from the ARM ID path) |
| `subnet->nsg` | `subnets` | Subnet references an NSG in `networkSecurityGroup` |
| `subnet->routeTable` | `subnets` | Subnet references a route table in `routeTable` |
| `vnet->peeredVnet` | `virtualnetworks` | VNet peering in `virtualNetworkPeerings[].properties.remoteVirtualNetwork` |
| `privateEndpoint->subnet` | `privateendpoints` | Private endpoint is in a subnet via `subnet` property |
| `privateEndpoint->target` | `privateendpoints` | Private endpoint connects to a service via `privateLinkServiceConnections[].properties.privateLinkServiceId` |
| `loadBalancer->backendNic` | `loadbalancers` | LB backend pool references a NIC via `backendAddressPools[].properties.backendIPConfigurations[].id` |
| `publicIp->attachment` | `publicipaddresses` | Public IP is attached to a NIC via `ipConfiguration.id` |
| `webApp->appServicePlan` | `web/sites` | Web app runs on a plan via `serverFarmId` |
| `webApp->subnet` | `web/sites` | Web app has VNet integration via `virtualNetworkSubnetId` |
| `rbac_assignment` | *(RBAC scope)* | RBAC role assignment scope edge (only when `includeRbac: true`) |

### UDR Callout Boxes

Route tables that contain defined routes are rendered with a special callout shape showing each route entry:

```
Routes:
  10.0.0.0/8 → VirtualAppliance(10.1.0.4)
  0.0.0.0/0 → Internet
```

The callout is connected to the associated subnet with a "UDR" labeled edge. The `subnet->routeTable` edge is not drawn separately — it is replaced by this callout visualization.

### Attribute Info Boxes

Resources with notable properties get a purple info box placed to the left of their icon, connected by a dashed edge. The following attributes are extracted:

| Resource Type | Attributes Shown |
|---------------|------------------|
| Virtual Machines | `SKU: Standard_D4s_v3`, `Image: Canonical/UbuntuServer/18.04-LTS`, `OS: Linux` |
| SQL Servers / Databases | `SKU: GP_Gen5`, `Tier: GeneralPurpose` |
| Any resource with children | `extensions: MDE.Linux`, `firewallRules: AllowAzure`, `administrators: admin@contoso.com` |

### Child Resource Merging

Resources whose ARM type has 3+ path segments after the provider (e.g., `microsoft.compute/virtualmachines/extensions`) are treated as child resources. They are not rendered as separate diagram nodes. Instead, they are merged into their parent node's `childResources` list and displayed as attribute annotations.

The following types are always treated as child resources:

- `microsoft.compute/virtualmachines/extensions`
- `microsoft.sql/servers/firewallrules`
- `microsoft.sql/servers/administrators`
- `microsoft.network/networksecuritygroups/securityrules`
- `microsoft.network/virtualnetworks/subnets/providers`

Additionally, any non-`microsoft.network` type with 3+ segments (e.g., `microsoft.foo/bar/baz`) is heuristically classified as a child resource.

**Exception:** `microsoft.network/virtualnetworks/subnets` is intentionally kept as a standalone node, not merged.

### Icon Matching

For each resource, the draw.io style is resolved in this order:

1. **Exact match** — The full lowercase type string is looked up in `assets/azure_icon_map.json`.
2. **Suffix match** — If no exact match, the last path segment of the type is tried (e.g., for `microsoft.foo/bar/loadbalancers`, it tries `loadbalancers`).
3. **Fallback** — If neither matches, a generic blue rounded rectangle is used.
4. **External** — Unresolved/external nodes use a red ellipse style.

### Transitive Discovery

The expand stage follows ARM ID references recursively (up to 50 iterations) until no new resources are found. ARM IDs are extracted from all string values in resource properties using a regex pattern. The following non-resource patterns are automatically filtered out:

- `microsoft.compute/locations/*` (marketplace/region metadata)
- `microsoft.compute/galleries/*` (image gallery references)
- `microsoft.marketplace/*`
- `microsoft.compute/images/*`
- `microsoft.authorization/roleDefinitions/*`
- `microsoft.authorization/policyDefinitions/*`

---

## Supported Azure Resource Types (Icons)

The tool discovers and renders any Azure resource type. The following 18 types have dedicated Azure icons mapped in `assets/azure_icon_map.json`:

| Resource Type | Icon | Category |
|---------------|------|----------|
| `microsoft.compute/virtualmachines` | Virtual Machine | Compute |
| `microsoft.compute/disks` | Managed Disk | Compute |
| `microsoft.containerservice/managedclusters` | Kubernetes Service (AKS) | Containers |
| `microsoft.network/virtualnetworks` | Virtual Network | Networking |
| `microsoft.network/virtualnetworks/subnets` | Subnet | Networking |
| `microsoft.network/networkinterfaces` | Network Interface | Networking |
| `microsoft.network/networksecuritygroups` | Network Security Group | Networking |
| `microsoft.network/routetables` | Route Table | Networking |
| `microsoft.network/loadbalancers` | Load Balancer | Networking |
| `microsoft.network/publicipaddresses` | Public IP Address | Networking |
| `microsoft.network/privateendpoints` | Private Endpoint | Networking |
| `microsoft.network/applicationgateways` | Application Gateway | Networking |
| `microsoft.web/sites` | App Service | App Services |
| `microsoft.web/serverfarms` | App Service Plan | App Services |
| `microsoft.storage/storageaccounts` | Storage Account | Storage |
| `microsoft.keyvault/vaults` | Key Vault | Security |
| `microsoft.sql/servers` | SQL Server | Databases |
| `microsoft.sql/servers/databases` | SQL Database | Databases |

To add icons for additional resource types, add entries to `assets/azure_icon_map.json`. The key is the lowercase ARM resource type; the value is a draw.io style string referencing an SVG from the built-in `azure2` shape library. Check `icons_used.json` after a run to see which types have `"unknown"` mappings.

---

## Project Structure

```
azure-to-drawio/
├── tools/azdisc/                      # Main Python package
│   ├── __main__.py                    # CLI entry point: argument parsing and subcommand dispatch
│   ├── arg.py                         # Azure Resource Graph query wrapper (paging, batching via az CLI)
│   ├── config.py                      # Config dataclass, JSON loader, layout validation
│   ├── discover.py                    # Seed, transitive expand, and RBAC discovery stages
│   ├── graph.py                       # Graph model: node/edge extraction, child merging, attributes
│   ├── drawio.py                      # Draw.io XML generation, both layout engines, image export
│   ├── docs.py                        # Markdown documentation generators (catalog, edges, routing)
│   ├── util.py                        # ARM ID regex, normalization, stable ID hashing, logging setup
│   └── tests/
│       ├── fixtures/
│       │   ├── app_contoso.json       # Realistic 3-tier app: VNet, subnets, VMs, SQL, LB, PE, NSGs
│       │   └── inventory_small.json   # Smaller fixture covering all edge types
│       ├── test_ids.py                # ARM ID parsing, normalization, stable ID determinism
│       ├── test_graph_edges.py        # Edge extraction: all 15 edge kinds
│       ├── test_child_resources.py    # Child resource detection, parent merging, attribute collection
│       ├── test_layout.py             # REGION>RG>TYPE: determinism, positive coords, no overlaps
│       ├── test_vnet_layout.py        # VNET>SUBNET: containers, nesting, labels, determinism
│       └── test_integration.py        # Full pipeline: graph build → drawio XML → PNG export
├── assets/
│   ├── azure_icon_map.json            # Azure resource type → draw.io style string mapping (18 types)
│   └── azure-fallback.mxlibrary       # Fallback icon library (placeholder for future use)
├── app/myapp/
│   └── config.json                    # Example configuration file
└── .github/workflows/
    └── tests.yml                      # CI: pytest, diagram generation, artifact upload, PR comment
```

---

## Running Tests

```bash
pip install pytest
python -m pytest tools/azdisc/tests/ -v
```

All tests run entirely offline using fixture data — no Azure credentials or network access required. The test suite covers:

- **ARM ID parsing** — Regex extraction from strings/dicts/lists, normalization, deduplication, non-resource filtering
- **Stable IDs** — Determinism, fixed length (16 hex chars), case insensitivity
- **Edge extraction** — All 15 edge kinds individually, sort order, no duplicates
- **Child resources** — Type detection heuristic, parent ID derivation, attribute collection (VM SKU/image, SQL SKU)
- **Layout engines** — Both `REGION>RG>TYPE` and `VNET>SUBNET`: determinism, positive coordinates, no overlapping nodes, correct cell dimensions
- **VNET>SUBNET containers** — VNet/subnet container cells exist, correct parent nesting, expected labels
- **Full integration** — Fixture → `build_graph` → `generate_drawio` → validates XML structure, vertex/edge cell counts, geometry, node labels
- **PNG/SVG export** — When the `drawio` CLI is available: valid PNG header, SVG file created. Graceful skip when CLI is absent.

---

## CI / GitHub Actions

The workflow at `.github/workflows/tests.yml` runs on every push and pull request to `main`:

1. Sets up Python 3.11 and installs `pytest`
2. Installs the draw.io Desktop CLI (with an `xvfb-run` wrapper for headless export)
3. Runs the full pytest suite
4. Generates an integration diagram from the `app_contoso.json` fixture
5. Uploads `diagram.drawio`, `diagram.svg`, and `diagram.png` as GitHub Actions artifacts
6. On pull requests, posts (or updates) a comment with diagram statistics (node/edge count, PNG size) and a link to download the artifacts

---

## Next Steps and Future Improvements

### Near-Term

- **More icon mappings** — Expand `azure_icon_map.json` to cover Cosmos DB, Event Hubs, Service Bus, Azure Functions, API Management, Front Door, Azure Firewall, Bastion, Azure Monitor, and more
- **Subscription/region grouping in VNET>SUBNET mode** — Wrap VNets in subscription or region containers for multi-subscription environments
- **Auto-generated legend** — Add a legend box to the diagram mapping icons to resource types
- **Configurable grid columns** — Allow `config.json` to override the default 6-column wrap limit

### Medium-Term

- **Additional layout modes** — `SUBSCRIPTION>RG` for subscription-centric views; force-directed layout for complex topologies
- **Diff mode** — Compare two inventory snapshots and highlight added/removed/changed resources
- **Cost annotations** — Integrate Azure Cost Management data to annotate resources with monthly spend
- **Tag-based filtering and coloring** — Filter resources by Azure tags or apply color-coding based on tag values
- **Custom edge rules** — User-defined edge extraction rules in config for resource types not yet supported

### Long-Term Vision

- **Live sync** — Watch for Azure resource changes and auto-update diagrams
- **Multi-format export** — Generate Mermaid, PlantUML, or Terraform-graph-compatible output
- **Web UI** — Browser-based interface for configuring, previewing, and editing diagrams
- **Policy visualization** — Overlay Azure Policy assignments and compliance state
- **Private link topology** — Dedicated view showing private endpoint chains across VNets and subscriptions
