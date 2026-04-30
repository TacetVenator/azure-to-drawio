"""Pipeline execution service that runs actual azdisc stages."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
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
        auth_mode: str = "auto",
        allow_authorization_fallback: bool = False,
        token_available: bool = False,
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
        fallback_triggered = False
        fallback_reason = None
        fallback_stage = None

        requested_mode = str(auth_mode or "auto").strip().lower()
        if requested_mode not in {"auto", "token", "cli"}:
            requested_mode = "auto"

        effective_mode = "cli"
        if requested_mode == "token":
            if not token_available:
                return {
                    "status": "failed",
                    "stages": completed_stages,
                    "error": "Token auth requested but token is not available",
                    "auth_mode_effective": "token",
                    "fallback_triggered": False,
                    "fallback_reason": None,
                    "fallback_stage": None,
                }
            effective_mode = "token"
        elif requested_mode == "auto":
            if token_available:
                effective_mode = "token"
            else:
                effective_mode = "cli"
                fallback_triggered = True
                fallback_reason = "Token unavailable at run start"
                fallback_stage = "pipeline-start"

        def _is_auth_error(err: Exception) -> bool:
            message = str(err).lower()
            markers = ["401", "unauthorized", "token", "credential", "expired", "refresh"]
            return any(marker in message for marker in markers)

        def _is_authorization_error(err: Exception) -> bool:
            message = str(err).lower()
            markers = ["403", "forbidden", "insufficient", "not authorized", "permission", "denied"]
            return any(marker in message for marker in markers)
        
        try:
            config.ensure_output_dir()

            # Attach a file handler so all azdisc log output is captured per-run
            log_path = Path(config.outputDir) / "pipeline.log"
            _file_handler = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
            _file_handler.setLevel(logging.DEBUG)
            _file_handler.setFormatter(logging.Formatter(
                "%(asctime)s %(levelname)-8s %(name)s - %(message)s",
                datefmt="%H:%M:%S",
            ))
            _run_logger = logging.getLogger("tools")
            _run_logger.addHandler(_file_handler)

            def _log_marker(msg: str) -> None:
                try:
                    with open(log_path, "a", encoding="utf-8") as _f:
                        _f.write(f"{'=' * 64}\n{msg}\n{'=' * 64}\n")
                except Exception:
                    pass

            _log_marker(f"Pipeline started: app={config.app}")

            for stage in build_pipeline_stages(config):
                try:
                    if status_callback:
                        await status_callback(stage.name, "running")

                    log.info("Starting stage: %s", stage.name)
                    _log_marker(f"STAGE START: {stage.name}")

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
                    _log_marker(f"STAGE DONE: {stage.name}")
                except Exception as e:
                    pipeline_failed = True
                    pipeline_error = str(e)
                    log.error("Stage %s failed: %s", stage.name, e)
                    _log_marker(f"STAGE FAILED: {stage.name} — {e}")
                    completed_stages.append({
                        "name": stage.name,
                        "status": "failed",
                        "error": str(e),
                    })

                    if status_callback:
                        await status_callback(stage.name, "failed")

                    switched_to_cli = False
                    if effective_mode == "token" and not fallback_triggered:
                        can_fallback = _is_auth_error(e) or (allow_authorization_fallback and _is_authorization_error(e))
                        if can_fallback:
                            effective_mode = "cli"
                            fallback_triggered = True
                            fallback_reason = str(e)
                            fallback_stage = stage.name
                            switched_to_cli = True
                            log.warning(
                                "Switching run to CLI fallback after token-mode failure at stage %s: %s",
                                stage.name,
                                e,
                            )

                    if not continue_on_error and not switched_to_cli:
                        break

            result = {
                "status": "completed-with-errors" if pipeline_failed and continue_on_error else ("failed" if pipeline_failed else "success"),
                "stages": completed_stages,
                "error": pipeline_error,
                "auth_mode_effective": effective_mode,
                "fallback_triggered": fallback_triggered,
                "fallback_reason": fallback_reason,
                "fallback_stage": fallback_stage,
            }
            _log_marker(f"Pipeline ended: {result['status']}")
            _run_logger.removeHandler(_file_handler)
            _file_handler.close()
            return result
        except Exception as e:
            log.error("Pipeline failed with exception: %s", e)
            try:
                _log_marker(f"Pipeline exception: {e}")
                _run_logger.removeHandler(_file_handler)
                _file_handler.close()
            except Exception:
                pass
            return {
                "status": "failed",
                "stages": completed_stages,
                "error": str(e),
                "auth_mode_effective": effective_mode,
                "fallback_triggered": fallback_triggered,
                "fallback_reason": fallback_reason,
                "fallback_stage": fallback_stage,
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
