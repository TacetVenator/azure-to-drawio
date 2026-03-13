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
5. **Draw.io** — Reads `graph.json` and the icon map from `assets/azure_icon_map.json`. Computes a deterministic layout (`REGION>RG>TYPE`, `VNET>SUBNET`, or `SUB>REGION>RG>NET`), generates draw.io XML with positioned nodes, styled icons, edges, UDR callout boxes, and attribute info boxes. Writes `diagram.drawio` and `icons_used.json`. If the `drawio` CLI is on `PATH`, also exports `diagram.svg` and `diagram.png`.
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

#### `render-all` — Generate all layout × mode variants

Reads the existing `graph.json` from your output directory and generates diagrams for every combination of layout and diagram mode. Each variant is written to a `variants/<layout>_<mode>/` subfolder alongside your primary output.

```bash
python3 -m tools.azdisc render-all app/myapp/config.json
```

This produces 6 variants (3 layouts × 2 modes) so you can compare how your architecture looks in each combination without modifying your primary config. Your original output files remain untouched.

**Requires:** `graph.json` in the output directory (run `graph` or `run` first).
**Produces:** `variants/` directory with subfolders for each combination.

#### `report-all` — Generate a Markdown report of all diagram variants

Reads the existing `graph.json` from your output directory and generates all 12 combinations of layout, diagram mode, and spacing preset (3 × 2 × 2). Each variant is written to a `variants/<layout>_<mode>_<spacing>/` subfolder, and a single `variants/report.md` is produced that links to every variant — embedding PNG previews where the `drawio` CLI is available.

```bash
python3 -m tools.azdisc report-all app/myapp/config.json
```

**Requires:** `graph.json` in the output directory (run `graph` or `run` first).
**Produces:**
- `variants/<layout>_<mode>_<spacing>/` — one subfolder per combination, each containing `diagram.drawio`, `icons_used.json`, `catalog.md`, `edges.md`, `routing.md`, and optionally `diagram.svg` / `diagram.png`
- `variants/report.md` — a single Markdown document with a section per variant, PNG embed (if available), and a link to the `.drawio` file

#### `test-all` — Render all fixtures × layouts × modes

Exercises every combination against the bundled test fixtures. No Azure credentials needed — useful for CI and development.

```bash
python3 -m tools.azdisc test-all [output_dir]
```

**Produces:** `<output_dir>/<fixture>/<layout>_<mode>/` directories with full diagram + docs output.

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

**Generate a Markdown report of all 12 diagram variants (layout × mode × spacing):**

