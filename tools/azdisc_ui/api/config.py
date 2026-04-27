"""Config validation API routes."""
from __future__ import annotations

import logging
from fastapi import APIRouter

from ..services.config_validator import validate_config_payload

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/config", tags=["config"])


@router.post("/validate")
async def validate_config(config_data: dict) -> dict:
    """Validate a config dictionary.
    
    Uses azdisc's validation logic without loading from a file.
    Returns validation result with errors (if any) and a preview of the config.
    """
    is_valid, errors, preview = validate_config_payload(config_data)
    
    return {
        "valid": is_valid,
        "errors": errors,
        "preview": preview,
    }
