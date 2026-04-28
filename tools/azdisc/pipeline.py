"""Shared pipeline stage definitions for CLI and Web UI execution."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .config import Config
from .discover import run_expand, run_policy, run_rbac, run_seed
from .docs import generate_docs
from .drawio import generate_drawio
from .graph import build_graph
from .insights import generate_vm_details_csv, run_advisor, run_quota
from .master_report import generate_master_report
from .migration_plan import generate_migration_plan
from .split import run_split
from .telemetry import run_telemetry_enrichment
from .vm_report import generate_vm_report_packs


@dataclass(frozen=True)
class PipelineStage:
    name: str
    action: Callable[[], None]


def build_pipeline_stages(
    config: Config,
    *,
    software_inventory_workspace: Optional[str] = None,
    software_inventory_days: int = 30,
) -> List[PipelineStage]:
    """Build the ordered stage list used by both CLI and UI runners."""
    stages: List[PipelineStage] = [
        PipelineStage("seed", lambda: run_seed(config)),
        PipelineStage(
            "expand",
            lambda: run_expand(
                config,
                software_inventory_workspace=software_inventory_workspace,
                software_inventory_days=software_inventory_days,
            ),
        ),
        PipelineStage("rbac", lambda: run_rbac(config)) if config.includeRbac else None,
        PipelineStage("policy", lambda: run_policy(config)) if config.includePolicy else None,
        PipelineStage("graph", lambda: build_graph(config)),
        PipelineStage("telemetry", lambda: run_telemetry_enrichment(config)) if config.enableTelemetry else None,
        PipelineStage("drawio", lambda: generate_drawio(config)),
        PipelineStage("advisor", lambda: run_advisor(config)) if config.includeAdvisor else None,
        PipelineStage("quota", lambda: run_quota(config)) if config.includeQuota else None,
        PipelineStage("vm-details", lambda: generate_vm_details_csv(config)) if config.includeVmDetails else None,
        PipelineStage("vm-report", lambda: generate_vm_report_packs(config)),
        PipelineStage("docs", lambda: generate_docs(config)),
        PipelineStage("split", lambda: run_split(config)) if config.applicationSplit.enabled else None,
        PipelineStage("migration-plan", lambda: generate_migration_plan(config)) if config.migrationPlan.enabled else None,
        PipelineStage("master-report", lambda: generate_master_report(config)),
    ]
    return [stage for stage in stages if stage is not None]