```bash
python3 -m tools.azdisc run app/myapp/config.json
python3 -m tools.azdisc report-all app/myapp/config.json
# produces variants/report.md with PNG previews and .drawio links for every combination
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
  "layout": "REGION>RG>TYPE",
  "diagramMode": "BANDS",
  "spacing": "compact"
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
| `layout` | `string` | No | `"REGION>RG>TYPE"` | Diagram layout mode. Must be one of: `"REGION>RG>TYPE"`, `"VNET>SUBNET"`, `"SUB>REGION>RG>NET"`. See [Layout Modes](#layout-modes). |
| `diagramMode` | `string` | No | `"BANDS"` | Diagram rendering mode. Must be one of: `"BANDS"`, `"MSFT"`. See [Diagram Modes](#diagram-modes). |
| `spacing` | `string` | No | `"compact"` | Diagram spacing preset. Must be one of: `"compact"`, `"spacious"`. See [Spacing](#spacing). |

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

### `SUB>REGION>RG>NET`

Organizes resources in a full environment hierarchy with subscriptions as the top-level container, designed for multi-subscription Azure Landing Zone documentation:

```
┌── Subscription ...00000001 ────────────────────────────────────┐
│  ┌── Region: westeurope ────────────────────────────────────┐  │
│  │  ┌── RG: rg-connectivity-prod ────────────────────────┐  │  │
│  │  │  Networking                                         │  │  │
│  │  │    virtualnetworks                                  │  │  │
│  │  │    ┌──────────┐                                     │  │  │
│  │  │    │ vnet-hub │                                     │  │  │
│  │  │    └──────────┘                                     │  │  │
│  │  │    azurefirewalls                                   │  │  │
│  │  │    ┌──────────┐                                     │  │  │
│  │  │    │ fw-hub   │                                     │  │  │
│  │  │    └──────────┘                                     │  │  │
│  │  │  Resources                                          │  │  │
│  │  │    Monitoring                                       │  │  │
│  │  │    ┌──────────────┐                                 │  │  │
│  │  │    │ law-platform │                                 │  │  │
│  │  │    └──────────────┘                                 │  │  │
│  │  └─────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
┌── Subscription ...00000002 ─────────────────────────────────────┐
│  ...                                                             │
└──────────────────────────────────────────────────────────────────┘
```

Resources inside each resource group are split into two sections:

- **Networking** — VNets, subnets, NSGs, route tables, firewalls, bastion hosts, application gateways, load balancers, public IPs, private endpoints, NICs, NAT gateways, firewall policies, VPN/local network gateways, and connections. Each specific network resource type gets its own sub-header.
- **Resources** — Everything else, grouped by category (Compute, Databases, Storage, Monitoring, etc.) with sub-headers.

This layout produces a 3-level container hierarchy (subscription → region → resource group) so cross-subscription relationships like VNet peering and shared Log Analytics workspaces are clearly visible as edges spanning container boundaries.

**Best for:** Azure Landing Zone migration documentation, multi-subscription environment mapping, full-picture architecture reviews with architects and application teams.

**Example config:**

```json
{
  "app": "landing-zone",
  "subscriptions": ["<hub-sub>", "<app-sub>", "<data-sub>"],
  "seedResourceGroups": ["rg-connectivity-prod", "rg-app-prod", "rg-data-prod"],
  "outputDir": "app/landing-zone/out",
  "layout": "SUB>REGION>RG>NET",
  "diagramMode": "MSFT"
}
```

---

## Diagram Modes

The `diagramMode` config field controls the visual rendering style. This is independent of the `layout` field — `layout` determines how resources are grouped, while `diagramMode` determines the visual style of containers, edges, and UDR presentation.

### `BANDS` (Default)

The original rendering mode. Resources are placed directly on the canvas with orthogonal connector edges, UDR callout boxes, and purple attribute info boxes. Works with both `REGION>RG>TYPE` and `VNET>SUBNET` layouts.

### `MSFT`

Microsoft Architecture Center style rendering. Resources are organized inside hierarchical containers with true draw.io parenting:

```
┌── Region: eastus ──────────────────────────────────────┐    ┌─────────────────────┐
│  ┌── RG: rg-prod ───────────────────────────────────┐  │    │ UDR: rt-web         │
│  │  Compute                                          │  │    │ 10.0.0.0/8 → VNet   │
│  │  ┌──────────┐ ┌──────────┐                        │  │    │ 0.0.0.0/0 → FW      │
│  │  │ vm-web   │ │ vm-app   │                        │  │    └─────────────────────┘
│  │  └──────────┘ └──────────┘                        │  │
│  │  Networking                                       │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐          │  │
│  │  │ vnet     │ │ nic-web  │ │ nsg-web  │          │  │
│  │  └──────────┘ └──────────┘ └──────────┘          │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

Key differences from `BANDS` mode:

| Feature | BANDS | MSFT |
|---------|-------|------|
| Region grouping | Implicit (layout only) | Explicit dashed container |
| Resource group grouping | Implicit (layout only) | Rounded, filled container |
| Node parenting | All nodes parent to root | Hierarchical: region → RG → node |
| Type sections | Type bands (layout) | Labeled headers (Compute, Networking, …) |
| UDR display | Callout boxes inline | Side panels with route details |
| Edge style | Labeled orthogonal | Orthogonal without labels |

Within each resource group container, resources are organized by type category (Compute, Networking, Storage, Databases, etc.) with section headers. Resources are laid out in a 6-column grid within each section.

UDR side panels are placed to the right of the region containers and connected to subnet nodes with `udr_detail` edges. Each panel shows the route table name and up to 8 routes (with a truncation indicator for larger tables).

**Best for:** Architecture documentation, presentations, Microsoft Architecture Center-style diagrams.

---

## Spacing

The `spacing` config field controls whitespace between icons in the diagram. When icon labels overlap or the diagram feels cramped, switching to `"spacious"` adds breathing room without changing icon sizes.

