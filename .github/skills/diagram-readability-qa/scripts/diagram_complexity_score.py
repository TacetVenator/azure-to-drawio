#!/usr/bin/env python3
"""Compute a simple readability score and split recommendation from diagram metrics."""

import argparse
import json
import sys

THRESHOLDS = {
    "strict": {"nodes": 30, "edges": 45},
    "balanced": {"nodes": 45, "edges": 70},
    "lenient": {"nodes": 60, "edges": 95},
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _score(metrics: dict, mode: str) -> dict:
    t = THRESHOLDS[mode]
    nodes = float(metrics.get("nodes", 0))
    edges = float(metrics.get("edges", 0))
    crossings = float(metrics.get("crossingsEstimate", 0))
    overlaps = float(metrics.get("overlapEstimate", 0))

    node_ratio = nodes / t["nodes"] if t["nodes"] else 0.0
    edge_ratio = edges / t["edges"] if t["edges"] else 0.0

    overload = max(node_ratio, edge_ratio)
    risk_penalty = (crossings * 0.4) + (overlaps * 0.6)
    raw = (overload * 70.0) + risk_penalty
    readability_risk = round(_clamp(raw, 0.0, 100.0), 1)

    threshold_exceeded = (nodes > t["nodes"]) or (edges > t["edges"])

    return {
        "mode": mode,
        "thresholds": t,
        "metrics": {
            "nodes": int(nodes),
            "edges": int(edges),
            "crossingsEstimate": int(crossings),
            "overlapEstimate": int(overlaps),
        },
        "thresholdExceeded": threshold_exceeded,
        "readabilityRisk": readability_risk,
        "recommendation": "split" if threshold_exceeded else "keep-single",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagram complexity scoring helper")
    parser.add_argument("--input", required=True, help="Path to metrics JSON")
    parser.add_argument(
        "--mode",
        choices=sorted(THRESHOLDS.keys()),
        default="balanced",
        help="Threshold mode",
    )
    args = parser.parse_args()

    try:
        with open(args.input, "r", encoding="utf-8") as f:
            metrics = json.load(f)
    except FileNotFoundError:
        print(f"Input not found: {args.input}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {args.input}: {exc}", file=sys.stderr)
        return 2

    report = _score(metrics, args.mode)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
