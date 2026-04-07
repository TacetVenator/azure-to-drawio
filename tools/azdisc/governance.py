"""Shared helpers for policy and RBAC governance summaries."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List

from .util import normalize_id


def normalize_compliance_state(value: object) -> str:
    state = str(value or "Unknown").strip()
    lowered = state.lower()
    if lowered == "noncompliant":
        return "NonCompliant"
    if lowered == "compliant":
        return "Compliant"
    if lowered == "exempt":
        return "Exempt"
    if lowered == "conflict":
        return "Conflict"
    if lowered == "unknown":
        return "Unknown"
    return state or "Unknown"


def summarize_policy_rows(rows: List[Dict[str, Any]]) -> Counter:
    counts: Counter = Counter()
    for row in rows:
        counts[normalize_compliance_state(row.get("complianceState"))] += 1
    return counts


def simplify_rbac_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    simplified: List[Dict[str, str]] = []
    for row in rows:
        props = row.get("properties") or {}
        role_definition_id = props.get("roleDefinitionId") or row.get("roleDefinitionId") or ""
        role_name = (
            props.get("roleDefinitionName")
            or props.get("roleName")
            or row.get("roleDefinitionName")
            or row.get("roleName")
            or (str(role_definition_id).rstrip("/").split("/")[-1] if role_definition_id else "Unknown role")
        )
        principal_id = props.get("principalId") or row.get("principalId") or ""
        principal_name = (
            props.get("principalDisplayName")
            or row.get("principalDisplayName")
            or props.get("principalName")
            or props.get("displayName")
            or row.get("principalName")
            or row.get("displayName")
            or principal_id
            or "Unknown principal"
        )
        simplified.append({
            "scope": normalize_id(props.get("scope") or row.get("scope") or ""),
            "roleName": str(role_name),
            "principalName": str(principal_name),
            "principalType": str(props.get("principalType") or row.get("principalType") or "Unknown"),
            "principalId": str(principal_id),
            "principalResolutionStatus": str(
                props.get("principalResolutionStatus") or row.get("principalResolutionStatus") or ""
            ),
        })
    return simplified


def summarize_resource_access(nodes: List[Dict[str, Any]], rbac_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    assignments = simplify_rbac_rows(rbac_rows)
    summaries: List[Dict[str, Any]] = []
    for node in nodes:
        resource_id = normalize_id(node.get("id") or "")
        if not resource_id or node.get("isExternal"):
            continue
        effective = [assignment for assignment in assignments if assignment["scope"] and resource_id.startswith(assignment["scope"])]
        if not effective:
            continue
        direct = [assignment for assignment in effective if assignment["scope"] == resource_id]
        inherited = [assignment for assignment in effective if assignment["scope"] != resource_id]
        summaries.append({
            "resourceId": resource_id,
            "resourceName": node.get("name") or resource_id,
            "resourceType": node.get("type") or "unknown",
            "resourceGroup": node.get("resourceGroup") or "",
            "effectiveAssignments": len(effective),
            "directAssignments": len(direct),
            "inheritedAssignments": len(inherited),
            "distinctRoles": len({assignment["roleName"] for assignment in effective}),
            "distinctPrincipals": len({assignment["principalName"] for assignment in effective}),
            "assignments": effective,
        })
    summaries.sort(
        key=lambda row: (-row["effectiveAssignments"], -row["distinctRoles"], row["resourceName"].lower())
    )
    return summaries
