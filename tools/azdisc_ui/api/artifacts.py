"""Artifact browsing and download API routes."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..services.pipeline_runner import get_runner

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/artifacts", tags=["artifacts"])


@router.get("/list/{run_id}")
async def list_artifacts(run_id: str, path: str = "") -> dict:
    """List artifacts from a run directory.
    
    Supports safe browsing with path sanitization to prevent traversal.
    """
    runner = get_runner()
    job = runner.get_job(run_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    root = Path(job["output_dir"])
    if not root.exists():
        return {"artifacts": [], "path": "/"}
    
    # Sanitize path to prevent traversal
    try:
        safe_path = Path(path).relative_to("/") if path else Path()
        target = root / safe_path
        
        # Verify target is within root
        target.resolve().relative_to(root.resolve())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Path traversal not allowed")
    
    artifacts = []
    if target.exists() and target.is_dir():
        for item in sorted(target.iterdir()):
            artifacts.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
                "path": str(item.relative_to(root)),
            })
    
    return {
        "artifacts": artifacts,
        "path": str(target.relative_to(root)) or "/",
    }


@router.get("/download/{run_id}/{file_path:path}")
async def download_artifact(run_id: str, file_path: str) -> FileResponse:
    """Download a single artifact file.
    
    Enforces bounds checking to prevent serving files outside output directory.
    """
    runner = get_runner()
    job = runner.get_job(run_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    root = Path(job["output_dir"])
    
    try:
        target = root / file_path
        # Verify target is within bounds
        target.resolve().relative_to(root.resolve())
    except (ValueError, RuntimeError):
        raise HTTPException(status_code=403, detail="Access denied")
    
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Not a file")
    
    return FileResponse(target, filename=target.name)
