#!/usr/bin/env python3
"""Assess Dynamics integration readiness for Logic Apps migration."""

import argparse
import csv
import json


def _norm(v: str) -> str:
    return (v or "").strip().lower()


def _evaluate(row: dict) -> dict:
    issues = []
    if _norm(row.get("idempotent")) != "yes":
        issues.append("Missing idempotency strategy")
    if _norm(row.get("hasRetryPolicy")) != "yes":
        issues.append("Missing retry policy")

    auth = _norm(row.get("authModel"))
    if auth in {"user", "password"}:
        issues.append("Use managed identity or service principal auth")

    rps_raw = (row.get("expectedRps") or "").strip()
    try:
        rps = float(rps_raw)
    except ValueError:
        rps = 0.0

    if rps > 50:
        issues.append("Review connector throttling and batching strategy")

    return {
        "integrationName": row.get("integrationName", ""),
        "ready": len(issues) == 0,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Dynamics integration readiness checker")
    parser.add_argument("--input", required=True, help="Input CSV")
    args = parser.parse_args()

    results = []
    with open(args.input, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            results.append(_evaluate(row))

    summary = {
        "total": len(results),
        "ready": sum(1 for r in results if r["ready"]),
        "notReady": sum(1 for r in results if not r["ready"]),
        "items": results,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
