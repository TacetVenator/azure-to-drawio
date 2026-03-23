"""Configuration schema and loader."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

from .util import load_json_file

log = logging.getLogger(__name__)

VALID_LAYOUTS = {"SUB>REGION>RG>NET"}
VALID_DIAGRAM_MODES = {"MSFT", "L2R"}
VALID_SPACINGS = {"compact", "spacious"}
VALID_EXPAND_SCOPES = {"related", "all"}
VALID_INVENTORY_GROUP_BYS = {"type", "rg"}
VALID_NETWORK_DETAILS = {"compact", "full"}
VALID_APPLICATION_SPLIT_MODES = {"tag-value"}
VALID_APPLICATION_SPLIT_OUTPUT_LAYOUTS = {"subdirs"}


@dataclass
class ApplicationSplitConfig:
    enabled: bool = False
    mode: str = "tag-value"
    tagKeys: List[str] = field(default_factory=list)
    values: List[str] = field(default_factory=list)
    includeSharedDependencies: bool = True
    outputLayout: str = "subdirs"


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
    applicationSplit: ApplicationSplitConfig = field(default_factory=ApplicationSplitConfig)

    def out(self, filename: str) -> Path:
        return Path(self.outputDir) / filename

    def ensure_output_dir(self) -> None:
        Path(self.outputDir).mkdir(parents=True, exist_ok=True)


def _validate_string_list(name: str, value: object) -> List[str]:
    if not isinstance(value, list) or any(not isinstance(v, str) or not v.strip() for v in value):
        raise ValueError(f"{name} must be a list of non-empty strings, got {value!r}")
    return [v.strip() for v in value]


def _validate_seed_tags(seed_tags: object) -> Dict[str, str]:
    if not isinstance(seed_tags, dict) or any(
        not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
        for k, v in seed_tags.items()
    ):
        raise ValueError(f"seedTags must be an object mapping non-empty strings to non-empty strings, got {seed_tags!r}")
    return {k.strip(): v.strip() for k, v in seed_tags.items()}


def _load_application_split(data: object) -> ApplicationSplitConfig:
    if data is None:
        return ApplicationSplitConfig()
    if not isinstance(data, dict):
        raise ValueError(f"applicationSplit must be an object, got {data!r}")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"applicationSplit.enabled must be a boolean, got {enabled!r}")

    mode = data.get("mode", "tag-value")
    if mode not in VALID_APPLICATION_SPLIT_MODES:
        raise ValueError(
            f"Unsupported applicationSplit.mode: {mode!r}. Valid: {sorted(VALID_APPLICATION_SPLIT_MODES)}"
        )

    tag_keys = _validate_string_list("applicationSplit.tagKeys", data.get("tagKeys", ["Application"]))
    values = _validate_string_list("applicationSplit.values", data.get("values", ["*"]))

    include_shared = data.get("includeSharedDependencies", True)
    if not isinstance(include_shared, bool):
        raise ValueError(
            "applicationSplit.includeSharedDependencies must be a boolean, "
            f"got {include_shared!r}"
        )

    output_layout = data.get("outputLayout", "subdirs")
    if output_layout not in VALID_APPLICATION_SPLIT_OUTPUT_LAYOUTS:
        raise ValueError(
            "Unsupported applicationSplit.outputLayout: "
            f"{output_layout!r}. Valid: {sorted(VALID_APPLICATION_SPLIT_OUTPUT_LAYOUTS)}"
        )

    return ApplicationSplitConfig(
        enabled=enabled,
        mode=mode,
        tagKeys=tag_keys,
        values=values,
        includeSharedDependencies=include_shared,
        outputLayout=output_layout,
    )


def load_config(path: str) -> Config:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    data = load_json_file(
        p,
        context="Config file",
        expected_type=dict,
        advice="Fix the config JSON and rerun the command.",
    )

    required = {"app", "subscriptions", "outputDir"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Config missing required keys: {missing}")

    seed_rgs = _validate_string_list("seedResourceGroups", data.get("seedResourceGroups", []))
    seed_tags = _validate_seed_tags(data.get("seedTags", {}))
    seed_tag_keys = _validate_string_list("seedTagKeys", data.get("seedTagKeys", []))
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
        raise ValueError(
            f"Unsupported inventoryGroupBy: {inventory_group_by!r}. Valid: {VALID_INVENTORY_GROUP_BYS}"
        )

    network_detail = data.get("networkDetail", "full")
    if network_detail not in VALID_NETWORK_DETAILS:
        raise ValueError(f"Unsupported networkDetail: {network_detail!r}. Valid: {VALID_NETWORK_DETAILS}")

    group_by_tag = _validate_string_list("groupByTag", data.get("groupByTag", []))

    layout_magic = data.get("layoutMagic", False)
    if not isinstance(layout_magic, bool):
        raise ValueError(f"layoutMagic must be a boolean, got {layout_magic!r}")

    enable_telemetry = data.get("enableTelemetry", False)
    if not isinstance(enable_telemetry, bool):
        raise ValueError(f"enableTelemetry must be a boolean, got {enable_telemetry!r}")

    include_rbac = data.get("includeRbac", False)
    if not isinstance(include_rbac, bool):
        raise ValueError(f"includeRbac must be a boolean, got {include_rbac!r}")

    lookback_days = data.get("telemetryLookbackDays", 7)
    if not isinstance(lookback_days, int) or lookback_days < 1:
        raise ValueError(f"telemetryLookbackDays must be a positive integer, got {lookback_days!r}")

    application_split = _load_application_split(data.get("applicationSplit"))

    cfg = Config(
        app=data["app"],
        subscriptions=data["subscriptions"],
        seedResourceGroups=seed_rgs,
        outputDir=data["outputDir"],
        seedTags=seed_tags,
        seedTagKeys=seed_tag_keys,
        includeRbac=include_rbac,
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
        groupByTag=group_by_tag,
        layoutMagic=layout_magic,
        applicationSplit=application_split,
    )
    log.info(
        "Loaded config for app=%s, subs=%d, seedRGs=%d, seedTags=%d, seedTagKeys=%d, appSplit=%s",
        cfg.app,
        len(cfg.subscriptions),
        len(cfg.seedResourceGroups),
        len(cfg.seedTags),
        len(cfg.seedTagKeys),
        cfg.applicationSplit.enabled,
    )
    return cfg
