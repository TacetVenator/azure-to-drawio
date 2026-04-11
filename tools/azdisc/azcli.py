"""Shared Azure CLI execution helpers."""
from __future__ import annotations

import logging
import subprocess
from typing import Any, Optional, Type

from .util import parse_json_text

log = logging.getLogger(__name__)


def run_az_json(
    args: list[str],
    *,
    context: str = "Azure CLI JSON output",
    expected_type: Optional[Type[Any]] = None,
    advice: Optional[str] = None,
) -> Any:
    """Run an Azure CLI command and parse its JSON output."""
    cmd = ["az"] + args
    log.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"az command failed (rc={result.returncode}):\n"
            f"  cmd: {' '.join(cmd)}\n"
            f"  stderr: {result.stderr.strip()}"
        )
    if not result.stdout.strip():
        raise RuntimeError(
            f"Azure CLI returned empty stdout for: {' '.join(cmd)}. "
            f"stderr: {result.stderr.strip() or '<empty>'}"
        )
    return parse_json_text(
        result.stdout,
        source=" ".join(cmd),
        context=context,
        expected_type=expected_type,
        advice=advice,
    )
