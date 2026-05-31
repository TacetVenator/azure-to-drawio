# SLM Diagram Beta Idea

## Intent
Design a Beta capability where a small language model (SLM) can generate diagram outputs close to frontier-model quality by using compressed, chunked discovery data and a constrained intermediate representation.

## Problem
Directly asking an SLM to ingest full Azure discovery artifacts and emit final draw.io XML is brittle:
- Context windows are too small for full graph/inventory payloads.
- Raw XML generation has high syntax/structure failure rates.
- Dense topology data causes omission and hallucination risk.

## Core Approach
Use a deterministic pipeline around the model:
1. Build a canonical graph from existing artifacts.
2. Compress and chunk graph evidence into stable, retrievable packs.
3. Ask SLM to emit a strict Diagram Plan IR (not final draw.io XML).
4. Compile IR to draw.io with deterministic code.
5. Validate and preview in the existing UI.

## Architecture (Proposed)
- Stage A: Artifacts -> Canonical Graph
- Stage B: Canonical Graph -> Chunk IR
- Stage C: SLM Planner -> selects relevant chunks and view strategy
- Stage D: SLM Emitter -> outputs Diagram Plan IR JSON
- Stage E: Deterministic Compiler -> drawio XML
- Stage F: Validation + Preview + diagnostics

## Diagram IR (v0)
Constrained JSON schema, not free-form text:
- `meta`: run, scope, view type, version
- `groups`: subscription/rg/logical clusters
- `nodes`: id alias, class/type, label, group, importance
- `edges`: source alias, target alias, intent, confidence
- `layoutHints`: lane/cluster/rank hints only
- `policies`: include/exclude intents, collapse rules, fanout limits

## Chunking Strategy
Chunk semantically instead of only by token count:
- Scope chunk: run metadata, selected scope boundaries
- Node chunks: by resource group or service family
- Edge chunks: by edge intent bucket
- Hotspot chunks: shared dependencies, unresolved references, high-degree hubs

Rules:
- Stable chunk IDs for repeatability and citations.
- Alias long IDs to short deterministic tokens.
- Keep only diagram-relevant attributes.
- Allow expansion from summary chunk -> detail chunk.

## Compression Strategy
- Normalize ARM IDs to deterministic aliases per run.
- Replace repetitive structures with templates + counts.
- Emit intent-classified adjacency lists rather than full row copies.
- Preserve provenance links back to original artifact rows.

## Generation Strategy
Two-pass model workflow:
1. Planner pass: decide included chunks and grouping strategy.
2. Emitter pass: output strict Diagram Plan IR JSON.

Deterministic post-processing:
- JSON schema validation
- Alias resolution and repair defaults
- Conflict checks (orphan edges, unknown groups)
- Compile to drawio XML

## Evaluation Strategy
Use frontier outputs as teacher baselines over a fixed benchmark set.

Metrics:
- Node coverage (required classes and critical nodes)
- Critical edge recall by intent
- Grouping fidelity (subscription/RG/application)
- Readability heuristics (fanout, density, overlap proxies)
- Cost and latency per diagram

## Beta UI Concept
Add an "SLM Diagram Beta" flow:
- Select run + scope mode (tag/resource group/resource)
- Select view type (network/application/governance)
- Inspect selected chunks and token estimate
- Generate Plan IR
- Compile and preview diagram
- Show diagnostics (chunks used, omissions, confidence notes)

## Phased Plan
### Phase 0: Success Criteria
- Define tasks, metrics, latency/cost goals.

### Phase 1: IR Schemas
- Implement Diagram Plan IR and Chunk IR schemas + validators.

### Phase 2: Chunker
- Build canonical-graph-to-chunks pipeline and manifests.

### Phase 3: SLM Prompting
- Add planner/emitter prompts and JSON-only response enforcement.

### Phase 4: Compiler
- Convert Plan IR -> drawio XML via deterministic mapping.

### Phase 5: Benchmark + Tuning
- Compare SLM vs teacher outputs; tune chunking and prompts.

### Phase 6: Productize Beta UI
- Expose controls, diagnostics, and export workflow.

## Immediate Next Work
Start with Phase 1 and Phase 2 before any model integration:
- Finalize schema contracts.
- Produce sample chunk packs from existing runs.
- Verify chunk fidelity and size against token budgets.
