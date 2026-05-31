#!/usr/bin/env python3
"""Rank compliance findings by migration impact and severity."""

import argparse
import csv
import json


def _norm(v: str) -> str:
    return (v or "").strip().lower()


def _score(row: dict) -> int:
    sev = _norm(row.get("severity"))
    blocker = _norm(row.get("migrationBlocker")) == "yes"

    sev_score = {"critical": 100, "high": 70, "medium": 40, "low": 20}.get(sev, 10)
    blocker_bonus = 120 if blocker else 0
    return sev_score + blocker_bonus


def main() -> int:
    parser = argparse.ArgumentParser(description="Compliance gap ranker")
    parser.add_argument("--input", required=True, help="Input CSV file")
    args = parser.parse_args()

    findings = []
    with open(args.input, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["priorityScore"] = _score(row)
            findings.append(row)

    findings.sort(key=lambda r: int(r["priorityScore"]), reverse=True)

    out = {
        "count": len(findings),
        "topBlockers": [
            f
            for f in findings
            if _norm(f.get("migrationBlocker")) == "yes"
        ][:20],
        "rankedFindings": findings,
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
