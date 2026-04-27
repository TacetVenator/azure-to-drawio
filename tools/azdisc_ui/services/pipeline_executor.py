"""Pipeline execution service that runs actual azdisc stages."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from pathlib import Path

from tools.azdisc.config import Config
from tools.azdisc.discover import run_seed, run_expand, run_policy, run_rbac
from tools.azdisc.graph import build_graph
from tools.azdisc.drawio import generate_drawio
from tools.azdisc.docs import generate_docs
from tools.azdisc.migration_plan import generate_migration_plan
from tools.azdisc.split import run_split
from tools.azdisc.telemetry import run_telemetry_enrichment
from tools.azdisc.master_report import generate_master_report

log = logging.getLogger(__name__)


class PipelineExecutor:
    """Executes azdisc pipeline stages synchronously.
    
    Wraps the full pipeline stages from azdisc CLI but exposes them
    for async/background execution by the UI. Each stage update can be
    logged for status tracking.
    """
    
    async def execute_full_pipeline(
        self,
        config: Config,
        status_callback: callable = None,
    ) -> dict:
        """Execute full pipeline from seed through docs and optional outputs.
        
        Args:
            config: Configuration for the run
            status_callback: Optional async callback(stage_name, status) for status updates
        
        Returns:
            Dict with pipeline summary: {"status": "success"|"failed", "stages": [...], "error": None|str}
            
        Raises:
            Exception if any stage fails and exception handling is strict
        """
        stages = [
            ("seed", lambda: run_seed(config)),
            ("expand", lambda: run_expand(config)),
            ("rbac", lambda: run_rbac(config) if config.includeRbac else None),
            ("policy", lambda: run_policy(config) if config.includePolicy else None),
            ("graph", lambda: build_graph(config)),
            ("drawio", lambda: generate_drawio(config)),
            ("docs", lambda: generate_docs(config)),
        ]
        
        # Optional stages
        if config.applicationSplit.enabled:
            stages.append(("split", lambda: run_split(config)))
        
        if config.migrationPlan.enabled:
            stages.append(("migration-plan", lambda: generate_migration_plan(config)))
        
        if config.enableTelemetry:
            stages.append(("telemetry", lambda: run_telemetry_enrichment(config)))
        
        # Master report (always last)
        stages.append(("master-report", lambda: generate_master_report(config)))
        
        completed_stages = []
        
        try:
            config.ensure_output_dir()
            
            for stage_name, stage_fn in stages:
                try:
                    if status_callback:
                        await status_callback(stage_name, "running")
                    
                    log.info("Starting stage: %s", stage_name)
                    
                    # Run stage in thread pool to avoid blocking event loop
                    await asyncio.to_thread(stage_fn)
                    
                    completed_stages.append({
                        "name": stage_name,
                        "status": "completed",
                        "error": None,
                    })
                    
                    if status_callback:
                        await status_callback(stage_name, "completed")
                    
                    log.info("Completed stage: %s", stage_name)
                except Exception as e:
                    log.error("Stage %s failed: %s", stage_name, e)
                    completed_stages.append({
                        "name": stage_name,
                        "status": "failed",
                        "error": str(e),
                    })
                    
                    if status_callback:
                        await status_callback(stage_name, "failed")
                    
                    # Continue other stages instead of failing immediately
                    # This allows partial outputs when some stages fail
            
            return {
                "status": "success",
                "stages": completed_stages,
                "error": None,
            }
        except Exception as e:
            log.error("Pipeline failed with exception: %s", e)
            return {
                "status": "failed",
                "stages": completed_stages,
                "error": str(e),
            }
    
    async def execute_split_only(self, config: Config) -> dict:
        """Execute only the application split stage.
        
        Requires existing graph/inventory outputs. Useful for reprocessing
        with different split configuration.
        """
        try:
            log.info("Starting split-only run for app=%s", config.app)
            await asyncio.to_thread(lambda: run_split(config))
            return {"status": "success", "error": None}
        except Exception as e:
            log.error("Split failed: %s", e)
            return {"status": "failed", "error": str(e)}
    
    async def execute_migration_plan_only(self, config: Config) -> dict:
        """Execute only the migration planning stage.
        
        Requires existing split outputs if applicationSplit is enabled.
        """
        try:
            log.info("Starting migration-plan-only run for app=%s", config.app)
            await asyncio.to_thread(lambda: generate_migration_plan(config))
            return {"status": "success", "error": None}
        except Exception as e:
            log.error("Migration plan generation failed: %s", e)
            return {"status": "failed", "error": str(e)}


# Global executor instance
_executor = PipelineExecutor()


def get_executor() -> PipelineExecutor:
    """Get the global pipeline executor instance."""
    return _executor