| Preset | Description |
|--------|-------------|
| `"compact"` | Default. Current behavior — tightest layout. |
| `"spacious"` | 1.8x gaps and padding between icons. Labels no longer overlap. |

Only the whitespace between icons is scaled. Icon cell sizes (`120x80` in BANDS, `110x70` in MSFT) remain unchanged, so icons look the same — they're just further apart.

**Example — enable spacious layout:**

```json
{
  "app": "myapp",
  "subscriptions": ["<sub>"],
  "seedResourceGroups": ["rg-prod"],
  "outputDir": "app/myapp/out",
  "layout": "VNET>SUBNET",
  "diagramMode": "MSFT",
  "spacing": "spacious"
}
```

The spacing option works with all layout modes (`REGION>RG>TYPE`, `VNET>SUBNET`, `SUB>REGION>RG>NET`) and all diagram modes (`BANDS`, `MSFT`). In `VNET>SUBNET` mode, container padding (VNet boxes, subnet boxes) is also scaled so inner resources have more room. In `MSFT` mode, RG containers, region containers, and type section headers all grow proportionally.

**When to use spacious:**
- Diagrams with long resource names (labels overlap their neighbors)
- Presentation or documentation contexts where readability matters more than compactness
- Large architectures where the default grid feels too dense

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

1. **Summary** — Counts of route tables and subnets with UDRs, with a list of affected subnet names.
2. **Route Tables** — For each route table, lists all routes in a table with `name`, `destination`, `nextHopType`, and `nextHopIp`. Routes are sorted deterministically by address prefix, hop type, hop IP, and name.
3. **Subnet UDR Associations** — Maps each subnet to its associated route table.
4. **Network Security Groups** — For each NSG, lists inbound and outbound security rules in a table with `name`, `priority`, `protocol`, `src`, `dst`, and `action`. Rules are sorted by priority.

---

## Diagram Features

### Relationship Edges

The graph builder extracts 22 typed edge kinds from resource properties:

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
| `firewall->subnet` | `azurefirewalls` | Firewall IP configuration references a subnet in `ipConfigurations[].properties.subnet` |
| `firewall->publicIp` | `azurefirewalls` | Firewall IP configuration references a public IP in `ipConfigurations[].properties.publicIPAddress` |
| `bastion->subnet` | `bastionhosts` | Bastion IP configuration references a subnet in `ipConfigurations[].properties.subnet` |
| `bastion->publicIp` | `bastionhosts` | Bastion IP configuration references a public IP in `ipConfigurations[].properties.publicIPAddress` |
| `containerApp->environment` | `containerapps` | Container App references its managed environment via `managedEnvironmentId` |
| `containerEnv->subnet` | `managedenvironments` | Container Apps Environment references its infrastructure subnet via `vnetConfiguration.infrastructureSubnetId` |
| `appInsights->workspace` | `components` | Application Insights references a Log Analytics workspace via `WorkspaceResourceId` |
| `appGw->subnet` | `applicationgateways` | Application Gateway references a subnet via `gatewayIPConfigurations[].properties.subnet` |
| `appGw->backend` | `applicationgateways` | Application Gateway references a backend FQDN via `backendAddressPools[].properties.backendAddresses[].fqdn` |
| `logicApp->connection` | `workflows` | Logic App references ARM IDs in parameter values |
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
3. **Microsoft icon fallback** — If no draw.io `azure2` icon matches, the tool attempts a fuzzy match against SVGs in `assets/microsoft-azure-icons/` (if present). Matched icons are embedded as base64 data URIs.
4. **Generic fallback** — If no icon matches at all, a generic blue rounded rectangle is used.
5. **External** — Unresolved/external nodes use a red ellipse style.

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

The tool discovers and renders any Azure resource type. **248 resource types** have dedicated Azure icons mapped in `assets/azure_icon_map.json`, covering the following categories:

