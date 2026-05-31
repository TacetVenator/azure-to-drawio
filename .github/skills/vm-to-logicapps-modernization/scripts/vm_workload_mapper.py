#!/usr/bin/env python3
"""Map VM-hosted workload characteristics to Logic App modernization patterns."""

import argparse
import csv
import json


def _norm(v: str) -> str:
    return (v or "").strip().lower()


def _pattern(row: dict) -> str:
    job = _norm(row.get("jobType"))
    stateful = _norm(row.get("stateful")) == "yes"
    freq = _norm(row.get("frequency"))

    if stateful:
        return "logic-app-stateful-with-checkpointing"
    if "event" in job:
        return "logic-app-event-driven"
    if freq in {"hourly", "daily", "weekly"}:
        return "logic-app-recurrence-trigger"
    return "logic-app-standard-workflow"


def _connectors(row: dict) -> list[str]:
    raw = row.get("externalSystems", "")
    systems = [s.strip() for s in raw.split(";") if s.strip()]
    return sorted(set(systems))


def main() -> int:
    parser = argparse.ArgumentParser(description="VM workload to Logic App mapper")
    parser.add_argument("--input", required=True, help="Input CSV")
    args = parser.parse_args()

    mapped = []
    with open(args.input, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mapped.append(
                {
                    "workload": row.get("workload", ""),
                    "recommendedPattern": _pattern(row),
                    "connectors": _connectors(row),
                    "identity": "managed-identity",
                }
            )

    print(json.dumps({"count": len(mapped), "items": mapped}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
