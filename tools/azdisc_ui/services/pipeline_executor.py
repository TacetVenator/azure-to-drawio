"""Pipeline execution service that runs actual azdisc stages."""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from tools.azdisc.config import Config
from tools.azdisc.pipeline import build_pipeline_stages

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
        status_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        continue_on_error: bool = False,
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
        completed_stages = []
        pipeline_failed = False
        pipeline_error = None
        
        try:
            config.ensure_output_dir()

            for stage in build_pipeline_stages(config):
                try:
                    if status_callback:
                        await status_callback(stage.name, "running")

                    log.info("Starting stage: %s", stage.name)

                    # Run stage in thread pool to avoid blocking event loop
                    await asyncio.to_thread(stage.action)

                    completed_stages.append({
                        "name": stage.name,
                        "status": "completed",
                        "error": None,
                    })

                    if status_callback:
                        await status_callback(stage.name, "completed")

                    log.info("Completed stage: %s", stage.name)
                except Exception as e:
                    pipeline_failed = True
                    pipeline_error = str(e)
                    log.error("Stage %s failed: %s", stage.name, e)
                    completed_stages.append({
                        "name": stage.name,
                        "status": "failed",
                        "error": str(e),
                    })

                    if status_callback:
                        await status_callback(stage.name, "failed")

                    if not continue_on_error:
                        break

            return {
                "status": "completed-with-errors" if pipeline_failed and continue_on_error else ("failed" if pipeline_failed else "success"),
                "stages": completed_stages,
                "error": pipeline_error,
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