| Category | Types | Examples |
|----------|-------|---------|
| Networking | 41 | Virtual Networks, Subnets, NICs, NSGs, Load Balancers, Application Gateways, Firewalls, DNS Zones, ExpressRoute, VPN Gateways, Private Endpoints, Traffic Manager, Front Door, NAT Gateways, Bastion, Private Link, … |
| Compute | 21 | Virtual Machines, VM Scale Sets, Disks, Snapshots, Images, Availability Sets, Host Groups, Galleries, SSH Keys, … |
| Web | 9 | App Services, App Service Plans, Function Apps, Static Web Apps, App Service Environments, … |
| SQL & Databases | 7 | SQL Servers, SQL Databases, Elastic Pools, Managed Instances, … |
| Monitoring | 7 | Application Insights, Log Analytics, Alerts, Autoscale, Action Groups, Dashboards, … |
| Storage | 5 | Storage Accounts, Data Lake, NetApp Files, Storage Movers, … |
| Event Grid | 5 | Topics, Subscriptions, Domains, System Topics, Partner Namespaces |
| Containers | 3 | AKS, Container Registry, Container Instances, … |
| Integration | 3 | Logic Apps, Service Bus, Event Hubs, … |
| Other | 147 | Key Vault, Cosmos DB, Redis Cache, API Management, Cognitive Services, Machine Learning, IoT Hub, DevTest Labs, Managed Identity, and many more |

To add icons for additional resource types, add entries to `assets/azure_icon_map.json`. The key is the lowercase ARM resource type; the value is a draw.io style string referencing an SVG from the built-in `azure2` shape library. Check `icons_used.json` after a run to see which types have `"unknown"` mappings.

### Microsoft Icon ZIP Fallback

For resource types not covered by `azure_icon_map.json`, the tool supports an optional fallback using Microsoft's official Azure icon SVGs. Place the extracted icon files in `assets/microsoft-azure-icons/` (SVG files following Microsoft's naming pattern: `{number}-icon-service-{Service-Name}.svg`).

When this directory exists, the tool:
1. Builds a normalized keyword index from all SVG filenames
2. Attempts fuzzy matching against ARM resource type strings (full resource type, suffix-stripped variants, provider name)
3. Embeds matched SVGs as base64 data URIs in the draw.io cell style
4. Regenerates `assets/azure-fallback.mxlibrary` — a draw.io-importable library of all discovered Microsoft icons

Types resolved via this fallback are reported as `"fallback"` (rather than `"mapped"`) in `icons_used.json`.

---

## Project Structure

