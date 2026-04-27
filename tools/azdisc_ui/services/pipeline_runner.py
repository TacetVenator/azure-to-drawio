"""Pipeline runner service for background job execution."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from tools.azdisc.config import Config

log = logging.getLogger(__name__)


class PipelineRunner:
    """Manages background pipeline execution.
    
    Phase 2A: Simple in-process job tracking. Later can be extended to use
    persistent storage or external task queues.
    """
    
    def __init__(self):
        """Initialize runner with empty job registry."""
        self.jobs: Dict[str, Dict[str, Any]] = {}
    
    async def start_run(
        self,
        run_id: str,
        config: Config,
        executor: Optional[Callable[[Config], None]] = None,
    ) -> Dict[str, Any]:
        """Start a new pipeline run in the background.
        
        Args:
            run_id: Unique identifier for this run
            config: Config instance to use
            executor: Optional async executor for testing. If None, uses real azdisc pipeline.
        
        Returns:
            Job metadata dictionary
        """
        if run_id in self.jobs:
            raise ValueError(f"Run {run_id} already exists")
        
        job = {
            "id": run_id,
            "status": "running",
            "config": config,
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": None,
            "error": None,
            "output_dir": config.outputDir,
            "stages": [],
        }
        
        self.jobs[run_id] = job
        
        # Schedule background execution
        if executor:
            asyncio.create_task(self._execute_custom(run_id, executor))
        else:
            asyncio.create_task(self._execute_real_pipeline(run_id, config))
        
        return job
    
    async def _execute_real_pipeline(self, run_id: str, config: Config) -> None:
        """Execute real azdisc pipeline and update job status.
        
        Args:
            run_id: Job ID
            config: Configuration for the run
        """
        try:
            from .pipeline_executor import get_executor
            
            job = self.jobs[run_id]
            executor = get_executor()
            
            log.info("Starting real pipeline for run %s (app=%s)", run_id, config.app)
            
            # Define status callback to track stage progress
            async def stage_status_callback(stage_name: str, status: str) -> None:
                if stage_name not in [s["name"] for s in job["stages"]]:
                    job["stages"].append({"name": stage_name, "status": status})
                else:
                    for stage in job["stages"]:
                        if stage["name"] == stage_name:
                            stage["status"] = status
                            break
                log.info("Stage %s: %s (run %s)", stage_name, status, run_id)
            
            # Execute pipeline with status callbacks
            result = await executor.execute_full_pipeline(config, stage_status_callback)
            
            job["status"] = result["status"]
            job["stages"] = result.get("stages", job["stages"])
            job["error"] = result.get("error")
            job["completed_at"] = datetime.utcnow().isoformat()
            
            log.info("Pipeline %s for run %s: %s", result["status"], run_id, config.app)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = datetime.utcnow().isoformat()
            log.error("Pipeline exception for run %s: %s", run_id, e)
    
    async def _execute_custom(self, run_id: str, executor: Callable[[Config], None]) -> None:
        """Execute custom executor and update job status (for testing).
        
        Args:
            run_id: Job ID
            executor: Async function to execute
        """
        try:
            job = self.jobs[run_id]
            config = job["config"]
            
            log.info("Starting custom executor for run %s (app=%s)", run_id, config.app)
            await executor(config)
            
            job["status"] = "completed"
            job["completed_at"] = datetime.utcnow().isoformat()
            log.info("Custom executor completed for run %s", run_id)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = datetime.utcnow().isoformat()
            log.error("Custom executor failed for run %s: %s", run_id, e)
    
    def get_job(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get job status.
        
        Args:
            run_id: Job ID
            
        Returns:
            Job metadata or None if not found
        """
        return self.jobs.get(run_id)
    
    def list_jobs(self) -> list[Dict[str, Any]]:
        """List all jobs (for dashboard).
        
        Returns:
            List of job metadata dicts
        """
        return list(self.jobs.values())


# Global runner instance
_runner = PipelineRunner()


def get_runner() -> PipelineRunner:
    """Get the global pipeline runner instance."""
    return _runner
