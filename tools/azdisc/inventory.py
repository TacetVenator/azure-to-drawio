"""Generate inventory exports (CSV and YAML) from inventory.json."""
from __future__ import annotations

import csv
import datetime
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import Config
from .util import load_json_file

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_get(obj: Any, *keys) -> Any:
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k)
        else:
            return None
        if obj is None:
            return None
    return obj


def _format_tags(tags: Any) -> str:
    if not tags or not isinstance(tags, dict):
        return ""
    return "; ".join(f"{k}={v}" for k, v in sorted(tags.items()))


def _load_inventory(cfg: Config) -> List[Dict]:
    inv_path = cfg.out("inventory.json")
    if not inv_path.exists():
        raise FileNotFoundError(
            f"inventory.json not found at {inv_path}. Run 'expand' (or 'run') first."
        )
    return load_json_file(
        inv_path,
        context="Inventory export input",
        expected_type=list,
        advice="Fix inventory.json or rerun the expand stage.",
    )


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

_CSV_FIELDS = [
    "Name", "Type", "Location", "ResourceGroup", "SubscriptionId",
    "ProvisioningState", "Tags", "CreatedDate", "CreatedBy", "SkuName",
]


def generate_csv(cfg: Config) -> Path:
    """Read inventory.json and write inventory.csv to outputDir."""
    inventory = _load_inventory(cfg)
    out_path = cfg.out("inventory.csv")

    with out_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for r in inventory:
            writer.writerow({
                "Name": r.get("name", ""),
                "Type": r.get("type", ""),
                "Location": r.get("location", ""),
                "ResourceGroup": r.get("resourceGroup", ""),
                "SubscriptionId": r.get("subscriptionId", ""),
                "ProvisioningState": _safe_get(r, "properties", "provisioningState") or "",
                "Tags": _format_tags(r.get("tags")),
                "CreatedDate": _safe_get(r, "systemData", "createdAt") or "",
                "CreatedBy": _safe_get(r, "systemData", "createdBy") or "",
                "SkuName": _safe_get(r, "sku", "name") or "",
            })

    log.info("Wrote inventory CSV (%d rows) to %s", len(inventory), out_path)
    return out_path


# ---------------------------------------------------------------------------
# YAML export — minimal serializer (no external dependencies)
# ---------------------------------------------------------------------------

def _yaml_scalar(value: Any, indent: int) -> str:
    """Render a scalar value as a YAML-safe string."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # Quote strings that could be misinterpreted by YAML parsers:
    #   - contain special leading characters
    #   - contain colons followed by space (key: value ambiguity)
    #   - look like booleans / null / numbers after conversion
    #   - contain newlines
    needs_quote = (
        not s
        or s[0] in ("#", "&", "*", "?", "|", "-", "<", ">", "=", "!", "%", "@", "`", "'", '"', "{", "}", "[", "]")
        or ": " in s
        or s.endswith(":")
        or "\n" in s
        or s.lower() in ("true", "false", "null", "yes", "no", "on", "off")
    )
    if needs_quote:
        escaped = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        return f'"{escaped}"'
    return s


def _yaml_node(value: Any, indent: int, buf: list) -> None:
    """Recursively render a value into buf lines."""
    pad = "  " * indent
    if isinstance(value, dict):
        if not value:
            buf.append("{}")
            return
        for k, v in value.items():
            key_str = _yaml_scalar(str(k), indent)
            if isinstance(v, (dict, list)):
                if isinstance(v, dict) and not v:
                    buf.append(f"{pad}{key_str}: {{}}")
                elif isinstance(v, list) and not v:
                    buf.append(f"{pad}{key_str}: []")
                else:
                    buf.append(f"{pad}{key_str}:")
                    _yaml_node(v, indent + 1, buf)
            else:
                buf.append(f"{pad}{key_str}: {_yaml_scalar(v, indent)}")
    elif isinstance(value, list):
        if not value:
            buf.append(f"{pad}[]")
            return
        for item in value:
            if isinstance(item, (dict, list)):
                buf.append(f"{pad}-")
                _yaml_node(item, indent + 1, buf)
            else:
                buf.append(f"{pad}- {_yaml_scalar(item, indent)}")
    else:
        buf.append(f"{pad}{_yaml_scalar(value, indent)}")


def _build_resource_entry(r: Dict) -> Dict:
    """Build an ordered resource dict: core fields first, properties last."""
    entry: Dict[str, Any] = {}
    for field in ("name", "type", "location", "resourceGroup", "subscriptionId"):
        v = r.get(field)
        if v is not None:
            entry[field] = v
    prov = _safe_get(r, "properties", "provisioningState")
    if prov is not None:
        entry["provisioningState"] = prov
    tags = r.get("tags")
    if tags:
        entry["tags"] = tags
    sku = r.get("sku")
    if sku:
        entry["sku"] = sku
    system_data = r.get("systemData")
    if system_data:
        entry["systemData"] = system_data
    props = r.get("properties")
    if props:
        entry["properties"] = props
    return entry


def generate_yaml(cfg: Config) -> Path:
    """Read inventory.json and write inventory.yaml to outputDir.

    Default grouping (inventoryGroupBy=type): resource_type → resource_name → fields
    RG grouping (inventoryGroupBy=rg):         resource_group → resource_type → resource_name → fields

    The resulting YAML is structured for VS Code section folding:
      Ctrl+Shift+[  →  fold block at cursor
      Ctrl+Shift+]  →  unfold block at cursor
      Ctrl+K Ctrl+0 →  fold all
      Ctrl+K Ctrl+J →  unfold all
    """
    inventory = _load_inventory(cfg)

    # Build grouped structure: top_key -> (type_key ->) name -> entry
    data: Dict[str, Any] = {}
    group_by = cfg.inventoryGroupBy

    for r in inventory:
        rtype = (r.get("type") or "unknown").lower()
        name = r.get("name") or r.get("id", "unknown")
        entry = _build_resource_entry(r)

        if group_by == "rg":
            rg = (r.get("resourceGroup") or "unknown").lower()
            data.setdefault(rg, {}).setdefault(rtype, {})[name] = entry
        else:
            data.setdefault(rtype, {})[name] = entry

    # Sort top-level and second-level keys; resource names within each group
    def _sort_group(g: Dict) -> Dict:
        return {k: g[k] for k in sorted(g)}

    if group_by == "rg":
        sorted_data = {
            rg: {rtype: _sort_group(names) for rtype, names in _sort_group(types).items()}
            for rg, types in _sort_group(data).items()
        }
    else:
        sorted_data = {
            rtype: _sort_group(names)
            for rtype, names in _sort_group(data).items()
        }

    # Render
    today = datetime.date.today().isoformat()
    header_lines = [
        f"# Azure Resource Inventory",
        f"# App: {cfg.app}",
        f"# Generated: {today}",
        f"# Group: {group_by}",
        f"# VS Code folding: Ctrl+K Ctrl+0 (fold all) / Ctrl+K Ctrl+J (unfold all)",
        "",
    ]

    buf: list = []
    _yaml_node(sorted_data, 0, buf)

    out_path = cfg.out("inventory.yaml")
    out_path.write_text("\n".join(header_lines) + "\n".join(buf) + "\n", encoding="utf-8")
    log.info("Wrote inventory YAML (%d resources, group=%s) to %s", len(inventory), group_by, out_path)
    return out_path
