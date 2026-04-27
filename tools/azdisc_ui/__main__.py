"""FastAPI entry point for azdisc_ui web interface."""
from __future__ import annotations

import json
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context: startup and cleanup."""
    log.info("azdisc_ui starting up")
    yield
    log.info("azdisc_ui shutting down")


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    
    app = FastAPI(
        title="Azure Discovery UI",
        description="Optional web interface for azdisc discovery and planning",
        version="0.1.0",
        lifespan=lifespan,
    )
    
    # Mount static files (CSS, JS)
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    
    # Configure templates
    templates_dir = Path(__file__).parent / "templates"
    templates_dir.mkdir(exist_ok=True)
    templates = Jinja2Templates(directory=str(templates_dir))
    
    # Health check endpoint
    @app.get("/health", tags=["system"])
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "service": "azdisc_ui"}
    
    # Index page
    @app.get("/", tags=["ui"])
    async def index(request: Request):
        """Serve index page."""
        return templates.TemplateResponse("index.html", {"request": request})
    
    # ============================================================================
    # Config API Routes (Phase 1B, 2)
    # ============================================================================
    
    @app.post("/api/config/validate", tags=["config"])
    async def validate_config(config_data: dict) -> dict:
        """Validate a config dictionary.
        
        Uses azdisc's validation logic without loading from a file.
        Returns validation result with errors (if any) and a preview of the config.
        """
        from tools.azdisc.config import load_config_from_dict
        
        try:
            cfg = load_config_from_dict(config_data)
            return {
                "valid": True,
                "errors": [],
                "preview": {
                    "app": cfg.app,
                    "subscriptions": cfg.subscriptions,
                    "seedResourceGroups": cfg.seedResourceGroups,
                    "outputDir": cfg.outputDir,
                    "deepDiscovery": {"enabled": cfg.deepDiscovery.enabled},
                    "applicationSplit": {"enabled": cfg.applicationSplit.enabled},
                    "migrationPlan": {"enabled": cfg.migrationPlan.enabled},
                },
            }
        except ValueError as e:
            return {
                "valid": False,
                "errors": [str(e)],
                "preview": None,
            }
    
    # ============================================================================
    # Pipeline Execution API Routes (Phase 2, 2A)
    # ============================================================================
    
    @app.post("/api/pipeline/run", tags=["pipeline"])
    async def run_pipeline(config_data: dict = None, config_path: str = None) -> dict:
        """Start a new pipeline run.
        
        Accepts either inline config_data or path to a config file.
        Returns run ID immediately; pipeline runs in background.
        """
        from tools.azdisc.config import load_config_from_dict, load_config
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        
        run_id = str(uuid.uuid4())[:8]
        runner = get_runner()
        
        try:
            # Support either raw config body or wrapped payload: {"config_data": {...}}
            if isinstance(config_data, dict) and "config_data" in config_data and isinstance(config_data["config_data"], dict):
                config_data = config_data["config_data"]

            # Load config from data or file
            if config_data:
                cfg = load_config_from_dict(config_data)
            elif config_path:
                cfg = load_config(config_path)
            else:
                raise ValueError("Must provide either config_data or config_path")
            
            # Start pipeline in background
            job = await runner.start_run(run_id, cfg)
            
            return {
                "run_id": run_id,
                "status": job["status"],
                "config_preview": {
                    "app": cfg.app,
                    "outputDir": cfg.outputDir,
                },
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/pipeline/jobs", tags=["pipeline"])
    async def list_pipeline_jobs() -> dict:
        """List all pipeline runs for dashboard selectors and status cards."""
        from tools.azdisc_ui.services.pipeline_runner import get_runner

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
    
    @app.get("/api/pipeline/status/{run_id}", tags=["pipeline"])
    async def pipeline_status(run_id: str) -> dict:
        """Get status of a pipeline run."""
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        
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
            "stages": job.get("stages", []),
        }
    
    # ============================================================================
    # Artifact API Routes (Phase 2B)
    # ============================================================================
    
    @app.get("/api/artifacts/list/{run_id}", tags=["artifacts"])
    async def list_artifacts(run_id: str, path: str = "") -> dict:
        """List artifacts from a run directory.
        
        Supports safe browsing with path sanitization to prevent traversal.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        
        runner = get_runner()
        job = runner.get_job(run_id)
        
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        root = Path(job["output_dir"])
        if not root.exists():
            return {"artifacts": [], "path": "/"}
        
        # Sanitize path to prevent traversal
        safe_path = Path(path.lstrip("/")) if path else Path()
        target = root / safe_path
        
        if not target.is_relative_to(root):
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
    
    @app.get("/api/artifacts/download/{run_id}/{file_path:path}", tags=["artifacts"])
    async def download_artifact(run_id: str, file_path: str) -> FileResponse:
        """Download a single artifact file.
        
        Enforces bounds checking to prevent serving files outside output directory.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        
        runner = get_runner()
        job = runner.get_job(run_id)
        
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        root = Path(job["output_dir"])
        target = root / file_path
        
        # Verify file is within bounds
        if not target.is_relative_to(root):
            raise HTTPException(status_code=403, detail="Access denied")
        
        if not target.exists():
            raise HTTPException(status_code=404, detail="File not found")
        
        if not target.is_file():
            raise HTTPException(status_code=400, detail="Not a file")
        
        return FileResponse(target, filename=target.name)
    
    # ============================================================================
    # Overview Routes (Phase 3, 3A)
    # ============================================================================
    
    @app.get("/api/split/overview/{run_id}", tags=["overview"])
    async def split_overview(run_id: str) -> dict:
        """Get overview of application split outputs.
        
        Returns summary of applications, confidence levels, and ambiguity flags.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.overview_loader import load_split_overview
        
        runner = get_runner()
        job = runner.get_job(run_id)
        
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        overview = load_split_overview(job["output_dir"])
        
        if overview is None:
            return {"available": False}
        
        return overview
    
    @app.get("/api/migration/overview/{run_id}", tags=["overview"])
    async def migration_overview(run_id: str) -> dict:
        """Get overview of migration planning outputs.
        
        Returns wave plans, confidence metrics, and related-resource candidates.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.overview_loader import load_migration_overview
        
        runner = get_runner()
        job = runner.get_job(run_id)
        
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        overview = load_migration_overview(job["output_dir"])
        
        if overview is None:
            return {"available": False}
        
        return overview
    
    # ============================================================================
    # Related Candidates / ARM Exploration (Phase 3A, 3B - skeletons)
    # ============================================================================
    
    @app.get("/api/candidates/related/{run_id}", tags=["candidates"])
    async def list_related_candidates(run_id: str) -> dict:
        """List related resource candidates and their filtering options.
        
        Phase 3B: Returns candidate metadata for UI filtering.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.overview_loader import load_related_candidates
        
        runner = get_runner()
        job = runner.get_job(run_id)
        
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        
        overview = load_related_candidates(job["output_dir"])
        
        if overview is None:
            return {"available": False, "candidates": [], "filters": {}}

        return overview
    
    @app.post("/api/candidates/filter/{run_id}", tags=["candidates"])
    async def filter_candidates(run_id: str, filter_spec: dict) -> dict:
        """Apply filters to related resource candidates.
        
        Placeholder for Phase 3B filtering UI.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.candidate_explorer import filter_candidates as apply_candidate_filter

        runner = get_runner()
        job = runner.get_job(run_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        return apply_candidate_filter(job["output_dir"], filter_spec or {})
    
    @app.get("/api/arm/deployments/{run_id}", tags=["arm"])
    async def list_arm_deployments(run_id: str) -> dict:
        """List deployment history records available for exploration.
        
        Placeholder for Phase 3A/4A ARM exploration UI.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.arm_explorer import list_deployments

        runner = get_runner()
        job = runner.get_job(run_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        return list_deployments(job["output_dir"])
    
    @app.post("/api/arm/search/{run_id}", tags=["arm"])
    async def search_arm_templates(run_id: str, payload: dict) -> dict:
        """Search deployment templates for keywords (e.g., 'SAP', 'ERP').
        
        Searches deployment history resources in inventory artifacts.
        """
        from tools.azdisc_ui.services.pipeline_runner import get_runner
        from tools.azdisc_ui.services.arm_explorer import search_deployments

        runner = get_runner()
        job = runner.get_job(run_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        keywords = payload.get("keywords", []) if isinstance(payload, dict) else []
        limit = payload.get("limit", 200) if isinstance(payload, dict) else 200
        if not isinstance(keywords, list):
            raise HTTPException(status_code=400, detail="keywords must be a list of strings")

        return search_deployments(job["output_dir"], keywords, limit=int(limit))
    
    return app


if __name__ == "__main__":
    import uvicorn
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    
    app = create_app()
    
    print("Starting azdisc_ui on http://localhost:8000")
    print("  config validation: POST /api/config/validate")
    print("  pipeline run:      POST /api/pipeline/run")
    print("  pipeline status:   GET  /api/pipeline/status/{run_id}")
    print("  artifacts:         GET  /api/artifacts/list/{run_id}")
    print("  UI dashboard:      GET  /")
    print()
    
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        log_level="info",
    )
