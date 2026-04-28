"""Pipeline runner service for background job execution."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from tools.azdisc.config import Config, load_config_from_dict

log = logging.getLogger(__name__)


class PipelineRunner:
    """Manages background pipeline execution.
    
    Phase 2A: Simple in-process job tracking. Later can be extended to use
    persistent storage or external task queues.
    """
    
    def __init__(self, state_dir: Path = None):
        """Initialize runner with empty job registry."""
        self.state_dir = state_dir if state_dir is not None else Path.cwd() / ".azdisc_ui_runs"
        self.state_file = self.state_dir / "runner-state" / "jobs.json"
        self.jobs: Dict[str, Dict[str, Any]] = {}
        self._load_state()

    def _serialize_job(self, job: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": job["id"],
            "status": job["status"],
            "config": asdict(job["config"]),
            "created_at": job.get("created_at"),
            "completed_at": job.get("completed_at"),
            "error": job.get("error"),
            "output_dir": job.get("output_dir"),
            "stages": list(job.get("stages", [])),
            "continue_on_error": bool(job.get("continue_on_error", False)),
            "source_mode": str(job.get("source_mode", "pipeline")),
            "imported_artifacts": list(job.get("imported_artifacts", [])),
        }

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": [self._serialize_job(job) for job in self.jobs.values()],
            "saved_at": datetime.utcnow().isoformat(),
        }
        self.state_file.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            payload = json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to parse runner state file %s: %s", self.state_file, e)
            return

        loaded = 0
        for entry in payload.get("jobs", []):
            if not isinstance(entry, dict):
                continue
            run_id = str(entry.get("id", "")).strip()
            if not run_id:
                continue
            source_mode = str(entry.get("source_mode", "pipeline"))
            raw_cfg = entry.get("config", {})
            try:
                cfg = load_config_from_dict(raw_cfg)
            except Exception as e:
                if source_mode == "imported":
                    cfg = Config(
                        app=str(raw_cfg.get("app", "imported-run")),
                        subscriptions=list(raw_cfg.get("subscriptions", [])) if isinstance(raw_cfg, dict) else [],
                        seedResourceGroups=list(raw_cfg.get("seedResourceGroups", [])) if isinstance(raw_cfg, dict) and raw_cfg.get("seedResourceGroups") else ["imported-artifact"],
                        outputDir=str(raw_cfg.get("outputDir", entry.get("output_dir", ""))) if isinstance(raw_cfg, dict) else str(entry.get("output_dir", "")),
                    )
                else:
                    log.warning("Skipping invalid persisted config for run %s: %s", run_id, e)
                    continue

            status = str(entry.get("status", "completed")).strip() or "completed"
            error = entry.get("error")
            if status == "running":
                status = "failed"
                error = "Recovered after process restart while run was still in progress"

            self.jobs[run_id] = {
                "id": run_id,
                "status": status,
                "config": cfg,
                "created_at": entry.get("created_at") or datetime.utcnow().isoformat(),
                "completed_at": entry.get("completed_at") or (datetime.utcnow().isoformat() if status != "running" else None),
                "error": error,
                "output_dir": entry.get("output_dir") or cfg.outputDir,
                "stages": list(entry.get("stages", [])),
                "continue_on_error": bool(entry.get("continue_on_error", False)),
                "source_mode": source_mode,
                "imported_artifacts": list(entry.get("imported_artifacts", [])),
            }
            loaded += 1

        if loaded:
            log.info("Recovered %d persisted pipeline runs from %s", loaded, self.state_file)
    
    async def start_run(
        self,
        run_id: str,
        config: Config,
        executor: Optional[Callable[[Config], None]] = None,
        *,
        continue_on_error: bool = False,
        source_mode: str = "pipeline",
        imported_artifacts: Optional[list[str]] = None,
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
            "continue_on_error": continue_on_error,
            "source_mode": source_mode,
            "imported_artifacts": list(imported_artifacts or []),
        }
        
        self.jobs[run_id] = job
        self._save_state()
        
        # Schedule background execution
        if executor:
            asyncio.create_task(self._execute_custom(run_id, executor))
        else:
            asyncio.create_task(self._execute_real_pipeline(run_id, config, continue_on_error))
        
        return job
    
    async def _execute_real_pipeline(self, run_id: str, config: Config, continue_on_error: bool) -> None:
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
                self._save_state()
                log.info("Stage %s: %s (run %s)", stage_name, status, run_id)
            
            # Execute pipeline with status callbacks
            result = await executor.execute_full_pipeline(
                config,
                stage_status_callback,
                continue_on_error=continue_on_error,
            )
            
            job["status"] = result["status"]
            job["stages"] = result.get("stages", job["stages"])
            job["error"] = result.get("error")
            job["completed_at"] = datetime.utcnow().isoformat()
            self._save_state()
            
            log.info("Pipeline %s for run %s: %s", result["status"], run_id, config.app)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = datetime.utcnow().isoformat()
            self._save_state()
            log.error("Pipeline exception for run %s: %s", run_id, e)

    def register_imported_run(
        self,
        run_id: str,
        config: Config,
        *,
        imported_artifacts: list[str],
    ) -> Dict[str, Any]:
        """Register a completed run backed by imported local artifacts."""
        if run_id in self.jobs:
            raise ValueError(f"Run {run_id} already exists")

        job = {
            "id": run_id,
            "status": "completed",
            "config": config,
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": datetime.utcnow().isoformat(),
            "error": None,
            "output_dir": config.outputDir,
            "stages": [],
            "continue_on_error": False,
            "source_mode": "imported",
            "imported_artifacts": list(imported_artifacts),
        }
        self.jobs[run_id] = job
        self._save_state()
        return job
    
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
            self._save_state()
            log.info("Custom executor completed for run %s", run_id)
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            job["completed_at"] = datetime.utcnow().isoformat()
            self._save_state()
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