```
azure-to-drawio/
├── tools/azdisc/                      # Main Python package
│   ├── __main__.py                    # CLI entry point: argument parsing and subcommand dispatch
│   ├── arg.py                         # Azure Resource Graph query wrapper (paging, batching via az CLI)
│   ├── config.py                      # Config dataclass, JSON loader, layout/diagramMode validation
│   ├── discover.py                    # Seed, transitive expand, and RBAC discovery stages
│   ├── graph.py                       # Graph model: node/edge extraction, child merging, attributes
│   ├── drawio.py                      # Draw.io XML generation, all layout engines + MSFT mode, image export
│   ├── docs.py                        # Markdown documentation generators (catalog, edges, routing)
│   ├── test_all.py                    # Render-all and test-all: all fixture × layout × mode combinations
│   ├── util.py                        # ARM ID regex, normalization, stable ID hashing, logging setup
│   └── tests/
│       ├── fixtures/
│       │   ├── app_contoso.json       # Realistic 3-tier app: VNet, subnets, VMs, SQL, LB, PE, NSGs
│       │   ├── app_ai_chatbot.json    # AI chatbot: Container Apps, OpenAI, Cosmos DB, hub-spoke networking
│       │   ├── app_landing_zone.json  # Multi-sub hub-spoke Azure Landing Zone: 3 subs, firewall, bastion, ACA, PEs
│       │   └── inventory_small.json   # Smaller fixture covering all edge types
│       ├── test_ids.py                # ARM ID parsing, normalization, stable ID determinism
│       ├── test_graph_edges.py        # Edge extraction: all 22 edge kinds
│       ├── test_child_resources.py    # Child resource detection, parent merging, attribute collection
│       ├── test_layout.py             # REGION>RG>TYPE: determinism, positive coords, no overlaps
│       ├── test_vnet_layout.py        # VNET>SUBNET: containers, nesting, labels, determinism
│       ├── test_msft_layout.py        # MSFT mode: region/RG containers, type headers, UDR panels
│       ├── test_msft_icon_fallback.py # Microsoft icon ZIP fallback: index building, fuzzy matching
│       ├── test_spacing.py            # Spacing presets: config validation, gap scaling, label overlap
│       ├── test_ai_chatbot_fixture.py # AI chatbot fixture: graph edges, all layout modes, determinism
│       ├── test_sub_rg_net_layout.py  # SUB>REGION>RG>NET: edges, hierarchy, cross-sub, spacing, edge cases
│       ├── test_test_all.py           # Render-all and test-all: combination generation, variant output
│       └── test_integration.py        # Full pipeline: graph build → drawio XML → PNG export
├── assets/
│   ├── azure_icon_map.json            # Azure resource type → draw.io style string mapping (248 types)
│   ├── azure-fallback.mxlibrary       # Auto-generated draw.io library from Microsoft icon SVGs
│   └── microsoft-azure-icons/         # (optional) Microsoft official Azure icon SVGs for fallback
├── app/myapp/
│   └── config.json                    # Example configuration file
└── .github/workflows/
    └── tests.yml                      # CI: pytest, BANDS + MSFT diagram generation, artifact upload, PR comments
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
- **Edge extraction** — All 22 edge kinds individually (including firewall, bastion, container apps, app insights, app gateway, logic apps), sort order, no duplicates
- **Child resources** — Type detection heuristic, parent ID derivation, attribute collection (VM SKU/image, SQL SKU)
- **Layout engines** — `REGION>RG>TYPE`, `VNET>SUBNET`, `SUB>REGION>RG>NET`, and `MSFT` mode: determinism, positive coordinates, no overlapping nodes, correct cell dimensions
- **Spacing presets** — `compact` (default, backward compatible) and `spacious` (1.8x gaps): config validation, bounding box growth, cell sizes unchanged, label gap sufficiency, no overlaps, integration with all layout/diagram mode combinations
- **VNET>SUBNET containers** — VNet/subnet container cells exist, correct parent nesting, expected labels
- **MSFT mode** — Region/RG container hierarchy, type section headers, hierarchical parenting via `parent` attribute, UDR side panels with route details, deterministic layout
- **SUB>REGION>RG>NET layout** — 3-level subscription→region→RG hierarchy, networking/resources section split, cross-subscription edge validation, subscription label helper, network type classification, spacing effects, edge cases (empty inventory, single node, multi-region, missing subscription)
- **Microsoft icon fallback** — Index building from SVG filenames, normalized keyword matching, fuzzy lookup for ARM types, base64 data URI style generation, fallback library regeneration
- **AI chatbot fixture** — Production-grade Container Apps + OpenAI + hub-spoke architecture: graph construction, private endpoint chains, VNet peering, all 3 layout modes, spacious mode, determinism
- **Landing zone fixture** — Multi-subscription hub-spoke: 3 subscriptions, Azure Firewall, Bastion, Container Apps, private endpoints, cross-subscription App Insights→workspace edges
- **Render-all / test-all** — All fixture × layout × mode combinations generate valid XML, variant folders created, primary output preserved
- **Full integration** — Fixture → `build_graph` → `generate_drawio` → validates XML structure, vertex/edge cell counts, geometry, node labels
- **PNG/SVG export** — When the `drawio` CLI is available: valid PNG header, SVG file created. Graceful skip when CLI is absent.

---

## CI / GitHub Actions

The workflow at `.github/workflows/tests.yml` runs on every push and pull request to `main`:

1. Sets up Python 3.11 and installs `pytest`
2. Installs the draw.io Desktop CLI (with an `xvfb-run` wrapper for headless export)
3. Runs the full pytest suite
4. Generates integration diagrams from the `app_contoso.json` fixture in **both** `BANDS` and `MSFT` diagram modes
5. Uploads separate artifact bundles for each mode:
   - `test-diagrams-bands` — `diagram.drawio`, `diagram.svg`, `diagram.png`
   - `test-diagrams-msft` — `diagram.drawio`, `diagram.svg`, `diagram.png`, `routing.md`, `icons_used.json`
6. On pull requests, posts (or updates) two separate PR comments — one for each diagram mode — with statistics (node/edge count, icon coverage, UDR counts, PNG size) and download links

---

## Backlog

See [Backlog.md](Backlog.md) for planned improvements and future work, including:

- Additional layout modes (`SUBSCRIPTION>RG`, force-directed)
- Diff mode, cost annotations, tag-based filtering
- Multi-format export (Mermaid, PlantUML, Visio)
- Web UI, live sync, policy visualization
