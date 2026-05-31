---
name: diagram-readability-qa
description: Use when evaluating diagram human readability, enforcing split thresholds, reducing crossed lines/overlap, and producing parent-child diagram decomposition plans.
---

# Diagram Readability QA

Use this skill to evaluate and improve human readability of generated diagrams.

## What This Skill Does

- Scores diagram complexity for node count, edge count, and edge density.
- Flags overlap and crossing risk heuristics.
- Applies a hard split threshold policy with context-aware options.
- Produces a split recommendation that preserves architectural context.

## Hard Split Threshold Policy

Always evaluate thresholds before edits:

- `strict`: split when nodes > 30 or edges > 45
- `balanced` (default): split when nodes > 45 or edges > 70
- `lenient`: split when nodes > 60 or edges > 95

If threshold is exceeded, ask the user to choose:

1. Split now by `resource-group`, `workload`, `network-boundary`, or `lifecycle-domain`
2. Keep single diagram with readability optimization only
3. Override threshold once with explicit approval

## Helper Script

Run the complexity helper to generate a quick threshold report:

```bash
python3 .github/skills/diagram-readability-qa/scripts/diagram_complexity_score.py --input <diagram-metrics.json> --mode balanced
```

Expected input JSON shape:

```json
{
  "nodes": 52,
  "edges": 84,
  "crossingsEstimate": 17,
  "overlapEstimate": 9
}
```

## Output Requirements

- Readability score summary
- Threshold mode and pass/fail decision
- Recommended split axis and rationale
- Parent-child mapping checklist
