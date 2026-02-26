"""Utility helpers: logging setup, stable IDs, ARM ID parsing."""
import hashlib
import logging
import re
import sys

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
