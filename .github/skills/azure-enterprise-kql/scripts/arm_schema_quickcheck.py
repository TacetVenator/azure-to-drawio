#!/usr/bin/env python3
"""Quick structural checks for ARM templates used in planning workflows."""

import argparse
import json
import sys
from typing import List


def _check_template(doc: dict) -> List[str]:
    issues: List[str] = []

    if "$schema" not in doc:
        issues.append("Missing top-level '$schema'.")

    if "contentVersion" not in doc:
        issues.append("Missing top-level 'contentVersion'.")

    resources = doc.get("resources")
    if not isinstance(resources, list):
        issues.append("Top-level 'resources' must be an array.")
        return issues

    for idx, res in enumerate(resources):
        if not isinstance(res, dict):
            issues.append(f"resources[{idx}] is not an object.")
            continue
        if "type" not in res:
            issues.append(f"resources[{idx}] missing 'type'.")
        if "apiVersion" not in res:
            issues.append(f"resources[{idx}] missing 'apiVersion'.")
        if "name" not in res:
            issues.append(f"resources[{idx}] missing 'name'.")

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="ARM template quick schema checker")
    parser.add_argument("--template", required=True, help="Path to ARM template JSON")
    args = parser.parse_args()

    try:
        with open(args.template, "r", encoding="utf-8") as f:
            doc = json.load(f)
    except FileNotFoundError:
        print(f"Template not found: {args.template}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in {args.template}: {exc}", file=sys.stderr)
        return 2

    issues = _check_template(doc)
    result = {
        "template": args.template,
        "passed": len(issues) == 0,
        "issues": issues,
    }
    print(json.dumps(result, indent=2, sort_keys=True))

    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
