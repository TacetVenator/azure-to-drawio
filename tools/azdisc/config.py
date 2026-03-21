"""Configuration schema and loader."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

log = logging.getLogger(__name__)

VALID_LAYOUTS = {"SUB>REGION>RG>NET"}
VALID_DIAGRAM_MODES = {"MSFT", "L2R"}
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
    seedTags: Dict[str, str] = field(default_factory=dict)
    seedTagKeys: List[str] = field(default_factory=list)
    includeRbac: bool = False
    enableTelemetry: bool = False
    telemetryLookbackDays: int = 7
    layout: str = "SUB>REGION>RG>NET"
    diagramMode: str = "MSFT"
    spacing: str = "compact"
    expandScope: str = "related"
    inventoryGroupBy: str = "type"
    networkDetail: str = "full"
    edgeLabels: bool = False
    subnetColors: bool = False
    groupByTag: List[str] = field(default_factory=list)
    layoutMagic: bool = False

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
    required = {"app", "subscriptions", "outputDir"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")
    seed_rgs = data.get("seedResourceGroups", [])
    if not isinstance(seed_rgs, list) or any(not isinstance(v, str) or not v.strip() for v in seed_rgs):
        raise ValueError(f"seedResourceGroups must be a list of non-empty strings, got {seed_rgs!r}")
    seed_tags = data.get("seedTags", {})
    if not isinstance(seed_tags, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
        for k, v in seed_tags.items()
    ):
        raise ValueError(f"seedTags must be an object mapping non-empty strings to non-empty strings, got {seed_tags!r}")
    seed_tag_keys = data.get("seedTagKeys", [])
    if not isinstance(seed_tag_keys, list) or any(
        not isinstance(v, str) or not v.strip() for v in seed_tag_keys
    ):
        raise ValueError(f"seedTagKeys must be a list of non-empty strings, got {seed_tag_keys!r}")
    if not seed_rgs and not seed_tags and not seed_tag_keys:
        raise ValueError("Config must include at least one of seedResourceGroups, seedTags, or seedTagKeys")
    layout = data.get("layout", "SUB>REGION>RG>NET")
    if layout not in VALID_LAYOUTS:
        raise ValueError(f"Unsupported layout: {layout!r}. Valid: {sorted(VALID_LAYOUTS)}")
    diagram_mode = data.get("diagramMode", "MSFT")
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
    group_by_tag = data.get("groupByTag", [])
    if not isinstance(group_by_tag, list) or any(not isinstance(v, str) or not v.strip() for v in group_by_tag):
        raise ValueError(f"groupByTag must be a list of non-empty strings, got {group_by_tag!r}")
    layout_magic = data.get("layoutMagic", False)
    if not isinstance(layout_magic, bool):
        raise ValueError(f"layoutMagic must be a boolean, got {layout_magic!r}")
    enable_telemetry = data.get("enableTelemetry", False)
    lookback_days = data.get("telemetryLookbackDays", 7)
    if not isinstance(lookback_days, int) or lookback_days < 1:
        raise ValueError(f"telemetryLookbackDays must be a positive integer, got {lookback_days!r}")
    cfg = Config(
        app=data["app"],
        subscriptions=data["subscriptions"],
        seedResourceGroups=[v.strip() for v in seed_rgs],
        outputDir=data["outputDir"],
        seedTags={k.strip(): v.strip() for k, v in seed_tags.items()},
        seedTagKeys=[v.strip() for v in seed_tag_keys],
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
        groupByTag=[v.strip() for v in group_by_tag],
        layoutMagic=layout_magic,
    )
    log.info(
        "Loaded config for app=%s, subs=%d, seedRGs=%d, seedTags=%d, seedTagKeys=%d",
        cfg.app,
        len(cfg.subscriptions),
        len(cfg.seedResourceGroups),
        len(cfg.seedTags),
        len(cfg.seedTagKeys),
    )
    return cfg
