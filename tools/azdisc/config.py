"""Configuration schema and loader."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

VALID_LAYOUTS = {"REGION>RG>TYPE", "VNET>SUBNET", "SUB>REGION>RG>NET", "HUB>SPOKE"}
VALID_DIAGRAM_MODES = {"BANDS", "MSFT", "L2R"}
VALID_SPACINGS = {"compact", "spacious"}
VALID_EXPAND_SCOPES = {"related", "all"}
VALID_INVENTORY_GROUP_BYS = {"type", "rg"}
VALID_NETWORK_DETAILS = {"compact", "full"}


@dataclass
class Config:
    app: str
    subscriptions: List[str]
    seedResourceGroups: List[str]
    outputDir: str
    includeRbac: bool = False
    enableTelemetry: bool = False
    telemetryLookbackDays: int = 7
    layout: str = "REGION>RG>TYPE"
    diagramMode: str = "BANDS"
    spacing: str = "compact"
    expandScope: str = "related"
    inventoryGroupBy: str = "type"
    networkDetail: str = "full"
    edgeLabels: bool = False
    subnetColors: bool = False

    def out(self, filename: str) -> Path:
        return Path(self.outputDir) / filename

    def ensure_output_dir(self) -> None:
        Path(self.outputDir).mkdir(parents=True, exist_ok=True)


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with p.open() as f:
        data = json.load(f)
    required = {"app", "subscriptions", "seedResourceGroups", "outputDir"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")
    layout = data.get("layout", "REGION>RG>TYPE")
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"Unsupported layout: {layout!r}. Valid: {sorted(VALID_LAYOUTS)}")
    diagram_mode = data.get("diagramMode", "BANDS")
    if diagram_mode not in VALID_DIAGRAM_MODES:
        raise ValueError(f"Unsupported diagramMode: {diagram_mode!r}. Valid: {sorted(VALID_DIAGRAM_MODES)}")
    spacing = data.get("spacing", "compact")
    if spacing not in VALID_SPACINGS:
        raise ValueError(f"Unsupported spacing: {spacing!r}. Valid: {VALID_SPACINGS}")
    expand_scope = data.get("expandScope", "related")
    if expand_scope not in VALID_EXPAND_SCOPES:
        raise ValueError(f"Unsupported expandScope: {expand_scope!r}. Valid: {VALID_EXPAND_SCOPES}")
    inventory_group_by = data.get("inventoryGroupBy", "type")
    if inventory_group_by not in VALID_INVENTORY_GROUP_BYS:
        raise ValueError(f"Unsupported inventoryGroupBy: {inventory_group_by!r}. Valid: {VALID_INVENTORY_GROUP_BYS}")
    network_detail = data.get("networkDetail", "full")
    if network_detail not in VALID_NETWORK_DETAILS:
        raise ValueError(f"Unsupported networkDetail: {network_detail!r}. Valid: {VALID_NETWORK_DETAILS}")
    enable_telemetry = data.get("enableTelemetry", False)
    lookback_days = data.get("telemetryLookbackDays", 7)
    if not isinstance(lookback_days, int) or lookback_days < 1:
        raise ValueError(f"telemetryLookbackDays must be a positive integer, got {lookback_days!r}")
    cfg = Config(
        app=data["app"],
        subscriptions=data["subscriptions"],
        seedResourceGroups=data["seedResourceGroups"],
        outputDir=data["outputDir"],
        includeRbac=data.get("includeRbac", False),
        enableTelemetry=enable_telemetry,
        telemetryLookbackDays=lookback_days,
        layout=layout,
        diagramMode=diagram_mode,
        spacing=spacing,
        expandScope=expand_scope,
        inventoryGroupBy=inventory_group_by,
        networkDetail=network_detail,
        edgeLabels=data.get("edgeLabels", False),
        subnetColors=data.get("subnetColors", False),
    )
    log.info("Loaded config for app=%s, subs=%d, seedRGs=%d", cfg.app, len(cfg.subscriptions), len(cfg.seedResourceGroups))
    return cfg
