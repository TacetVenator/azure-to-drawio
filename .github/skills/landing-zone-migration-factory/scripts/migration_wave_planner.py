#!/usr/bin/env python3
"""Build a dependency-aware migration wave plan from CSV inventory."""

import argparse
import csv
import json
from collections import defaultdict


def _norm(value: str) -> str:
    return (value or "").strip().lower()


def _priority(row: dict) -> int:
    crit = _norm(row.get("criticality"))
    blocked = _norm(row.get("blockedByCompliance")) == "yes"
    pattern = _norm(row.get("pattern"))

    crit_rank = {"high": 0, "medium": 1, "low": 2}.get(crit, 3)
    pattern_rank = {"logicapp": 0, "refactor": 1, "rehost": 2}.get(pattern, 3)
    block_rank = 1 if blocked else 0
    return (block_rank * 100) + (crit_rank * 10) + pattern_rank


def _deps(raw: str) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(";") if x.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Migration wave planner")
    parser.add_argument("--input", required=True, help="CSV inventory path")
    parser.add_argument("--max-wave-size", type=int, default=10)
    args = parser.parse_args()

    rows = []
    with open(args.input, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["dependsOnList"] = _deps(row.get("dependsOn", ""))
            rows.append(row)

    by_name = {r.get("workload", "").strip(): r for r in rows if r.get("workload")}
    scheduled = set()
    waves = []

    while len(scheduled) < len(by_name):
        ready = []
        waiting = []
        for name, row in by_name.items():
            if name in scheduled:
                continue
            deps = row["dependsOnList"]
            if all(d in scheduled or d not in by_name for d in deps):
                ready.append(row)
            else:
                waiting.append(name)

        if not ready:
            # Circular or unresolved dependencies: force-pick remaining by priority
            remaining = [by_name[n] for n in waiting]
            remaining.sort(key=_priority)
            ready = remaining

        ready.sort(key=_priority)
        wave_rows = ready[: max(1, args.max_wave_size)]
        wave_name = f"wave-{len(waves) + 1}"

        waves.append(
            {
                "wave": wave_name,
                "workloads": [r["workload"] for r in wave_rows],
                "containsComplianceBlocked": any(
                    _norm(r.get("blockedByCompliance")) == "yes" for r in wave_rows
                ),
            }
        )

        for r in wave_rows:
            scheduled.add(r["workload"])

    result = {
        "totalWorkloads": len(by_name),
        "waveCount": len(waves),
        "waves": waves,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
