# Diagram Configurations Guide

This guide shows practical `config.json` patterns you can use to generate different diagram styles from the same Azure estate.

## Quick Chooser

| Goal | Best Pattern |
|---|---|
| Clean app view from one RG (with dependencies) | RG-scoped + `L2R` + `spacious` + `networkDetail: "compact"` |
| Strictly only resources from one RG | Seed-only flow (`seed` -> `graph` -> `drawio`) |
| One VM and immediate network chain | `seedResourceIds` + `diagramFocus.preset: "vm-dependencies"` |
| Show app/service integrations, hide network noise | `diagramFocus.diagramType: "application"` |
| Show network topology only | `diagramFocus.diagramType: "network"` |
| Broad baseline of a whole subscription | `seedEntireSubscriptions: true` |

## Configuration Levers That Change Diagram Results

### Scope levers (what enters discovery)

- `seedResourceGroups`: start from known workload RGs.
- `seedResourceIds`: deterministic scope around exact resources (for example one VM).
- `seedTags` and `seedTagKeys`: tag-driven scoping.
- `seedEntireSubscriptions`: broadest baseline scope.
- `expandScope`:
  - `"related"` keeps expansion focused on curated workload dependencies.
  - `"all"` follows all ARM references and can become noisy.

### Layout/readability levers (how the diagram looks)

- `diagramMode`:
  - `"MSFT"`: denser Microsoft-style grouping.
  - `"L2R"`: left-to-right split between resources and network, often cleaner.
- `spacing`:
  - `"compact"`: dense layout.
  - `"spacious"`: more whitespace, less label overlap.
- `networkDetail`:
  - `"full"`: show plumbing (NIC/subnet/NSG/etc.).
  - `"compact"`: summarize plumbing to reduce clutter.
- `edgeLabels`: set `false` for cleaner visuals.
- `layoutMagic`: set `false` for more deterministic placement.

### Focus levers (filter diagram after graph build)

`diagramFocus` is useful when discovery is correct but the rendered diagram is too busy.

- `preset`: `"full"`, `"vm-dependencies"`, `"vm-logicapp-integration"`, `"custom"`
- `includeDependencies`: include neighbors of anchor nodes
- `dependencyDepth`: hop depth for neighbor expansion (`1`-`5`)
- `networkScope`: `"full"` or `"immediate-vm-network"`
- `diagramType`: `"balanced"`, `"network"`, or `"application"`

## Recipes

Replace placeholder values (`<...>`) before running.

### 1) RG-scoped, clean readable diagram (recommended default)

```json
{
  "app": "myapp-rg-clean",
  "subscriptions": ["<subscription-id>"],
  "outputDir": "app/myapp/out-rg-clean",
  "seedResourceGroups": ["<resource-group-name>"],
  "expandScope": "related",
  "layout": "SUB>REGION>RG>NET",
  "diagramMode": "L2R",
  "spacing": "spacious",
  "networkDetail": "compact",
  "edgeLabels": false,
  "layoutMagic": false,
  "includeRbac": false,
  "includePolicy": false,
  "includeAdvisor": false,
  "includeQuota": false,
  "includeVmDetails": false,
  "enableTelemetry": false,
  "diagramFocus": {
    "preset": "full",
    "includeDependencies": true,
    "dependencyDepth": 1,
    "networkScope": "full",
    "diagramType": "balanced"
  }
}
```

Run:

```bash
python3 -m tools.azdisc run app/myapp/config.rg-clean.json
```

### 2) Strict RG-only diagram (no cross-RG expansion)

Use this when you want only resources from the seeded RG, even if dependencies exist elsewhere.

Config snippet:

```json
{
  "app": "myapp-rg-strict",
  "subscriptions": ["<subscription-id>"],
  "outputDir": "app/myapp/out-rg-strict",
  "seedResourceGroups": ["<resource-group-name>"],
  "layout": "SUB>REGION>RG>NET",
  "diagramMode": "L2R",
  "spacing": "spacious",
  "networkDetail": "compact",
  "edgeLabels": false,
  "layoutMagic": false
}
```

