"""Overview service for split and migration plan summarization."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from .candidate_explorer import summarize_candidates

log = logging.getLogger(__name__)


def load_split_overview(output_dir: str) -> Optional[dict]:
    """Load and summarize application split outputs.
    
    Args:
        output_dir: Root output directory from a run
    
    Returns:
        Dict with split summary or None if split not available
    """
    try:
        root = Path(output_dir)
        
        # Check if split outputs exist
        applications_file = root / "applications.md"
        if not applications_file.exists():
            return None
        
        applications_text = applications_file.read_text()
        
        # Try to load split metadata if available (applications/<slug>/slice.json)
        split_metadata = []
        for app_dir in root.glob("applications/*"):
            if app_dir.is_dir():
                manifest_file = app_dir / "slice.json"
                if manifest_file.exists():
                    try:
                        manifest = json.loads(manifest_file.read_text())
                        split_metadata.append({
                            "name": manifest.get("application", app_dir.name),
                            "resourceCount": manifest.get("directCount", 0) + manifest.get("sharedCount", 0),
                            "confidence": manifest.get("appBoundary", {}).get("confidence"),
                            "ambiguityLevel": manifest.get("appBoundary", {}).get("ambiguityLevel"),
                            "ambiguousResourceGroupCount": manifest.get("appBoundary", {}).get("ambiguousResourceGroupCount", 0),
                        })
                    except Exception as e:
                        log.warning("Failed to parse manifest for app %s: %s", app_dir.name, e)
        
        return {
            "available": True,
            "applicationsReportPath": "applications.md",
            "applicationCount": len(split_metadata),
            "applications": sorted(split_metadata, key=lambda x: x.get("confidence", 0)),
        }
    except Exception as e:
        log.error("Failed to load split overview: %s", e)
        return None


def load_migration_overview(output_dir: str) -> Optional[dict]:
    """Load and summarize migration plan outputs.
    
    Args:
        output_dir: Root output directory from a run
    
    Returns:
        Dict with migration summary or None if migration planning not available
    """
    try:
        root = Path(output_dir)
        
        # Migration output may be at output/migration-plan/migration-plan.json
        # or at output/migration-plan.json (custom output path).
        migration_plan_candidates = [
            root / "migration-plan" / "migration-plan.json",
            root / "migration-plan.json",
        ]
        migration_plan_file = next((path for path in migration_plan_candidates if path.exists()), None)
        if migration_plan_file is None:
            return None
        
        try:
            plan_data = json.loads(migration_plan_file.read_text())
        except Exception as e:
            log.warning("Failed to parse migration-plan.json: %s", e)
            return {"available": True, "error": "Could not parse migration plan"}
        
        # Extract summary info
        summary = plan_data.get("summary", {})
        waves = plan_data.get("waves", [])
        packs = plan_data.get("packs", [])
        
        wave_info = []
        for wave in waves:
            wave_info.append({
                "name": wave.get("name"),
                "description": wave.get("description"),
                "applicationCount": len(wave.get("applications", [])),
            })
        
        return {
            "available": True,
            "migrationPlanPath": "migration-plan.json",
            "summary": {
                "audience": summary.get("audience"),
                "applicationScope": summary.get("applicationScope"),
                "appBoundaryAnalysis": summary.get("appBoundaryAnalysis"),
            },
            "waveCount": len(waves),
            "waves": wave_info,
            "packCount": len(packs),
        }
    except Exception as e:
        log.error("Failed to load migration overview: %s", e)
        return None


def load_related_candidates(output_dir: str) -> Optional[dict]:
    """Load related resource candidates if available.
    
    Args:
        output_dir: Root output directory from a run
    
    Returns:
        Dict with candidates summary or None if not available
    """
    try:
        summary = summarize_candidates(output_dir)
        if not summary.get("available"):
            return None
        return summary
    except Exception as e:
        log.error("Failed to load related candidates: %s", e)
        return None
