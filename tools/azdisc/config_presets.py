"""Reusable config presets for common scoped-discovery workflows."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


_CONFIG_PRESETS: Dict[str, Dict[str, Any]] = {
    "rg-scoped": {
        "title": "Resource Group Scoped",
        "description": "Seed from one resource group and generate a focused diagram pack.",
        "config": {
            "app": "rg-scoped-workload",
            "subscriptions": ["00000000-0000-0000-0000-000000000000"],
            "outputDir": "app/rg-scoped-workload/out",
            "seedResourceGroups": ["rg-app-prod"],
            "expandScope": "related",
            "diagramFocus": {
                "preset": "full",
                "includeDependencies": True,
                "dependencyDepth": 1,
                "networkScope": "full",
                "diagramType": "balanced",
            },
        },
    },
    "single-vm-deterministic-min-noise": {
        "title": "Single VM Deterministic (Minimal Network Noise)",
        "description": "Seed by exact VM ARM ID and render immediate VM network only.",
        "config": {
            "app": "vm-focused-workload",
            "subscriptions": ["00000000-0000-0000-0000-000000000000"],
            "outputDir": "app/vm-focused-workload/out",
            "seedResourceIds": [
                "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg-app-prod/providers/Microsoft.Compute/virtualMachines/vm-web-01"
            ],
            "expandScope": "related",
            "includeVmDetails": True,
            "diagramFocus": {
                "preset": "vm-dependencies",
                "includeDependencies": True,
                "dependencyDepth": 2,
                "networkScope": "immediate-vm-network",
                "diagramType": "network",
            },
        },
    },
}


def list_config_presets(include_config: bool = True) -> List[Dict[str, Any]]:
    """Return stable, sorted preset metadata with optional config payloads."""
    result: List[Dict[str, Any]] = []
    for name in sorted(_CONFIG_PRESETS):
        item = _CONFIG_PRESETS[name]
        entry: Dict[str, Any] = {
            "name": name,
            "title": item["title"],
            "description": item["description"],
        }
        if include_config:
            entry["config"] = deepcopy(item["config"])
        result.append(entry)
    return result


def get_config_preset(name: str) -> Dict[str, Any]:
    """Return one preset by name or raise ValueError."""
    key = str(name or "").strip()
    if key not in _CONFIG_PRESETS:
        raise ValueError(f"Unknown config preset '{name}'. Available: {sorted(_CONFIG_PRESETS)}")
    payload = _CONFIG_PRESETS[key]
    return {
        "name": key,
        "title": payload["title"],
        "description": payload["description"],
        "config": deepcopy(payload["config"]),
    }
