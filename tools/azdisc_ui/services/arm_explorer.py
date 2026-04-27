"""ARM deployment-history exploration helpers for the web UI."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.azdisc.util import extract_arm_ids, normalize_id

from .candidate_explorer import load_candidates


def _inventory_paths(output_dir: str) -> list[Path]:
    root = Path(output_dir)
    paths = [root / "inventory.json"]
    split_root = root / "applications"
    if split_root.exists() and split_root.is_dir():
        paths.extend(split_root.glob("*/inventory.json"))
    return [path for path in paths if path.exists() and path.is_file()]


def _load_json_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text())
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _is_deployment(resource: dict[str, Any]) -> bool:
    return str(resource.get("type", "")).lower() == "microsoft.resources/deployments"


def _deployment_record(resource: dict[str, Any], source_path: Path, output_dir: str) -> dict[str, Any]:
    props = resource.get("properties") if isinstance(resource.get("properties"), dict) else {}
    template_link = props.get("templateLink") if isinstance(props.get("templateLink"), dict) else {}
    parameters = props.get("parameters") if isinstance(props.get("parameters"), dict) else {}

    return {
        "id": resource.get("id"),
        "name": resource.get("name"),
        "type": resource.get("type"),
        "subscriptionId": resource.get("subscriptionId"),
        "resourceGroup": resource.get("resourceGroup"),
        "location": resource.get("location"),
        "provisioningState": props.get("provisioningState"),
        "timestamp": props.get("timestamp") or props.get("createdTime") or props.get("lastModifiedTime"),
        "mode": props.get("mode"),
        "templateLinkUri": template_link.get("uri"),
        "templateHash": props.get("templateHash"),
        "parameterKeys": sorted(parameters.keys()),
        "parameterCount": len(parameters),
        "sourceInventory": str(source_path.relative_to(Path(output_dir))) if source_path.is_relative_to(Path(output_dir)) else str(source_path),
        "_raw": resource,
    }


def _build_match_fields(resource: dict[str, Any], keyword: str) -> list[str]:
    fields: list[str] = []
    if keyword in str(resource.get("name", "")).lower():
        fields.append("name")
    if keyword in str(resource.get("id", "")).lower():
        fields.append("id")
    if keyword in str(resource.get("resourceGroup", "")).lower():
        fields.append("resourceGroup")
    if keyword in str(resource.get("type", "")).lower():
        fields.append("type")

    tags = resource.get("tags")
    if isinstance(tags, dict) and keyword in json.dumps(tags, sort_keys=True).lower():
        fields.append("tags")

    props = resource.get("properties")
    if isinstance(props, dict):
        payload = json.dumps(props, sort_keys=True).lower()
        if keyword in payload:
            fields.append("properties")

        template_link = props.get("templateLink")
        if isinstance(template_link, dict) and keyword in json.dumps(template_link, sort_keys=True).lower():
            fields.append("templateLink")

        parameters = props.get("parameters")
        if isinstance(parameters, dict) and keyword in json.dumps(parameters, sort_keys=True).lower():
            fields.append("parameters")

    return sorted(set(fields))


def _candidate_contexts(output_dir: str) -> list[dict[str, Any]]:
    candidates, _ = load_candidates(output_dir)
    contexts: list[dict[str, Any]] = []

    for candidate in candidates:
        terms = {
            str(term).strip().lower()
            for term in candidate.get("matchedSearchStrings", [])
            if isinstance(term, str) and term.strip()
        }

        ids = {normalize_id(value) for value in extract_arm_ids(candidate)}
        candidate_id = normalize_id(str(candidate.get("id", "")))
        if candidate_id:
            ids.add(candidate_id)

        evidence = candidate.get("discoveryEvidence")
        if isinstance(evidence, list):
            for entry in evidence:
                if not isinstance(entry, dict):
                    continue
                related = entry.get("relatedResources")
                if isinstance(related, list):
                    for related_item in related:
                        if not isinstance(related_item, dict):
                            continue
                        rid = normalize_id(str(related_item.get("id", "")))
                        if rid:
                            ids.add(rid)

        contexts.append(
            {
                "id": str(candidate.get("id", "")),
                "name": str(candidate.get("name", "")),
                "type": str(candidate.get("type", "")),
                "resourceGroup": str(candidate.get("resourceGroup", "")),
                "subscriptionId": str(candidate.get("subscriptionId", "")),
                "terms": terms,
                "ids": ids,
            }
        )

    return contexts


def _attach_candidate_links(
    output_dir: str,
    deployments: list[dict[str, Any]],
    keywords: list[str],
    *,
    per_deployment_limit: int = 5,
) -> None:
    candidate_contexts = _candidate_contexts(output_dir)
    keyword_set = {keyword.strip().lower() for keyword in keywords if keyword and keyword.strip()}

    for deployment in deployments:
        dep_raw = deployment.get("_raw")
        dep_ids = {normalize_id(value) for value in extract_arm_ids(dep_raw if isinstance(dep_raw, dict) else {})}
        dep_id = normalize_id(str(deployment.get("id", "")))
        if dep_id:
            dep_ids.add(dep_id)

        linked_candidates: list[dict[str, Any]] = []

        for candidate in candidate_contexts:
            reasons: list[dict[str, Any]] = []

            shared_ids = sorted(dep_ids & candidate["ids"])
            if shared_ids:
                reasons.append(
                    {
                        "kind": "shared-arm-id",
                        "count": len(shared_ids),
                        "example": shared_ids[0],
                    }
                )

            shared_terms = sorted(candidate["terms"] & keyword_set)
            if shared_terms:
                reasons.append(
                    {
                        "kind": "shared-search-term",
                        "count": len(shared_terms),
                        "terms": shared_terms,
                    }
                )

            if not reasons:
                continue

            linked_candidates.append(
                {
                    "id": candidate["id"],
                    "name": candidate["name"],
                    "type": candidate["type"],
                    "resourceGroup": candidate["resourceGroup"],
                    "subscriptionId": candidate["subscriptionId"],
                    "reasons": reasons,
                    "reasonCount": len(reasons),
                }
            )

        linked_candidates.sort(
            key=lambda item: (
                -int(item.get("reasonCount", 0)),
                str(item.get("name", "")).lower(),
            )
        )

        deployment["linkedCandidateCount"] = len(linked_candidates)
        deployment["linkedCandidates"] = linked_candidates[: max(1, per_deployment_limit)]


def list_deployments(output_dir: str, *, limit: int = 200) -> dict[str, Any]:
    """List ARM deployment resources from inventory artifacts."""
    paths = _inventory_paths(output_dir)
    by_id: dict[str, dict[str, Any]] = {}

    for path in paths:
        for resource in _load_json_list(path):
            if not _is_deployment(resource):
                continue
            rid = str(resource.get("id", "")).lower()
            if not rid:
                continue
            if rid not in by_id:
                by_id[rid] = _deployment_record(resource, path, output_dir)

    deployments = sorted(
        by_id.values(),
        key=lambda d: (
            str(d.get("subscriptionId", "")),
            str(d.get("resourceGroup", "")),
            str(d.get("name", "")),
        ),
    )
    for item in deployments:
        item.pop("_raw", None)

    return {
        "available": len(deployments) > 0,
        "inventoryFiles": [str(path.relative_to(Path(output_dir))) for path in paths if path.is_relative_to(Path(output_dir))],
        "deploymentCount": len(deployments),
        "deployments": deployments[: max(1, min(limit, 2000))],
    }


def search_deployments(output_dir: str, keywords: list[str], *, limit: int = 200) -> dict[str, Any]:
    """Search deployment-history resources for ARM/template keyword hits."""
    normalized_keywords = [keyword.strip().lower() for keyword in keywords if keyword and keyword.strip()]
    if not normalized_keywords:
        return {
            "available": False,
            "keywords": [],
            "resultCount": 0,
            "results": [],
        }

    paths = _inventory_paths(output_dir)
    results: list[dict[str, Any]] = []

    for path in paths:
        for resource in _load_json_list(path):
            if not _is_deployment(resource):
                continue

            combined = json.dumps(resource, sort_keys=True).lower()
            matched_keywords = [kw for kw in normalized_keywords if kw in combined]
            if not matched_keywords:
                continue

            matched_fields: set[str] = set()
            for kw in matched_keywords:
                matched_fields.update(_build_match_fields(resource, kw))

            entry = _deployment_record(resource, path, output_dir)
            entry["matchedKeywords"] = matched_keywords
            entry["matchedFields"] = sorted(matched_fields)
            entry["matchScore"] = len(matched_keywords) * 10 + len(matched_fields)
            results.append(entry)

    deduped: dict[str, dict[str, Any]] = {}
    for item in results:
        rid = str(item.get("id", "")).lower()
        existing = deduped.get(rid)
        if not existing or item["matchScore"] > existing["matchScore"]:
            deduped[rid] = item

    ranked = sorted(
        deduped.values(),
        key=lambda d: (-int(d.get("matchScore", 0)), str(d.get("name", "")).lower()),
    )

    _attach_candidate_links(output_dir, ranked, normalized_keywords)

    for item in ranked:
        item.pop("_raw", None)

    return {
        "available": len(ranked) > 0,
        "keywords": normalized_keywords,
        "resultCount": len(ranked),
        "results": ranked[: max(1, min(limit, 2000))],
    }
