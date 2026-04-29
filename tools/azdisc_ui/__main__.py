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

    def render_template(name: str, request: Request, context: dict | None = None):
        """Render templates across Starlette versions with differing signatures."""
        ctx = dict(context or {})
        ctx.setdefault("request", request)

        try:
            # Starlette 0.37+ expects request/name/context keyword arguments.
            return templates.TemplateResponse(request=request, name=name, context=ctx)
        except TypeError:
            # Backward compatibility for older Starlette versions.
            return templates.TemplateResponse(name, ctx)
    
    # Health check endpoint
    @app.get("/health", tags=["system"])
    async def health() -> dict:
        """Health check endpoint."""
        return {"status": "ok", "service": "azdisc_ui"}
    
    # Index page
    @app.get("/", tags=["ui"])
    async def index(request: Request):
        """Serve index page."""
        return render_template("index.html", request)
    
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

    @app.get("/api/config/presets", tags=["config"])
    async def list_config_presets() -> dict:
        """List built-in config presets that can be applied in the UI."""
        from tools.azdisc.config_presets import list_config_presets as load_presets

        presets = load_presets(include_config=True)
        return {
            "presets": presets,
            "total": len(presets),
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
                execution_options = config_data.get("execution_options", {})
                continue_on_error = bool(execution_options.get("continueOnError", False))
                auth_mode = str(execution_options.get("authMode", "auto")).strip().lower() or "auto"
                allow_authorization_fallback = bool(execution_options.get("allowAuthorizationFallback", False))
                token_available = bool(execution_options.get("tokenAvailable", False))
                config_data = config_data["config_data"]
            else:
                continue_on_error = False
                auth_mode = "auto"
                allow_authorization_fallback = False
                token_available = False

            if auth_mode not in {"auto", "token", "cli"}:
                raise ValueError("execution_options.authMode must be one of: auto, token, cli")

            # Load config from data or file
            if config_data:
                cfg = load_config_from_dict(config_data)
            elif config_path:
                cfg = load_config(config_path)
            else:
                raise ValueError("Must provide either config_data or config_path")
            
            # Start pipeline in background
            job = await runner.start_run(
                run_id,
                cfg,
                continue_on_error=continue_on_error,
                auth_mode_requested=auth_mode,
                allow_authorization_fallback=allow_authorization_fallback,
                token_available=token_available,
            )
            
            return {
                "run_id": run_id,
                "status": job["status"],
                "config_preview": {
                    "app": cfg.app,
                    "outputDir": cfg.outputDir,
                },
                "execution": {
                    "continueOnError": continue_on_error,
                    "authMode": auth_mode,
                    "allowAuthorizationFallback": allow_authorization_fallback,
                    "tokenAvailable": token_available,
                },
                "auth": {
                    "auth_mode_requested": job.get("auth_mode_requested", auth_mode),
                    "auth_mode_effective": job.get("auth_mode_effective", "cli"),
                    "fallback_triggered": job.get("fallback_triggered", False),
                    "fallback_reason": job.get("fallback_reason"),
                    "fallback_stage": job.get("fallback_stage"),
                },
            }
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/import/run", tags=["pipeline", "artifacts"])
    async def import_run(payload: dict) -> dict:
        """Create a completed run from existing local seed/inventory artifacts."""
        from tools.azdisc.config import Config
        from tools.azdisc_ui.services.artifact_importer import default_import_output_dir, import_artifacts
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")

        app_name = str(payload.get("app", "")).strip() or "imported-run"
        subscriptions = payload.get("subscriptions", [])
        if not isinstance(subscriptions, list):
            raise HTTPException(status_code=400, detail="subscriptions must be a list of strings")

        sources = payload.get("sourceFiles", [])
        if not isinstance(sources, list) or not sources:
            raise HTTPException(status_code=400, detail="sourceFiles must be a non-empty list")

        run_id = str(uuid.uuid4())[:8]
        output_dir = str(payload.get("outputDir", "")).strip() or str(default_import_output_dir(run_id))
        try:
            imported = import_artifacts(output_dir=output_dir, sources=sources)
            cfg = Config(
                app=app_name,
                subscriptions=[str(item).strip() for item in subscriptions if str(item).strip()],
                seedResourceGroups=["imported-artifact"],
                outputDir=output_dir,
            )
            runner = get_runner()
            runner.register_imported_run(
                run_id,
                cfg,
                imported_artifacts=[item.target_name for item in imported],
            )
            return {
                "run_id": run_id,
                "status": "completed",
                "source_mode": "imported",
                "outputDir": output_dir,
                "artifacts": [
                    {
                        "artifactType": item.artifact_type,
                        "targetName": item.target_name,
                        "sizeBytes": item.size_bytes,
                        "sha256": item.sha256,
                    }
                    for item in imported
                ],
            }
        except ValueError as e:
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
                    "source_mode": job.get("source_mode", "pipeline"),
                    "continue_on_error": job.get("continue_on_error", False),
                    "auth_mode_requested": job.get("auth_mode_requested", "auto"),
                    "auth_mode_effective": job.get("auth_mode_effective", "cli"),
                    "fallback_triggered": job.get("fallback_triggered", False),
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
            "source_mode": job.get("source_mode", "pipeline"),
            "continue_on_error": job.get("continue_on_error", False),
            "imported_artifacts": job.get("imported_artifacts", []),
            "auth_mode_requested": job.get("auth_mode_requested", "auto"),
            "auth_mode_effective": job.get("auth_mode_effective", "cli"),
            "allow_authorization_fallback": job.get("allow_authorization_fallback", False),
            "fallback_triggered": job.get("fallback_triggered", False),
            "fallback_reason": job.get("fallback_reason"),
            "fallback_stage": job.get("fallback_stage"),
            "stages": job.get("stages", []),
        }
    
    @app.get("/api/pipeline/logs/{run_id}", tags=["pipeline"])
    async def pipeline_logs(run_id: str, tail: int = 300) -> str:
        """Return the last *tail* lines from the pipeline.log for a run."""
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        runner = get_runner()
        job = runner.get_job(run_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        log_path = Path(job.get("output_dir", "")) / "pipeline.log"
        if not log_path.exists():
            return "(pipeline.log not yet available — run may still be initialising)"

        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-tail:]) if len(lines) > tail else "\n".join(lines)
        except Exception as exc:
            return f"(could not read log: {exc})"
    
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

    @app.get("/api/artifacts/diagrams/{run_id}", tags=["artifacts"])
    async def list_diagram_artifacts(run_id: str) -> dict:
        """List diagram-like artifacts available for embedded preview."""
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        runner = get_runner()
        job = runner.get_job(run_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        root = Path(job["output_dir"])
        if not root.exists():
            return {"diagrams": []}

        diagrams = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue

            suffix = path.suffix.lower()
            if suffix not in {".drawio", ".mxlibrary", ".svg", ".png"}:
                continue

            rel = str(path.relative_to(root))
            lower_rel = rel.lower()
            if lower_rel.startswith("applications/") and lower_rel.endswith("/diagram.drawio"):
                diagram_class = "application-slice"
                label = f"Application Slice: {path.parent.name}"
            elif path.name.lower() == "diagram.drawio":
                diagram_class = "global-topology"
                label = "Global Topology"
            elif suffix in {".svg", ".png"}:
                diagram_class = "image"
                label = f"Image: {path.name}"
            else:
                diagram_class = "drawio"
                label = path.name

            diagrams.append(
                {
                    "path": rel,
                    "name": path.name,
                    "kind": "image" if suffix in {".svg", ".png"} else "drawio",
                    "diagramClass": diagram_class,
                    "label": label,
                    "size": path.stat().st_size,
                }
            )

        diagrams.sort(key=lambda item: (item.get("diagramClass", ""), item.get("path", "")))
        return {"diagrams": diagrams}

    @app.get("/api/diagram-beta/viewer", tags=["artifacts"])
    async def diagram_beta_viewer() -> dict:
        """Return local embedded viewer URL when a bundled diagrams.net viewer is available."""
        ui_static_root = Path(__file__).resolve().parent / "static"
        local_candidates = [
            ui_static_root / "vendor" / "diagrams-net" / "index.html",
            ui_static_root / "vendor" / "drawio" / "index.html",
        ]
        for candidate in local_candidates:
            if candidate.exists() and candidate.is_file():
                rel = candidate.relative_to(ui_static_root).as_posix()
                return {
                    "available": True,
                    "url": f"/static/{rel}?embed=1&ui=min&spin=1&proto=json",
                    "source": "local-static",
                }
        return {
            "available": False,
            "url": None,
            "source": "none",
            "hint": "Place a bundled diagrams.net build at static/vendor/diagrams-net/index.html",
        }

    @app.get("/api/diagram/scope-options/{run_id}", tags=["artifacts"])
    async def diagram_scope_options(run_id: str, target: str = "resourcegroup", limit: int = 500) -> dict:
        """Return scope dropdown options for scoped diagram generation."""
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        target_mode = str(target or "").strip().lower()
        if target_mode not in {"tag", "resourcegroup", "resource"}:
            raise HTTPException(status_code=400, detail="target must be one of: tag, resourcegroup, resource")

        runner = get_runner()
        job = runner.get_job(run_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        root = Path(job["output_dir"])
        inv_path = root / "inventory.json"
        if not inv_path.exists():
            raise HTTPException(status_code=404, detail="inventory.json not found for this run")

        try:
            inventory = json.loads(inv_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not parse inventory.json: {exc}")

        if not isinstance(inventory, list):
            raise HTTPException(status_code=400, detail="inventory.json must be a JSON array")

        safe_limit = max(1, min(int(limit), 5000))

        if target_mode == "resourcegroup":
            counts: dict[str, int] = {}
            for row in inventory:
                if not isinstance(row, dict):
                    continue
                rg = str(row.get("resourceGroup") or "").strip()
                if not rg:
                    continue
                counts[rg] = counts.get(rg, 0) + 1
            options = [
                {"value": rg, "label": f"{rg} ({count} resources)", "count": count}
                for rg, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:safe_limit]
            ]
            return {"target": target_mode, "options": options}

        if target_mode == "tag":
            counts: dict[str, int] = {}
            for row in inventory:
                if not isinstance(row, dict):
                    continue
                tags = row.get("tags")
                if not isinstance(tags, dict):
                    continue
                for key, value in tags.items():
                    k = str(key or "").strip()
                    v = str(value or "").strip()
                    if not k or not v:
                        continue
                    pair = f"{k}={v}"
                    counts[pair] = counts.get(pair, 0) + 1
            options = [
                {"value": pair, "label": f"{pair} ({count} resources)", "count": count}
                for pair, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].lower()))[:safe_limit]
            ]
            return {"target": target_mode, "options": options}

        # target_mode == "resource"
        resources: list[dict] = []
        for row in inventory:
            if not isinstance(row, dict):
                continue
            rid = str(row.get("id") or "").strip()
            if not rid:
                continue
            name = str(row.get("name") or rid.split("/")[-1])
            rtype = str(row.get("type") or "unknown")
            rg = str(row.get("resourceGroup") or "")
            label = f"{name} ({rtype})" + (f" - {rg}" if rg else "")
            resources.append({"value": rid, "label": label, "count": 1})

        resources.sort(key=lambda row: row["label"].lower())
        return {"target": target_mode, "options": resources[:safe_limit]}

    @app.post("/api/diagram/generate-scoped", tags=["artifacts"])
    async def generate_scoped_diagram(payload: dict) -> dict:
        """Generate a scoped network diagram from an existing run's graph/inventory artifacts."""
        from dataclasses import asdict

        from tools.azdisc.config import load_config_from_dict
        from tools.azdisc.drawio import generate_drawio
        from tools.azdisc.util import normalize_id
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")

        run_id = str(payload.get("run_id") or "").strip()
        target_mode = str(payload.get("target") or "").strip().lower()
        scope_value = str(payload.get("scope") or "").strip()
        include_neighbors = bool(payload.get("include_neighbors", True))

        if not run_id:
            raise HTTPException(status_code=400, detail="run_id is required")
        if target_mode not in {"tag", "resourcegroup", "resource"}:
            raise HTTPException(status_code=400, detail="target must be one of: tag, resourcegroup, resource")
        if not scope_value:
            raise HTTPException(status_code=400, detail="scope is required")

        runner = get_runner()
        job = runner.get_job(run_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        root = Path(job["output_dir"])
        graph_path = root / "graph.json"
        inventory_path = root / "inventory.json"
        if not graph_path.exists():
            raise HTTPException(status_code=404, detail="graph.json not found for this run")
        if not inventory_path.exists():
            raise HTTPException(status_code=404, detail="inventory.json not found for this run")

        try:
            graph = json.loads(graph_path.read_text(encoding="utf-8"))
            inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Failed to parse run artifacts: {exc}")

        if not isinstance(graph, dict) or not isinstance(inventory, list):
            raise HTTPException(status_code=400, detail="Invalid graph.json or inventory.json structure")

        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise HTTPException(status_code=400, detail="graph.json must include array fields: nodes and edges")

        selected_ids: set[str] = set()
        if target_mode == "resourcegroup":
            wanted = scope_value.lower()
            for row in inventory:
                if isinstance(row, dict) and str(row.get("resourceGroup") or "").strip().lower() == wanted:
                    rid = normalize_id(row.get("id") or "")
                    if rid:
                        selected_ids.add(rid)
        elif target_mode == "resource":
            selected_ids.add(normalize_id(scope_value))
        else:
            if "=" not in scope_value:
                raise HTTPException(status_code=400, detail="Tag scope must be in key=value format")
            wanted_key, wanted_value = scope_value.split("=", 1)
            wanted_key = wanted_key.strip().lower()
            wanted_value = wanted_value.strip().lower()
            for row in inventory:
                if not isinstance(row, dict):
                    continue
                tags = row.get("tags")
                if not isinstance(tags, dict):
                    continue
                for key, value in tags.items():
                    if str(key or "").strip().lower() == wanted_key and str(value or "").strip().lower() == wanted_value:
                        rid = normalize_id(row.get("id") or "")
                        if rid:
                            selected_ids.add(rid)
                        break

        if not selected_ids:
            raise HTTPException(status_code=404, detail="No resources matched the selected scope")

        node_id_to_original: dict[str, str] = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = normalize_id(node.get("id") or "")
            if nid:
                node_id_to_original[nid] = node.get("id")

        keep_norm_ids: set[str] = {nid for nid in selected_ids if nid in node_id_to_original}
        if include_neighbors:
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                src = normalize_id(edge.get("source") or "")
                tgt = normalize_id(edge.get("target") or "")
                if src in keep_norm_ids or tgt in keep_norm_ids:
                    if src in node_id_to_original:
                        keep_norm_ids.add(src)
                    if tgt in node_id_to_original:
                        keep_norm_ids.add(tgt)

        filtered_nodes = [
            node for node in nodes
            if isinstance(node, dict) and normalize_id(node.get("id") or "") in keep_norm_ids
        ]
        filtered_edges = [
            edge for edge in edges
            if isinstance(edge, dict)
            and normalize_id(edge.get("source") or "") in keep_norm_ids
            and normalize_id(edge.get("target") or "") in keep_norm_ids
        ]

        if not filtered_nodes:
            raise HTTPException(status_code=404, detail="No graph nodes found for the selected scope")

        slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in scope_value).strip("-")
        slug = slug[:64] if slug else target_mode
        suffix = uuid.uuid4().hex[:6]
        out_dir = root / "diagram-beta" / f"{target_mode}-{slug}-{suffix}"
        out_dir.mkdir(parents=True, exist_ok=True)

        (out_dir / "graph.json").write_text(
            json.dumps({"nodes": filtered_nodes, "edges": filtered_edges}, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (out_dir / "unresolved.json").write_text("[]\n", encoding="utf-8")

        cfg_data = asdict(job["config"])
        cfg_data["outputDir"] = str(out_dir)
        cfg_data["diagramFocus"] = {
            "preset": "full",
            "resourceTypes": [],
            "includeDependencies": True,
            "dependencyDepth": 1,
            "networkScope": "full",
            "diagramType": "network",
        }

        try:
            scoped_cfg = load_config_from_dict(cfg_data)
            generate_drawio(scoped_cfg)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Scoped diagram generation failed: {exc}")

        diagram_drawio = out_dir / "diagram.drawio"
        if not diagram_drawio.exists():
            raise HTTPException(status_code=500, detail="diagram.drawio was not produced")

        rel_drawio = diagram_drawio.relative_to(root).as_posix()
        rel_svg = (out_dir / "diagram.svg").relative_to(root).as_posix()
        rel_png = (out_dir / "diagram.png").relative_to(root).as_posix()

        return {
            "run_id": run_id,
            "target": target_mode,
            "scope": scope_value,
            "output_dir": out_dir.relative_to(root).as_posix(),
            "diagramPath": rel_drawio,
            "svgPath": rel_svg if (out_dir / "diagram.svg").exists() else None,
            "pngPath": rel_png if (out_dir / "diagram.png").exists() else None,
            "nodeCount": len(filtered_nodes),
            "edgeCount": len(filtered_edges),
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

    @app.get("/api/artifacts/preview/{run_id}/{file_path:path}", tags=["artifacts"])
    async def preview_artifact(run_id: str, file_path: str, limit: int = 50) -> dict:
        """Preview supported artifacts.

        Supported preview types:
        - JSON: sampled structural preview
        - .drawio/.xml: raw XML text snippet preview
        """
        from tools.azdisc_ui.services.json_preview import preview_json_artifact
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        runner = get_runner()
        job = runner.get_job(run_id)

        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        root = Path(job["output_dir"])
        target = root / file_path
        if not target.is_relative_to(root):
            raise HTTPException(status_code=403, detail="Access denied")
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
        suffix = target.suffix.lower()

        if suffix == ".json":
            try:
                preview = preview_json_artifact(target, sample_limit=max(1, min(limit, 200)))
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            return {
                "kind": "json",
                "path": str(target.relative_to(root)),
                "fileSize": target.stat().st_size,
                **preview,
            }

        if suffix in {".drawio", ".xml", ".mxlibrary"}:
            max_lines = max(20, min(limit * 4, 400))
            text = target.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            preview_lines = lines[:max_lines]
            truncated = len(lines) > len(preview_lines)
            preview_text = "\n".join(preview_lines)
            if truncated:
                preview_text += "\n... (truncated)"

            return {
                "kind": "xml",
                "path": str(target.relative_to(root)),
                "fileSize": target.stat().st_size,
                "lineCount": len(lines),
                "previewText": preview_text,
                "truncated": truncated,
            }

        raise HTTPException(
            status_code=400,
            detail="Preview is supported for .json, .drawio, .xml, and .mxlibrary artifacts",
        )

    @app.get("/api/inventory/explore/{run_id}", tags=["artifacts"])
    async def explore_inventory(
        run_id: str,
        artifact: str = "inventory",
        offset: int = 0,
        limit: int = 100,
        query: str = "",
        resource_type: str = "",
        resource_group: str = "",
        subscription: str = "",
    ) -> dict:
        """Explore inventory-like artifacts with pagination and simple filters."""
        from tools.azdisc_ui.services.inventory_explorer import query_inventory
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        runner = get_runner()
        job = runner.get_job(run_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        try:
            return query_inventory(
                job["output_dir"],
                artifact=artifact,
                offset=offset,
                limit=limit,
                query=query,
                resource_types=[resource_type] if resource_type else [],
                resource_groups=[resource_group] if resource_group else [],
                subscriptions=[subscription] if subscription else [],
            )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.get("/api/inventory/facets/{run_id}", tags=["artifacts"])
    async def inventory_facets(run_id: str, artifact: str = "inventory") -> dict:
        """Return distinct values for inventory filters."""
        from tools.azdisc_ui.services.inventory_explorer import get_inventory_facets
        from tools.azdisc_ui.services.pipeline_runner import get_runner

        runner = get_runner()
        job = runner.get_job(run_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        try:
            return get_inventory_facets(job["output_dir"], artifact=artifact)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    
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

    # ============================================================================
    # Deterministic Scenario Generation (Beta-Dumb-AI)
    # ============================================================================

    @app.post("/api/scenario/generate", tags=["scenario"])
    async def scenario_generate(payload: dict) -> dict:
        """Parse a controlled scenario prompt and return a deterministic graph payload.

        Accepts:
            text (str): the scenario description text.
            template (str, optional): builtin template name to use instead of raw text.

        Returns:
            graph payload (nodes, edges, title, scenario, layout_rules)
            plus a parsed_summary of counts.
        """
        from tools.azdisc.scenario_spec import (
            parse_scenario_spec,
            scenario_spec_to_graph,
            BUILTIN_TEMPLATES,
        )

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be a JSON object")

        template_name = str(payload.get("template", "")).strip()
        text = str(payload.get("text", "")).strip()

        if template_name:
            if template_name not in BUILTIN_TEMPLATES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown template '{template_name}'. Available: {sorted(BUILTIN_TEMPLATES)}",
                )
            text = BUILTIN_TEMPLATES[template_name]
        elif not text:
            raise HTTPException(
                status_code=400,
                detail="Must provide either 'text' or a valid 'template' name",
            )

        spec = parse_scenario_spec(text)
        graph = scenario_spec_to_graph(spec)

        return {
            "graph": graph,
            "parsed_summary": {
                "resources": len(spec.resources),
                "connections": len(spec.connections),
                "layout_rules": len(spec.layout_rules),
                "actor_nodes": sum(
                    1 for n in graph["nodes"] if n["type"] == "scenario/actor"
                ),
                "total_nodes": len(graph["nodes"]),
                "total_edges": len(graph["edges"]),
            },
            "available_templates": sorted(BUILTIN_TEMPLATES),
        }

    @app.get("/api/scenario/templates", tags=["scenario"])
    async def scenario_templates() -> dict:
        """List available builtin scenario templates."""
        from tools.azdisc.scenario_spec import BUILTIN_TEMPLATES

        return {
            "templates": [
                {"name": name, "text": text}
                for name, text in sorted(BUILTIN_TEMPLATES.items())
            ],
            "total": len(BUILTIN_TEMPLATES),
        }

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
