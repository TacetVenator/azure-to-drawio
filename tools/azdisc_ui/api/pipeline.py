"""Pipeline execution API routes."""
from __future__ import annotations

import logging
import uuid
from fastapi import APIRouter, HTTPException

from tools.azdisc.config import load_config_from_dict, load_config
from ..services.pipeline_runner import get_runner

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/run")
async def run_pipeline(config_data: dict = None, config_path: str = None) -> dict:
    """Start a new pipeline run.
    
    Accepts either inline config_data or path to a config file.
    Returns run ID immediately; pipeline runs in background.
    """
    run_id = str(uuid.uuid4())[:8]
    runner = get_runner()
    
    try:
        # Load config from data or file
        if config_data:
            cfg = load_config_from_dict(config_data)
        elif config_path:
            cfg = load_config(config_path)
        else:
            raise ValueError("Must provide either config_data or config_path")
        
        # Start pipeline in background
        # TODO: Phase 2A - implement actual pipeline executor from azdisc
        job = await runner.start_run(run_id, cfg)
        
        return {
            "run_id": run_id,
            "status": job["status"],
            "config_preview": {
                "app": cfg.app,
                "outputDir": cfg.outputDir,
            },
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("Failed to start pipeline: %s", e)
        raise HTTPException(status_code=500, detail="Failed to start pipeline")


@router.get("/status/{run_id}")
async def pipeline_status(run_id: str) -> dict:
    """Get status of a pipeline run."""
    runner = get_runner()
    job = runner.get_job(run_id)
    
    if not job:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    
    return {
        "run_id": run_id,
        "status": job["status"],
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "error": job.get("error"),
    }


@router.get("/jobs")
async def list_jobs() -> dict:
    """List all pipeline runs (for dashboard)."""
    runner = get_runner()
    jobs = runner.list_jobs()
    
    return {
        "total": len(jobs),
        "jobs": [
            {
                "run_id": job["id"],
                "status": job["status"],
                "app": job["config"].app,
                "created_at": job["created_at"],
                "completed_at": job.get("completed_at"),
            }
            for job in jobs
        ],
    }
