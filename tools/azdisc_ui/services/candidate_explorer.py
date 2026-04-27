"""Candidate exploration and filtering helpers for the web UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _candidate_paths(output_dir: str) -> list[Path]:
    root = Path(output_dir)
    return [
        root / "related_candidates.json",
        root / "deep-discovery" / "related_candidates.json",
    ]


def _load_candidates_file(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict) and isinstance(data.get("candidates"), list):
        return [item for item in data["candidates"] if isinstance(item, dict)]
    return []


def load_candidates(output_dir: str) -> tuple[list[dict[str, Any]], Path | None]:
    """Load candidate list from known artifact locations."""
    for path in _candidate_paths(output_dir):
        if not path.exists():
            continue
        try:
            return _load_candidates_file(path), path
        except Exception:
            continue
    return [], None


def _scan_text(candidate: dict[str, Any]) -> str:
    evidence = candidate.get("discoveryEvidence")
    return " ".join(
        [
            str(candidate.get("id", "")),
            str(candidate.get("name", "")),
            str(candidate.get("type", "")),
            str(candidate.get("resourceGroup", "")),
            str(candidate.get("subscriptionId", "")),
            json.dumps(candidate.get("matchedSearchStrings", []), sort_keys=True),
            json.dumps(evidence if isinstance(evidence, list) else [], sort_keys=True),
        ]
    ).lower()


def _candidate_matches(candidate: dict[str, Any], spec: dict[str, Any]) -> bool:
    resource_types = {str(v).lower() for v in spec.get("resourceTypes", []) if v}
    subscriptions = {str(v) for v in spec.get("subscriptions", []) if v}
    resource_groups = {str(v).lower() for v in spec.get("resourceGroups", []) if v}
    matched_terms = {str(v).lower() for v in spec.get("matchedTerms", []) if v}
    evidence_fields = {str(v).lower() for v in spec.get("evidenceFields", []) if v}
    query = str(spec.get("query", "")).strip().lower()

    if resource_types and str(candidate.get("type", "")).lower() not in resource_types:
        return False
    if subscriptions and str(candidate.get("subscriptionId", "")) not in subscriptions:
        return False
    if resource_groups and str(candidate.get("resourceGroup", "")).lower() not in resource_groups:
        return False

    terms = {str(v).lower() for v in candidate.get("matchedSearchStrings", []) if isinstance(v, str)}
    if matched_terms and not (terms & matched_terms):
        return False

    if evidence_fields:
        fields: set[str] = set()
        for evidence in candidate.get("discoveryEvidence", []):
            if not isinstance(evidence, dict):
                continue
            single = evidence.get("matchField")
            if isinstance(single, str):
                fields.add(single.lower())
            many = evidence.get("matchFields")
            if isinstance(many, list):
                fields.update(str(v).lower() for v in many if isinstance(v, str))
        if not (fields & evidence_fields):
            return False

    if query and query not in _scan_text(candidate):
        return False

    return True


def summarize_candidates(output_dir: str, *, sample_limit: int = 25) -> dict[str, Any]:
    """Build summary and default sample for candidate exploration."""
    candidates, path = load_candidates(output_dir)
    if not candidates:
        return {
            "available": False,
            "candidateCount": 0,
            "filters": {},
            "candidates": [],
        }

    by_type: dict[str, int] = {}
    by_subscription: dict[str, int] = {}
    by_resource_group: dict[str, int] = {}
    all_terms: set[str] = set()
    evidence_fields: set[str] = set()

    for candidate in candidates:
        ctype = str(candidate.get("type", "unknown"))
        by_type[ctype] = by_type.get(ctype, 0) + 1

        sub = str(candidate.get("subscriptionId", "unknown"))
        by_subscription[sub] = by_subscription.get(sub, 0) + 1

        rg = str(candidate.get("resourceGroup", "unknown"))
        by_resource_group[rg] = by_resource_group.get(rg, 0) + 1

        for term in candidate.get("matchedSearchStrings", []):
            if isinstance(term, str) and term.strip():
                all_terms.add(term.strip())

        for evidence in candidate.get("discoveryEvidence", []):
            if not isinstance(evidence, dict):
                continue
            single = evidence.get("matchField")
            if isinstance(single, str) and single.strip():
                evidence_fields.add(single.strip())
            many = evidence.get("matchFields")
            if isinstance(many, list):
                for field in many:
                    if isinstance(field, str) and field.strip():
                        evidence_fields.add(field.strip())

    sample = sorted(
        candidates,
        key=lambda c: (
            str(c.get("subscriptionId", "")),
            str(c.get("resourceGroup", "")),
            str(c.get("name", "")),
        ),
    )[:sample_limit]

    return {
        "available": True,
        "candidateCount": len(candidates),
        "candidatesPath": str(path.relative_to(Path(output_dir))) if path else None,
        "byType": dict(sorted(by_type.items(), key=lambda kv: kv[0].lower())),
        "bySubscription": dict(sorted(by_subscription.items(), key=lambda kv: kv[0].lower())),
        "byResourceGroup": dict(sorted(by_resource_group.items(), key=lambda kv: kv[0].lower())),
        "filters": {
            "resourceTypes": sorted(by_type.keys(), key=str.lower),
            "subscriptions": sorted(by_subscription.keys(), key=str.lower),
            "resourceGroups": sorted(by_resource_group.keys(), key=str.lower),
            "matchedTerms": sorted(all_terms, key=str.lower),
            "evidenceFields": sorted(evidence_fields, key=str.lower),
        },
        "candidates": sample,
    }


def filter_candidates(output_dir: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Filter candidate list using criteria from the UI."""
    candidates, path = load_candidates(output_dir)
    if not candidates:
        return {
            "available": False,
            "total": 0,
            "filtered": 0,
            "candidates": [],
            "candidatesPath": None,
        }

    limit = max(1, min(int(spec.get("limit", 200)), 1000))
    offset = max(0, int(spec.get("offset", 0)))

    filtered = [c for c in candidates if _candidate_matches(c, spec)]
    filtered_sorted = sorted(
        filtered,
        key=lambda c: (
            str(c.get("subscriptionId", "")),
            str(c.get("resourceGroup", "")),
            str(c.get("name", "")),
        ),
    )
    page = filtered_sorted[offset : offset + limit]

    return {
        "available": True,
        "total": len(candidates),
        "filtered": len(filtered_sorted),
        "offset": offset,
        "limit": limit,
        "candidates": page,
        "candidatesPath": str(path.relative_to(Path(output_dir))) if path else None,
    }