Run seed-only flow:

```bash
python3 -m tools.azdisc seed app/myapp/config.rg-strict.json
cp app/myapp/out-rg-strict/seed.json app/myapp/out-rg-strict/inventory.json
printf "[]\n" > app/myapp/out-rg-strict/unresolved.json
python3 -m tools.azdisc graph app/myapp/config.rg-strict.json
python3 -m tools.azdisc drawio app/myapp/config.rg-strict.json
python3 -m tools.azdisc docs app/myapp/config.rg-strict.json
```

### 3) One VM deterministic view (minimal noise)

```json
{
  "app": "myapp-vm-focused",
  "subscriptions": ["<subscription-id>"],
  "outputDir": "app/myapp/out-vm-focused",
  "seedResourceIds": [
    "/subscriptions/<subscription-id>/resourceGroups/<rg>/providers/Microsoft.Compute/virtualMachines/<vm-name>"
  ],
  "expandScope": "related",
  "layout": "SUB>REGION>RG>NET",
  "diagramMode": "L2R",
  "spacing": "spacious",
  "networkDetail": "compact",
  "edgeLabels": false,
  "layoutMagic": false,
  "diagramFocus": {
    "preset": "vm-dependencies",
    "includeDependencies": true,
    "dependencyDepth": 2,
    "networkScope": "immediate-vm-network",
    "diagramType": "network"
  }
}
```

Run:

```bash
python3 -m tools.azdisc run app/myapp/config.vm-focused.json
```

### 4) Application integration diagram (service relationships)

Start from recipe #1 and only change:

```json
{
  "diagramFocus": {
    "preset": "full",
    "includeDependencies": true,
    "dependencyDepth": 1,
    "networkScope": "full",
    "diagramType": "application"
  }
}
```

Use this for architecture conversations where data/integration edges matter more than network paths.

### 5) Network-centric diagram

Start from recipe #1 and only change:

```json
{
  "diagramFocus": {
    "preset": "full",
    "includeDependencies": true,
    "dependencyDepth": 2,
    "networkScope": "full",
    "diagramType": "network"
  },
  "networkDetail": "full",
  "diagramMode": "MSFT"
}
```

Use this when routing, subnet attachments, and network flow are the primary concern.

### 6) Broad subscription baseline

```json
{
  "app": "myapp-baseline",
  "subscriptions": ["<subscription-id>"],
  "outputDir": "app/myapp/out-baseline",
  "seedEntireSubscriptions": true,
  "expandScope": "related",
  "layout": "SUB>REGION>RG>NET",
  "diagramMode": "L2R",
  "spacing": "compact",
  "networkDetail": "compact",
  "edgeLabels": false,
  "layoutMagic": false
}
```

Tip: for large estates, first run baseline with compact settings, then tighten scope by RG, tags, or exact resource IDs.

## Compare Multiple Render Variants Quickly

When the discovered graph is correct but the visual layout is not, generate all mode/spacing variants:

```bash
python3 -m tools.azdisc run app/myapp/config.json
python3 -m tools.azdisc report-all app/myapp/config.json
```

Review `variants/report.md` under your output directory and pick the variant with the best readability.

## Built-in Presets

List built-in presets:

```bash
python3 -m tools.azdisc config-presets
```

Export one preset:

```bash
python3 -m tools.azdisc config-presets --name rg-scoped --write app/myapp/config.preset-rg.json
```

## Troubleshooting Visual Noise

If text overlaps:

1. Set `spacing` to `"spacious"`.
2. Set `edgeLabels` to `false`.
3. Try `diagramMode: "L2R"`.

If lines cross too much:

1. Set `networkDetail` to `"compact"`.
2. Use `diagramFocus.diagramType` = `"application"` or `"network"`.
3. Use `seedResourceIds` for deterministic, smaller scope.

If too many external/shared resources appear:

1. Keep `expandScope: "related"` (avoid `"all"`).
2. Use strict RG-only seed flow (recipe #2).
3. Reduce focus depth to `dependencyDepth: 1`.