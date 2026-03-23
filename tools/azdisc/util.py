"""Utility helpers: logging setup, stable IDs, ARM ID parsing."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any, Optional, Type

ARM_ID_RE = re.compile(
    r'/subscriptions/[^\s/]+/(?:resourcegroups/[^\s/]+/)?providers/[^\s/]+(?:/[^\s/]+/[^\s/]+)*',
    re.IGNORECASE,
)

# Patterns for ARM-like IDs that are NOT actual deployable resources.
# These are marketplace references, location-scoped metadata, etc.
_NON_RESOURCE_PATTERNS = re.compile(
    r'/providers/microsoft\.compute/locations/'
    r'|/providers/microsoft\.compute/galleries/'
    r'|/providers/microsoft\.marketplace/'
    r'|/providers/microsoft\.compute/images/'
    r'|/providers/microsoft\.authorization/roleDefinitions/'
    r'|/providers/microsoft\.authorization/policyDefinitions/',
    re.IGNORECASE,
)


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        stream=sys.stderr,
        level=level,
        format='%(asctime)s %(levelname)s %(name)s: %(message)s',
        datefmt='%H:%M:%S',
    )


def stable_id(resource_id: str) -> str:
    """Return a short stable hex ID derived from a resource ID."""
    return hashlib.sha256(resource_id.lower().encode()).hexdigest()[:16]


def normalize_id(arm_id: str) -> str:
    """Lowercase and strip trailing slashes from an ARM resource ID."""
    return arm_id.lower().rstrip('/')


def _is_resource_id(arm_id: str) -> bool:
    """Return False for ARM-like IDs that are not actual deployable resources."""
    return not _NON_RESOURCE_PATTERNS.search(arm_id)


def extract_arm_ids(obj, seen=None):
    """Recursively walk obj (dict/list/str) and yield normalized ARM IDs."""
    if seen is None:
        seen = set()
    if isinstance(obj, str):
        for m in ARM_ID_RE.finditer(obj):
            nid = normalize_id(m.group(0))
            if nid not in seen and _is_resource_id(nid):
                seen.add(nid)
                yield nid
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from extract_arm_ids(v, seen)
    elif isinstance(obj, list):
        for item in obj:
            yield from extract_arm_ids(item, seen)


def _json_excerpt(text: str, pos: int, radius: int = 60) -> str:
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    excerpt = text[start:end].replace("\n", "\\n")
    pointer = pos - start
    return f"{excerpt}\n{' ' * pointer}^"


def parse_json_text(
    text: str,
    *,
    source: str,
    context: str,
    expected_type: Optional[Type[Any]] = None,
    advice: Optional[str] = None,
) -> Any:
    """Parse JSON text with actionable error context."""
    if not text.strip():
        message = f"{context} from {source} is empty."
        if advice:
            message = f"{message} {advice}"
        raise RuntimeError(message)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        excerpt = _json_excerpt(text, exc.pos)
        message = (
            f"{context} from {source} is invalid JSON at "
            f"line {exc.lineno} column {exc.colno}: {exc.msg}.\n"
            f"Excerpt: {excerpt}"
        )
        if advice:
            message = f"{message}\n{advice}"
        raise RuntimeError(message) from exc
    if expected_type is not None and not isinstance(data, expected_type):
        expected_name = getattr(expected_type, "__name__", str(expected_type))
        actual_name = type(data).__name__
        message = (
            f"{context} from {source} has unexpected JSON shape: "
            f"expected {expected_name}, got {actual_name}."
        )
        if advice:
            message = f"{message} {advice}"
        raise RuntimeError(message)
    return data


def load_json_file(
    path: Path,
    *,
    context: str,
    expected_type: Optional[Type[Any]] = None,
    advice: Optional[str] = None,
) -> Any:
    """Read and parse a JSON file with actionable error context."""
    return parse_json_text(
        path.read_text(),
        source=str(path),
        context=context,
        expected_type=expected_type,
        advice=advice,
    )

