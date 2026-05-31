"""Output anonymization for corporate-safe test dataset extraction.

Transforms all output files in an azdisc outputDir so that Azure-specific
identifiers (resource names, subscription IDs, tenant IDs, principal names,
tag keys/values, IP addresses, FQDNs) are replaced with stable, readable
aliases derived from SHA-256 hashing.

Aliases are deterministic: the same original value always produces the same
alias for a given salt.  With the default empty salt every run on the same
data produces identical aliases, enabling safe sharing across invocations.

Usage (programmatic)::

    from pathlib import Path
    from tools.azdisc.anonymize import ResourceAnonymizer

    anon = ResourceAnonymizer(salt="")          # deterministic across runs
    anon.apply_output_dir(Path(cfg.outputDir))  # rewrites files in-place
    anon.save_map(Path(cfg.outputDir) / ".anon-map.json")

Usage (via Config flag)::

    # In config.json:
    { "anonymizeOutput": true, "anonymizeSalt": "" }

    # Or via CLI:
    # set anonymizeOutput: true in your config file, then run normally.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# ── Regex patterns ─────────────────────────────────────────────────────────────

_IPv4_RE = re.compile(
    r"^\s*(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})\s*$"
)

_GUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

_EMAIL_RE = re.compile(
    r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
)

# Azure service domains that should never be anonymized
_SAFE_DOMAINS = frozenset({
    "windows.net",
    "azure.com",
    "microsoft.com",
    "microsoftonline.com",
    "azure.net",
    "azurewebsites.net",
    "azurefd.net",
    "core.windows.net",
    "anon.example",
    "management.azure.com",
})

# ── JSON artifact filenames to process ────────────────────────────────────────

_JSON_ARTIFACTS = (
    "inventory.json",
    "seed.json",
    "graph.json",
    "rbac.json",
    "policy.json",
    "resource_catalog.json",
    "related_candidates.json",
    "related_promoted.json",
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _is_private_ip(octets: tuple[int, int, int, int]) -> bool:
    a, b, c, d = octets
    return (
        a == 10
        or (a == 172 and 16 <= b <= 31)
        or (a == 192 and b == 168)
        or (a == 127)
    )


def _is_safe_domain(fqdn: str) -> bool:
    lower = fqdn.lower()
    return any(lower == d or lower.endswith("." + d) for d in _SAFE_DOMAINS)


# ── Core class ────────────────────────────────────────────────────────────────


class ResourceAnonymizer:
    """Deterministically anonymize Azure resource identifiers in output files.

    Parameters
    ----------
    salt:
        Optional string mixed into the hash.  Default ``""`` = fully
        deterministic across any run and any machine.  Pass a secret
        value to prevent cross-client alias correlation.
    """

    def __init__(self, salt: str = "") -> None:
        self._salt = salt
        # Mapping key is "category:original_value" → alias string
        self._map: Dict[str, str] = {}
        # Track known subscription / tenant GUIDs for GUID disambiguation
        self._subscription_guids: set[str] = set()
        self._tenant_guids: set[str] = set()

    # ── Alias generation ───────────────────────────────────────────────────────

    def _h6(self, category: str, value: str) -> str:
        """Return 6 stable hex characters for (salt, category, value)."""
        raw = f"{self._salt}\x00{category}\x00{value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:6]

    def _alias(self, category: str, value: str, prefix: str) -> str:
        key = f"{category}:{value}"
        if key not in self._map:
            self._map[key] = f"{prefix}-{self._h6(category, value)}"
        return self._map[key]

    def alias_subscription(self, sub_id: str) -> str:
        if not sub_id:
            return sub_id
        norm = sub_id.strip().lower()
        self._subscription_guids.add(norm)
        return self._alias("sub", norm, "sub")

    def alias_tenant(self, tenant_id: str) -> str:
        if not tenant_id:
            return tenant_id
        norm = tenant_id.strip().lower()
        self._tenant_guids.add(norm)
        return self._alias("ten", norm, "ten")

    def alias_resource_group(self, rg: str) -> str:
        if not rg:
            return rg
        return self._alias("rg", rg.strip().lower(), "rg")

    def alias_resource_name(self, name: str) -> str:
        if not name:
            return name
        return self._alias("res", name.strip().lower(), "res")

    def alias_principal_email(self, email: str) -> str:
        if not email:
            return email
        norm = email.strip().lower()
        key = f"email:{norm}"
        if key not in self._map:
            self._map[key] = f"user-{self._h6('email', norm)}@anon.example"
        return self._map[key]

    def alias_principal_display_name(self, name: str) -> str:
        if not name:
            return name
        return self._alias("principal", name.strip().lower(), "user")

    def alias_principal_id(self, oid: str) -> str:
        if not oid:
            return oid
        return self._alias("oid", oid.strip().lower(), "oid")

    def alias_tag_key(self, key: str) -> str:
        if not key:
            return key
        return self._alias("tagkey", key.strip().lower(), "tagkey")

    def alias_tag_value(self, value: str) -> str:
        if not value:
            return value
        return self._alias("tagval", value.strip().lower(), "tagval")

    def alias_ipv4(self, ip: str) -> str:
        """Return an anonymized IPv4 address in a documentation range."""
        if not ip:
            return ip
        m = _IPv4_RE.match(ip)
        if not m:
            return ip
        octets = tuple(int(m.group(i)) for i in range(1, 5))
        key = f"ip:{ip.strip()}"
        if key not in self._map:
            h = self._h6("ip", ip.strip())
            x = int(h[:2], 16) % 254 + 1
            y = int(h[2:4], 16) % 254 + 1
            if _is_private_ip(octets):  # type: ignore[arg-type]
                # RFC 1918 — use a dedicated sub-range unlikely to clash
                self._map[key] = f"10.100.{x}.{y}"
            else:
                # RFC 5737 documentation range for public addresses
                self._map[key] = f"203.0.113.{x}"
        return self._map[key]

    def alias_fqdn(self, fqdn: str) -> str:
        """Return an anonymized FQDN in the anon.example domain."""
        if not fqdn:
            return fqdn
        if _is_safe_domain(fqdn):
            return fqdn
        key = f"fqdn:{fqdn.strip().lower()}"
        if key not in self._map:
            h = self._h6("fqdn", fqdn.strip().lower())
            self._map[key] = f"host-{h}.anon.example"
        return self._map[key]

    def alias_guid(self, guid: str) -> str:
        """Anonymize a GUID that is not a known subscription or tenant ID."""
        if not guid:
            return guid
        norm = guid.strip().lower()
        if norm in self._subscription_guids:
            return self.alias_subscription(norm)
        if norm in self._tenant_guids:
            return self.alias_tenant(norm)
        return self._alias("guid", norm, "id")

    # ── ARM ID rewriting ───────────────────────────────────────────────────────

    def rewrite_arm_id(self, arm_id: str) -> str:
        """Rewrite an ARM resource ID, anonymizing subscription, RG, and resource name.

        Provider namespace (e.g. ``Microsoft.Compute``) and resource type
        (e.g. ``virtualMachines``) are preserved because they carry architecture
        signal without exposing client identity.
        """
        if not arm_id or not arm_id.startswith("/"):
            return arm_id

        parts = arm_id.split("/")
        result: List[str] = []
        i = 0
        while i < len(parts):
            part = parts[i]
            part_l = part.lower()

            if part_l == "subscriptions" and i + 1 < len(parts):
                result.append(part)
                i += 1
                result.append(self.alias_subscription(parts[i]))

            elif part_l in ("resourcegroups", "resourcegroup") and i + 1 < len(parts):
                result.append(part)
                i += 1
                result.append(self.alias_resource_group(parts[i]))

            elif part_l == "providers" and i + 2 < len(parts):
                result.append(part)                    # 'providers'
                i += 1
                result.append(parts[i])               # namespace — keep
                i += 1
                result.append(parts[i])               # resource type — keep
                if i + 1 < len(parts):
                    i += 1
                    # Sub-resource types (e.g. 'subnets', 'networkInterfaces')
                    # alternate between type and name segments
                    result.append(self.alias_resource_name(parts[i]))
                    while i + 2 < len(parts):
                        i += 1
                        result.append(parts[i])       # sub-resource type — keep
                        i += 1
                        result.append(self.alias_resource_name(parts[i]))

            else:
                result.append(part)

            i += 1

        return "/".join(result)

    # ── Structural JSON transforms ─────────────────────────────────────────────

    def _anon_tags(self, tags: Dict[str, Any]) -> Dict[str, Any]:
        return {
            self.alias_tag_key(str(k)): self.alias_tag_value(str(v)) if v is not None else v
            for k, v in tags.items()
        }

    def _anon_string_deep(self, value: str) -> str:
        """Pattern-based anonymization for nested strings (not field-key aware)."""
        stripped = value.strip()
        if stripped.startswith("/subscriptions/") or stripped.startswith("/Subscriptions/"):
            return self.rewrite_arm_id(stripped)
        if _EMAIL_RE.match(stripped):
            return self.alias_principal_email(stripped)
        if _GUID_RE.match(stripped):
            return self.alias_guid(stripped)
        if _IPv4_RE.match(stripped):
            return self.alias_ipv4(stripped)
        return value

    def _anon_dict_deep(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively anonymize a dict using pattern-based transforms only."""
        result: Dict[str, Any] = {}
        for k, v in obj.items():
            if isinstance(v, str):
                result[k] = self._anon_string_deep(v)
            elif isinstance(v, dict):
                result[k] = self._anon_dict_deep(v)
            elif isinstance(v, list):
                result[k] = [
                    self._anon_dict_deep(item) if isinstance(item, dict)
                    else (self._anon_string_deep(item) if isinstance(item, str) else item)
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def _anon_resource_field(self, key: str, value: Any) -> Any:
        """Apply field-name-aware transform for a top-level resource item field."""
        key_l = key.lower()

        if isinstance(value, str):
            stripped = value.strip()

            # ARM resource IDs (by value prefix, regardless of key name)
            if stripped.startswith("/subscriptions/") or stripped.startswith("/Subscriptions/"):
                return self.rewrite_arm_id(stripped)

            # Subscription IDs
            if key_l in ("subscriptionid", "subscription_id"):
                return self.alias_subscription(stripped)

            # Tenant IDs
            if key_l in ("tenantid", "tenant_id"):
                return self.alias_tenant(stripped)

            # Resource group
            if key_l in ("resourcegroup", "resource_group"):
                return self.alias_resource_group(stripped)

            # Resource name (top-level only — not SKU/tier/kind nested names)
            if key_l == "name":
                return self.alias_resource_name(stripped)

            # Principal identities
            if key_l in ("principaldisplayname", "displayname", "principalname", "upn"):
                if _EMAIL_RE.match(stripped):
                    return self.alias_principal_email(stripped)
                return self.alias_principal_display_name(stripped)

            if key_l in ("principalid", "objectid", "object_id"):
                return self.alias_principal_id(stripped)

            # SCOPE field (RBAC / policy)
            if key_l == "scope":
                return self._anon_string_deep(stripped)

            # IP address fields
            if key_l in (
                "privateipaddress", "publicipaddress", "ipaddress", "ip_address",
                "privateip", "publicip",
            ):
                if _IPv4_RE.match(stripped):
                    return self.alias_ipv4(stripped)

            # FQDN / hostname fields
            if key_l in ("fqdn", "hostname", "host", "dnslabel", "dnsname", "dnshostname"):
                return self.alias_fqdn(stripped)

            # Pattern fallback: plain GUIDs and emails
            if _EMAIL_RE.match(stripped):
                return self.alias_principal_email(stripped)
            if _GUID_RE.match(stripped):
                return self.alias_guid(stripped)

            return value

        if key_l == "tags" and isinstance(value, dict):
            return self._anon_tags(value)

        if isinstance(value, dict):
            # Recursively process nested dicts (e.g. properties) with deep scan
            return self._anon_dict_deep(value)

        if isinstance(value, list):
            return [self._anon_resource_field(key, item) for item in value]

        return value

    def anon_resource_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Anonymize a single resource item dict (inventory, seed, graph node)."""
        return {k: self._anon_resource_field(k, v) for k, v in item.items()}

    def anon_rbac_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Anonymize an RBAC assignment item."""
        # RBAC assignments share many fields with resource items
        return self.anon_resource_item(item)

    def anon_edge_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        """Anonymize a graph edge item (source/target are ARM IDs)."""
        result: Dict[str, Any] = {}
        for k, v in item.items():
            if isinstance(v, str):
                result[k] = self._anon_string_deep(v)
            elif isinstance(v, dict):
                result[k] = self._anon_dict_deep(v)
            else:
                result[k] = v
        return result

    # ── JSON file processing ───────────────────────────────────────────────────

    def _read_json(self, path: Path) -> Optional[Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("Could not parse JSON for anonymization: %s — %s", path, exc)
            return None

    def _write_json(self, path: Path, data: Any) -> None:
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _anon_graph_json(self, data: Any) -> Any:
        """Anonymize graph.json with node/edge-aware transforms."""
        if not isinstance(data, dict):
            return data
        result: Dict[str, Any] = {}
        for k, v in data.items():
            if k == "nodes" and isinstance(v, list):
                result[k] = [
                    self.anon_resource_item(item) if isinstance(item, dict) else item
                    for item in v
                ]
            elif k == "edges" and isinstance(v, list):
                result[k] = [
                    self.anon_edge_item(item) if isinstance(item, dict) else item
                    for item in v
                ]
            elif isinstance(v, dict):
                result[k] = self._anon_dict_deep(v)
            elif isinstance(v, list):
                result[k] = [
                    self.anon_resource_item(item) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                result[k] = v
        return result

    def anon_json_file(self, path: Path) -> bool:
        """Anonymize a JSON file in-place.  Returns True if the file was found and rewritten."""
        if not path.exists() or not path.is_file():
            return False
        data = self._read_json(path)
        if data is None:
            return False

        name = path.name.lower()

        if name == "graph.json":
            result = self._anon_graph_json(data)
        elif isinstance(data, list):
            # inventory.json, seed.json, rbac.json, policy.json, candidates, etc.
            result = [
                self.anon_resource_item(item) if isinstance(item, dict) else item
                for item in data
            ]
        elif isinstance(data, dict):
            result = self._anon_dict_deep(data)
        else:
            return False

        self._write_json(path, result)
        log.info("Anonymized JSON: %s (%d bytes)", path.name, path.stat().st_size)
        return True

    # ── Text / log / drawio / csv / md processing ──────────────────────────────

    def anon_text_file(self, path: Path) -> bool:
        """Replace all known sensitive originals in a text file in-place.

        Should be called *after* all JSON files have been processed so
        that the mapping is fully populated.

        Returns True if the file was found (even if no replacements made).
        """
        if not path.exists() or not path.is_file():
            return False
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log.warning("Could not read text file for anonymization: %s — %s", path, exc)
            return False

        if not self._map:
            return True  # Nothing to replace yet

        # Sort by original length (longest first) to avoid partial-match collisions
        replacements = sorted(
            ((k.split(":", 1)[1], v) for k, v in self._map.items() if k.split(":", 1)[1]),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

        modified = content
        for original, alias in replacements:
            if len(original) < 6:
                # Skip very short originals — too much risk of false positives
                continue
            if original in modified:
                modified = modified.replace(original, alias)

        if modified != content:
            path.write_text(modified, encoding="utf-8")
            log.info("Anonymized text file: %s", path.name)
        return True

    # ── Orchestrator ───────────────────────────────────────────────────────────

    def apply_output_dir(self, output_dir: Path) -> None:
        """Process all output artifacts in *output_dir*, rewriting them in-place.

        Processing order:
        1. Structured JSON files — builds the alias mapping.
        2. Text / drawio / csv / md files — uses the populated mapping for
           string replacement.
        """
        if not output_dir.is_dir():
            log.warning("Output directory not found for anonymization: %s", output_dir)
            return

        # ── Step 1: structured JSON ────────────────────────────────────────────
        for name in _JSON_ARTIFACTS:
            self.anon_json_file(output_dir / name)

        # Applications subdirectory (per-app slice.json etc.)
        for json_path in output_dir.glob("applications/**/*.json"):
            self.anon_json_file(json_path)
        for json_path in output_dir.glob("migration-plan/**/*.json"):
            self.anon_json_file(json_path)

        # ── Step 2: text files (use populated mapping) ─────────────────────────
        self.anon_text_file(output_dir / "pipeline.log")

        for drawio_path in sorted(output_dir.glob("**/*.drawio")):
            self.anon_text_file(drawio_path)

        for csv_path in sorted(output_dir.glob("**/*.csv")):
            self.anon_text_file(csv_path)

        for md_path in sorted(output_dir.glob("**/*.md")):
            self.anon_text_file(md_path)

        log.info(
            "Anonymization complete for %s — %d unique mappings applied",
            output_dir,
            len(self._map),
        )

    # ── Map persistence ────────────────────────────────────────────────────────

    def save_map(self, path: Path) -> None:
        """Write the forward mapping to *path* for internal reference.

        .. warning::
            This file contains the original → alias mapping.  Keep it
            confidential; it must **not** be included in shared datasets.
        """
        by_category: Dict[str, Dict[str, str]] = {}
        for key, alias in sorted(self._map.items()):
            cat, original = key.split(":", 1)
            by_category.setdefault(cat, {})[original] = alias

        path.write_text(
            json.dumps(
                {
                    "_note": (
                        "Internal reference only — do NOT share this file. "
                        "It maps original Azure identifiers to their anonymized aliases."
                    ),
                    "mappings": by_category,
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        log.info("Anonymization map written to %s (%d entries)", path, len(self._map))

    @property
    def mapping_count(self) -> int:
        """Number of unique anonymization mappings built so far."""
        return len(self._map)
