# Doc4agents

## Purpose

Agent-only context for `tools.azdisc`. Optimize for minimal tokens. Read this before changing discovery behavior.

## Pipeline

`seed -> expand -> rbac/policy/telemetry/etc -> graph -> drawio/html/docs -> split/migration/local-analysis`

Keep stage boundaries intact. Prefer artifact consumers over live-query changes in later stages.

## Key Files

- `tools/azdisc/__main__.py`: command wiring
- `tools/azdisc/config.py`: schema, defaults, path helpers
- `tools/azdisc/discover.py`: seed, expand, deep discovery, provenance
- `tools/azdisc/graph.py`: nodes + typed edges from `inventory.json`
- `tools/azdisc/drawio.py`: draw.io renderer
- `tools/azdisc/htmlmap.py`: offline HTML views
- `tools/azdisc/docs.py`: Markdown reports
- `tools/azdisc/review.py`: deep-discovery review UX
- `tools/azdisc/split.py`: post-root application slicing
- `tools/azdisc/wizard.py`: interactive config / prompt flow

## Discovery Rules

### Seed

Seed scope is additive across:
- `seedResourceGroups`
- `seedResourceIds`
- `seedTags`
- `seedTagKeys`
- `seedManagementGroups`
- `seedEntireSubscriptions`

### Expand

`expandScope`:
- `related`: safe default, workload-topology only
- `all`: follow every ARM ID in `properties`

`related` should stay conservative.

Current intended `related` behavior:
- follow curated forward refs: VM->NIC/disk, NIC->subnet/NSG/ASG, subnet->NSG/UDR, webapp->plan/subnet, PE->subnet/target, AppInsights->workspace, ACA/env network refs, etc.
- do narrow reverse lookups for NIC-attached `loadBalancers` and `publicIPAddresses`
- do not walk broad fan-out like VNet peering
- do not add route-table RG context
- avoid generic catch-all ref following unless `all`

Parent derivation still exists:
- subnet ID can derive parent VNet
- missing subnet can be synthesized from VNet `properties.subnets`

This is useful but also a noise source.

### Deep Discovery

Heuristic, opt-in, sidecar workflow.

`related-candidates` matches search strings against:
- `name`
- serialized `tags`
- serialized `properties`

Candidate evidence should preserve:
- why it matched
- how it ties to base inventory

Current rules:
- keep direct ARM-reference associations to base inventory
- keep shared-term associations
- suppress shared-term-only `microsoft.network/*` context unless direct reference exists

Do not casually broaden network evidence here.

## Artifact Contracts

Main:
- `seed.json`
- `inventory.json`
- `unresolved.json`
- `expand_reasons.json`
- `graph.json`
- optional `rbac.json`, `policy.json`, etc.

Deep discovery sidecar:
- `deep-discovery/related_candidates.json`
- `deep-discovery/related_promoted.json`
- `deep-discovery/related_review.md`
- `deep-discovery/extended/seed.json`
- `deep-discovery/extended/inventory.json`

`related-extend` must not mutate base output.

## Change Routing

If user wants discovery breadth / scope / missing resources:
- start in `discover.py`
- then update `test_expand_scope.py`
- then update `test_deep_discovery.py` if keyword/evidence behavior changed

If user wants missing lines / relationships in diagrams:
- inspect `graph.py`
- then renderer/docs only if needed

If user wants review UX / candidate explainability:
- inspect `review.py`, `htmlmap.py`, `discover.py`

If user wants docs wording:
- user-facing semantics: `README.md`
- agent-only semantics: this file

## Invariants

- normalize ARM IDs before compare/store
- keep `related` conservative
- prefer explainable heuristics over broad hidden expansion
- avoid live Azure calls outside discovery/enrichment stages
- if adding new discovery relation, check whether graph edge extraction also needs update
- if changing wizard prompts, update `test_wizard.py`

## Tests

Fast subset:

```bash
pytest -q tools/azdisc/tests/test_deep_discovery.py \
  tools/azdisc/tests/test_expand_scope.py \
  tools/azdisc/tests/test_review_related.py \
  tools/azdisc/tests/test_htmlmap.py
```

Full:

```bash
pytest -q tools/azdisc/tests
```

High-signal for discovery changes:
- `test_expand_scope.py`
- `test_deep_discovery.py`
- `test_cross_rg_networking.py`
- `test_graph_edges.py`
- `test_integration.py`
- `test_seed_tags.py`
