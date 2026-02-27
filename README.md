# azure-to-drawio

Automatically discover Azure resources via [Azure Resource Graph](https://learn.microsoft.com/en-us/azure/governance/resource-graph/) and generate fully-editable [draw.io](https://app.diagrams.net) architecture diagrams — complete with official Azure icons, relationship edges, and network topology containers.

## How It Works

```
Azure Resource Graph  ──►  Seed  ──►  Expand  ──►  Graph  ──►  Draw.io  ──►  Docs
    (Kusto / az CLI)       │           │            │            │             │
                           ▼           ▼            ▼            ▼             ▼
                       seed.json   inventory.json  graph.json  diagram.drawio  catalog.md
                                   unresolved.json              diagram.svg    edges.md
                                                                diagram.png    routing.md
                                                                icons_used.json
```

The tool runs a multi-stage pipeline:

1. **Seed** — Queries Azure Resource Graph for all resources in specified resource groups
2. **Expand** — Transitively follows ARM ID references in resource properties to discover related resources (NICs, disks, subnets, etc.), iterating until convergence
3. **RBAC** *(optional)* — Queries `authorizationresources` for role assignments scoped to discovered resources
4. **Graph** — Builds a normalized graph model (nodes + typed edges) from the inventory, merging child resources (e.g., VM extensions, SQL firewall rules) into their parent nodes
5. **Draw.io** — Generates a `.drawio` XML file with positioned nodes, Azure icon styles, typed edges, UDR callouts, and attribute info boxes. Optionally exports to SVG and PNG
6. **Docs** — Generates Markdown documentation: resource catalog, edge statistics, and routing/NSG details

## Prerequisites

- **Python 3.11+**
- **Azure CLI** (`az`) — authenticated with access to your target subscriptions
- **draw.io CLI** *(optional)* — for automatic SVG/PNG export. Install [drawio-desktop](https://github.com/jgraph/drawio-desktop/releases) and ensure `drawio` is on your `PATH`

## Quick Start

### 1. Create a Configuration File

Create a `config.json` for your application:

```json
{
  "app": "myapp",
  "subscriptions": ["xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"],
  "seedResourceGroups": ["rg-myapp-prod", "rg-myapp-network"],
  "outputDir": "app/myapp/out",
  "includeRbac": false,
  "layout": "REGION>RG>TYPE"
}
```

### 2. Run the Full Pipeline

```bash
python3 -m tools.azdisc run app/myapp/config.json
```

This executes all stages in sequence (seed → expand → rbac → graph → drawio → docs) and writes output files to your configured `outputDir`.

### 3. Open the Diagram

Open `diagram.drawio` in:
- [app.diagrams.net](https://app.diagrams.net) (online)
- [draw.io Desktop](https://github.com/jgraph/drawio-desktop/releases) (offline)
- VS Code with the [Draw.io Integration](https://marketplace.visualstudio.com/items?itemName=hediet.vscode-drawio) extension

## Configuration Reference

| Field | Type | Required | Default | Description |
|-------|------|----------|---------|-------------|
| `app` | `string` | Yes | — | Application name, used as the diagram tab label |
| `subscriptions` | `string[]` | Yes | — | Azure subscription IDs to query |
| `seedResourceGroups` | `string[]` | Yes | — | Resource groups to seed discovery from |
| `outputDir` | `string` | Yes | — | Directory for all output files |
| `includeRbac` | `bool` | No | `false` | Query and include RBAC role assignments |
| `layout` | `string` | No | `"REGION>RG>TYPE"` | Diagram layout mode (see below) |

## Layout Modes

### `REGION>RG>TYPE` (Default)

Organizes resources in a hierarchical grid:

```
Region
└── Resource Group
    └── Resource Type Band
        └── Resources (left-to-right grid, wrapping at 6 columns)
```

Resources are grouped by region, then by resource group, then by type. Within each type band, resources are laid out in a grid that wraps after 6 columns. This mode gives a clear inventory-style overview of all resources.

**Best for:** General-purpose infrastructure overviews, multi-region deployments, resource auditing.

### `VNET>SUBNET`

Organizes resources by their network topology:

```
┌─ VNet: vnet-prod ─────────────────────────────────┐
│  ┌─ Subnet: snet-web ──┐  ┌─ Subnet: snet-app ─┐ │
│  │  vm-web-01           │  │  vm-app-01          │ │
│  │  nic-web-01          │  │  nic-app-01         │ │
│  │  nsg-web             │  │  nsg-app            │ │
│  └──────────────────────┘  └─────────────────────┘ │
└────────────────────────────────────────────────────┘
┌─ Other Resources ──┐
│  kv-prod            │
│  stprod             │
└─────────────────────┘
```

VNets and subnets are rendered as nested container boxes. Resources are placed inside the subnet they belong to based on edge relationships:

- **VMs** — placed via VM → NIC → Subnet chain
- **NICs** — placed via NIC → Subnet IP configuration
- **Private Endpoints** — placed via their subnet property
- **Web Apps** — placed via VNet integration subnet
- **NSGs** and **Route Tables** — placed in the subnet they're associated with
- **Load Balancers** — placed near their backend NIC's subnet
- **Public IPs** — placed near their attached NIC's subnet
- **Private Endpoint targets** (e.g., SQL Server) — placed in the PE's subnet

Resources not attached to any subnet appear in an "Other Resources" box.

**Best for:** Network architecture diagrams, security reviews, subnet capacity planning.

## Pipeline Stages

Each stage can be run individually or as part of the full pipeline:

```bash
# Full pipeline (all stages)
python3 -m tools.azdisc run config.json

# Individual stages
python3 -m tools.azdisc seed config.json       # Query Azure for seed resources
python3 -m tools.azdisc expand config.json      # Transitive expansion
python3 -m tools.azdisc graph config.json       # Build graph model
python3 -m tools.azdisc drawio config.json      # Generate draw.io diagram
python3 -m tools.azdisc docs config.json        # Generate Markdown docs
```

Running individual stages is useful when you want to:
- Re-generate the diagram after tweaking config (without re-querying Azure)
- Debug a specific stage
- Only produce documentation without a diagram

Enable verbose logging with `-v`:

```bash
python3 -m tools.azdisc -v run config.json
```

## Output Files

| File | Stage | Description |
|------|-------|-------------|
| `seed.json` | seed | Raw resources from seeded resource groups |
| `inventory.json` | expand | Complete inventory after transitive expansion |
| `unresolved.json` | expand | ARM IDs referenced but not found in Azure |
| `rbac.json` | run | RBAC role assignments (when `includeRbac: true`) |
| `graph.json` | graph | Normalized graph model with nodes, edges, and attributes |
| `diagram.drawio` | drawio | draw.io XML diagram — the main output |
| `diagram.svg` | drawio | SVG export (requires draw.io CLI) |
| `diagram.png` | drawio | PNG export (requires draw.io CLI) |
| `icons_used.json` | drawio | Icon mapping report (mapped, fallback, unknown types) |
| `catalog.md` | docs | Resource catalog table by type, region, and resource group |
| `edges.md` | docs | Edge statistics, top-20 nodes by degree, unresolved references |
| `routing.md` | docs | UDR route tables and NSG security rules per subnet |

## Supported Azure Resource Types

The tool discovers and renders any Azure resource type. The following have dedicated Azure icons in the diagram:

| Resource Type | Icon |
|---------------|------|
| `microsoft.compute/virtualmachines` | Virtual Machine |
| `microsoft.compute/disks` | Managed Disk |
| `microsoft.network/virtualnetworks` | Virtual Network |
| `microsoft.network/virtualnetworks/subnets` | Subnet |
| `microsoft.network/networkinterfaces` | Network Interface |
| `microsoft.network/networksecuritygroups` | Network Security Group |
| `microsoft.network/routetables` | Route Table |
| `microsoft.network/loadbalancers` | Load Balancer |
| `microsoft.network/publicipaddresses` | Public IP Address |
| `microsoft.network/privateendpoints` | Private Endpoint |
| `microsoft.network/applicationgateways` | Application Gateway |
| `microsoft.web/sites` | App Service |
| `microsoft.web/serverfarms` | App Service Plan |
| `microsoft.storage/storageaccounts` | Storage Account |
| `microsoft.keyvault/vaults` | Key Vault |
| `microsoft.sql/servers` | SQL Server |
| `microsoft.sql/servers/databases` | SQL Database |
| `microsoft.containerservice/managedclusters` | Kubernetes Service (AKS) |

Resource types without a mapped icon are rendered with a generic rounded-rectangle style. External/unresolved references are shown as red ellipses.

## Diagram Features

### Relationship Edges

The graph builder extracts typed edges from resource properties:

| Edge Kind | Meaning |
|-----------|---------|
| `vm->nic` | VM references a network interface |
| `vm->disk` | VM references a managed disk (OS or data) |
| `nic->subnet` | NIC IP configuration references a subnet |
| `nic->nsg` | NIC references a network security group |
| `subnet->vnet` | Subnet belongs to a virtual network |
| `subnet->nsg` | Subnet references a network security group |
| `subnet->routeTable` | Subnet references a route table (UDR) |
| `vnet->peeredVnet` | VNet peering to another virtual network |
| `privateEndpoint->subnet` | Private endpoint is in a subnet |
| `privateEndpoint->target` | Private endpoint connects to a service |
| `loadBalancer->backendNic` | Load balancer backend pool references a NIC |
| `publicIp->attachment` | Public IP is attached to a NIC |
| `webApp->appServicePlan` | Web app runs on an App Service Plan |
| `webApp->subnet` | Web app has VNet integration |
| `rbac_assignment` | RBAC role assignment scope (when enabled) |

### UDR Callout Boxes

Route tables with defined routes get a callout box showing each route's address prefix and next hop type, connected to the associated subnet with a labeled "UDR" edge.

### Attribute Info Boxes

Resources with notable properties display an info box next to their icon:

- **VMs** — SKU size, OS image (publisher/offer/sku), OS type
- **SQL Servers/Databases** — SKU name and tier
- **Child resources** — VM extensions, SQL firewall rules, and SQL administrators are listed as attributes on their parent node

### Child Resource Merging

Resources that are children of another resource (e.g., VM extensions, SQL firewall rules) are not rendered as separate icons. Instead, they are merged into their parent node as attribute annotations, keeping the diagram clean.

### Transitive Discovery

The expand stage follows ARM ID references recursively (up to 50 iterations) until no new resources are found. This ensures the diagram captures resources that weren't in the original resource groups but are referenced by discovered resources — for example, a subnet in a shared networking resource group referenced by a NIC in an application resource group.

## Project Structure

```
azure-to-drawio/
├── tools/azdisc/                      # Main Python package
│   ├── __main__.py                    # CLI entry point and subcommands
│   ├── arg.py                         # Azure Resource Graph query wrapper (az CLI)
│   ├── config.py                      # Configuration schema and loader
│   ├── discover.py                    # Seed, expand, and RBAC discovery
│   ├── graph.py                       # Graph model: nodes, edges, attributes
│   ├── drawio.py                      # Draw.io XML generation and layout engines
│   ├── docs.py                        # Markdown documentation generators
│   ├── util.py                        # ARM ID parsing, normalization, stable IDs
│   └── tests/                         # pytest test suite
│       ├── fixtures/                  # Test data (realistic Azure inventories)
│       ├── test_ids.py                # ARM ID parsing and normalization
│       ├── test_graph_edges.py        # Edge extraction for all relationship types
│       ├── test_child_resources.py    # Child resource filtering and merging
│       ├── test_layout.py            # REGION>RG>TYPE layout determinism and overlaps
│       ├── test_vnet_layout.py        # VNET>SUBNET layout and container tests
│       └── test_integration.py        # Full pipeline: graph → drawio XML → PNG
├── assets/
│   ├── azure_icon_map.json            # Azure resource type → draw.io style mapping
│   └── azure-fallback.mxlibrary       # Fallback icon library
├── app/myapp/
│   └── config.json                    # Example configuration
└── .github/workflows/
    └── tests.yml                      # CI: pytest + diagram generation on PRs
```

## Running Tests

```bash
pip install pytest
python -m pytest tools/azdisc/tests/ -v
```

Tests run entirely offline using fixture data — no Azure credentials needed. The test suite covers:

- ARM ID parsing and normalization
- Edge extraction for all 15 relationship types
- Child resource detection and parent merging
- Both layout engines (determinism, no overlaps, correct positioning)
- Full pipeline integration (inventory → graph → draw.io XML validation)
- PNG/SVG export (when the draw.io CLI is available)

## CI / GitHub Actions

The included workflow (`.github/workflows/tests.yml`) runs on every push and PR to `main`:

1. Runs the full pytest suite
2. Generates a diagram from the test fixture
3. Uploads `.drawio`, `.svg`, and `.png` as build artifacts
4. Posts a summary comment on PRs with diagram statistics

## Next Steps and Future Improvements

### Near-Term Enhancements

- **More icon mappings** — Expand `azure_icon_map.json` to cover additional resource types (Cosmos DB, Event Hubs, Service Bus, Azure Functions, API Management, Front Door, Azure Firewall, Bastion, etc.)
- **Subscription and region grouping in VNET>SUBNET mode** — Wrap VNets in subscription/region containers for multi-subscription environments
- **Interactive legend** — Auto-generate a legend in the diagram showing which icon maps to which resource type
- **Configurable column count** — Allow `config.json` to override the default 6-column grid width

### Medium-Term Features

- **Additional layout modes** — e.g., `SUBSCRIPTION>RG` for subscription-centric views, or a force-directed layout for complex topologies
- **Diff mode** — Compare two inventory snapshots and highlight added, removed, or changed resources in the diagram
- **Cost annotations** — Pull Azure Cost Management data and annotate resources with monthly spend
- **Tag-based filtering** — Filter or color-code resources by Azure tags
- **Custom edge types** — Allow users to define additional edge extraction rules for resource types not yet supported

### Long-Term Vision

- **Live sync** — Watch for Azure resource changes and auto-update diagrams
- **Multi-format export** — Generate Mermaid, PlantUML, or Terraform-graph-compatible output
- **Web UI** — Browser-based interface for configuring and previewing diagrams without the CLI
- **Policy visualization** — Overlay Azure Policy assignments and compliance state onto the diagram
- **Private link topology** — Dedicated view showing private endpoint chains across VNets and subscriptions

## License

This project does not currently include a license file. Contact the repository owner for licensing information.
