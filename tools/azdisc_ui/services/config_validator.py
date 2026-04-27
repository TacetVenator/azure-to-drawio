"""Config validation service for Web UI."""
from __future__ import annotations

import logging
from typing import Any

from tools.azdisc.config import load_config_from_dict

log = logging.getLogger(__name__)


def validate_config_payload(data: dict) -> tuple[bool, list[str], dict | None]:
    """Validate a config dictionary.
    
    Args:
        data: Configuration dictionary to validate
        
    Returns:
        Tuple of (is_valid, error_messages, config_preview)
    """
    try:
        cfg = load_config_from_dict(data)
        preview = {
            "app": cfg.app,
            "subscriptions": cfg.subscriptions,
            "seedResourceGroups": cfg.seedResourceGroups,
            "outputDir": cfg.outputDir,
            "deepDiscovery": {
                "enabled": cfg.deepDiscovery.enabled,
                "searchStrings": cfg.deepDiscovery.searchStrings,
            },
            "applicationSplit": {
                "enabled": cfg.applicationSplit.enabled,
                "tagKeys": cfg.applicationSplit.tagKeys,
                "values": cfg.applicationSplit.values,
            },
            "migrationPlan": {
                "enabled": cfg.migrationPlan.enabled,
                "audience": cfg.migrationPlan.audience,
            },
        }
        return True, [], preview
    except ValueError as e:
        log.warning("Config validation failed: %s", e)
        return False, [str(e)], None
    except Exception as e:
        log.error("Unexpected error during config validation: %s", e)
        return False, [f"Unexpected error: {str(e)}"], None
