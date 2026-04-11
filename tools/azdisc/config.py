"""Configuration schema and loader."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
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
VALID_MIGRATION_PLAN_AUDIENCES = {"mixed", "technical", "executive"}
VALID_MIGRATION_PLAN_APPLICATION_SCOPES = {"root", "split", "both"}
APPLICATION_SPLIT_DEFAULT_TAG_KEYS = ["Application", "App", "Workload", "Service"]


@dataclass
class DeepDiscoveryConfig:
    enabled: bool = False
    searchStrings: List[str] = field(default_factory=list)
    candidateFile: str = "related_candidates.json"
    promotedFile: str = "related_promoted.json"
    outputDirName: str = "deep-discovery"
    extendedOutputDirName: str = "extended"


@dataclass
class ApplicationSplitConfig:
    enabled: bool = False
    mode: str = "tag-value"
    tagKeys: List[str] = field(default_factory=list)
    values: List[str] = field(default_factory=list)
    includeSharedDependencies: bool = True
    outputLayout: str = "subdirs"


@dataclass
class MigrationPlanConfig:
    enabled: bool = False
    outputDir: str = ""
    audience: str = "mixed"
    applicationScope: str = "both"
    includeCopilotPrompts: bool = True


@dataclass
class Config:
    app: str
    subscriptions: List[str]
    seedResourceGroups: List[str]
    outputDir: str
    seedManagementGroups: List[str] = field(default_factory=list)
    seedResourceIds: List[str] = field(default_factory=list)
    seedTags: Dict[str, str] = field(default_factory=dict)
    seedTagKeys: List[str] = field(default_factory=list)
    seedEntireSubscriptions: bool = False
    includeRbac: bool = False
    resolvePrincipalNames: bool = False
    includePolicy: bool = False
    includeAdvisor: bool = False
    includeQuota: bool = False
    includeVmDetails: bool = False
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
    deepDiscovery: DeepDiscoveryConfig = field(default_factory=DeepDiscoveryConfig)
    applicationSplit: ApplicationSplitConfig = field(default_factory=ApplicationSplitConfig)
    migrationPlan: MigrationPlanConfig = field(default_factory=MigrationPlanConfig)

    def out(self, filename: str) -> Path:
        return Path(self.outputDir) / filename

    def ensure_output_dir(self) -> None:
        Path(self.outputDir).mkdir(parents=True, exist_ok=True)

    def deep_out(self, filename: str) -> Path:
        return Path(self.outputDir) / self.deepDiscovery.outputDirName / filename

    def ensure_deep_output_dir(self) -> Path:
        path = Path(self.outputDir) / self.deepDiscovery.outputDirName
        path.mkdir(parents=True, exist_ok=True)
        return path

    def extended_output_dir(self) -> Path:
        return Path(self.outputDir) / self.deepDiscovery.outputDirName / self.deepDiscovery.extendedOutputDirName

    def with_output_dir(self, output_dir: str) -> "Config":
        return replace(self, outputDir=output_dir)


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


def _validate_nonempty_string(name: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string, got {value!r}")
    return value.strip()


def _load_deep_discovery(data: object) -> DeepDiscoveryConfig:
    if data is None:
        return DeepDiscoveryConfig()
    if not isinstance(data, dict):
        raise ValueError(f"deepDiscovery must be an object, got {data!r}")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"deepDiscovery.enabled must be a boolean, got {enabled!r}")

    search_strings = _validate_string_list("deepDiscovery.searchStrings", data.get("searchStrings", []))
    if enabled and not search_strings:
        raise ValueError("deepDiscovery.searchStrings must include at least one value when deepDiscovery.enabled is true")

    return DeepDiscoveryConfig(
        enabled=enabled,
        searchStrings=search_strings,
        candidateFile=_validate_nonempty_string("deepDiscovery.candidateFile", data.get("candidateFile", "related_candidates.json")),
        promotedFile=_validate_nonempty_string("deepDiscovery.promotedFile", data.get("promotedFile", "related_promoted.json")),
        outputDirName=_validate_nonempty_string("deepDiscovery.outputDirName", data.get("outputDirName", "deep-discovery")),
        extendedOutputDirName=_validate_nonempty_string("deepDiscovery.extendedOutputDirName", data.get("extendedOutputDirName", "extended")),
    )


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

    tag_keys = _validate_string_list("applicationSplit.tagKeys", data.get("tagKeys", APPLICATION_SPLIT_DEFAULT_TAG_KEYS))
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


def _load_migration_plan(data: object) -> MigrationPlanConfig:
    if data is None:
        return MigrationPlanConfig()
    if not isinstance(data, dict):
        raise ValueError(f"migrationPlan must be an object, got {data!r}")

    enabled = data.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ValueError(f"migrationPlan.enabled must be a boolean, got {enabled!r}")

    output_dir = data.get("outputDir", "")
    if not isinstance(output_dir, str):
        raise ValueError(f"migrationPlan.outputDir must be a string, got {output_dir!r}")

    audience = data.get("audience", "mixed")
    if audience not in VALID_MIGRATION_PLAN_AUDIENCES:
        raise ValueError(
            f"Unsupported migrationPlan.audience: {audience!r}. Valid: {sorted(VALID_MIGRATION_PLAN_AUDIENCES)}"
        )

    application_scope = data.get("applicationScope", "both")
    if application_scope not in VALID_MIGRATION_PLAN_APPLICATION_SCOPES:
        raise ValueError(
            "Unsupported migrationPlan.applicationScope: "
            f"{application_scope!r}. Valid: {sorted(VALID_MIGRATION_PLAN_APPLICATION_SCOPES)}"
        )

    include_copilot_prompts = data.get("includeCopilotPrompts", True)
    if not isinstance(include_copilot_prompts, bool):
        raise ValueError(
            "migrationPlan.includeCopilotPrompts must be a boolean, "
            f"got {include_copilot_prompts!r}"
        )

    return MigrationPlanConfig(
        enabled=enabled,
        outputDir=output_dir.strip(),
        audience=audience,
        applicationScope=application_scope,
        includeCopilotPrompts=include_copilot_prompts,
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
    seed_resource_ids = _validate_string_list("seedResourceIds", data.get("seedResourceIds", []))
    seed_tags = _validate_seed_tags(data.get("seedTags", {}))
    seed_tag_keys = _validate_string_list("seedTagKeys", data.get("seedTagKeys", []))
    seed_management_groups = _validate_string_list("seedManagementGroups", data.get("seedManagementGroups", []))
    seed_entire_subscriptions = data.get("seedEntireSubscriptions", False)
    if not isinstance(seed_entire_subscriptions, bool):
        raise ValueError(
            f"seedEntireSubscriptions must be a boolean, got {seed_entire_subscriptions!r}"
        )
    if not seed_rgs and not seed_resource_ids and not seed_tags and not seed_tag_keys and not seed_entire_subscriptions and not seed_management_groups:
        raise ValueError(
            "Config must include at least one of seedResourceGroups, seedResourceIds, seedTags, seedTagKeys, or seedEntireSubscriptions (or seedManagementGroups)"
        )

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

    resolve_principal_names = data.get("resolvePrincipalNames", False)
    if not isinstance(resolve_principal_names, bool):
        raise ValueError(f"resolvePrincipalNames must be a boolean, got {resolve_principal_names!r}")

    include_policy = data.get("includePolicy", False)
    if not isinstance(include_policy, bool):
        raise ValueError(f"includePolicy must be a boolean, got {include_policy!r}")

    include_advisor = data.get("includeAdvisor", False)
    if not isinstance(include_advisor, bool):
        raise ValueError(f"includeAdvisor must be a boolean, got {include_advisor!r}")

    include_quota = data.get("includeQuota", False)
    if not isinstance(include_quota, bool):
        raise ValueError(f"includeQuota must be a boolean, got {include_quota!r}")

    include_vm_details = data.get("includeVmDetails", False)
    if not isinstance(include_vm_details, bool):
        raise ValueError(f"includeVmDetails must be a boolean, got {include_vm_details!r}")

    lookback_days = data.get("telemetryLookbackDays", 7)
    if not isinstance(lookback_days, int) or lookback_days < 1:
        raise ValueError(f"telemetryLookbackDays must be a positive integer, got {lookback_days!r}")

    deep_discovery = _load_deep_discovery(data.get("deepDiscovery"))
    application_split = _load_application_split(data.get("applicationSplit"))
    migration_plan = _load_migration_plan(data.get("migrationPlan"))

    cfg = Config(
        app=data["app"],
        subscriptions=data["subscriptions"],
        seedManagementGroups=seed_management_groups,
        seedResourceGroups=seed_rgs,
        outputDir=data["outputDir"],
        seedResourceIds=seed_resource_ids,
        seedTags=seed_tags,
        seedTagKeys=seed_tag_keys,
        seedEntireSubscriptions=seed_entire_subscriptions,
        includeRbac=include_rbac,
        resolvePrincipalNames=resolve_principal_names,
        includePolicy=include_policy,
        includeAdvisor=include_advisor,
        includeQuota=include_quota,
        includeVmDetails=include_vm_details,
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
        deepDiscovery=deep_discovery,
        applicationSplit=application_split,
        migrationPlan=migration_plan,
    )
    log.info(
        "Loaded config for app=%s, subs=%d, seedMGs=%d, seedRGs=%d, seedResourceIds=%d, seedTags=%d, seedTagKeys=%d, seedAllSubs=%s, includeRbac=%s, resolvePrincipalNames=%s, includePolicy=%s, includeAdvisor=%s, includeQuota=%s, includeVmDetails=%s, deepDiscovery=%s, appSplit=%s, migrationPlan=%s",
        cfg.app,
        len(cfg.subscriptions),
        len(cfg.seedManagementGroups),
        len(cfg.seedResourceGroups),
        len(cfg.seedResourceIds),
        len(cfg.seedTags),
        len(cfg.seedTagKeys),
        cfg.seedEntireSubscriptions,
        cfg.includeRbac,
        cfg.resolvePrincipalNames,
        cfg.includePolicy,
        cfg.includeAdvisor,
        cfg.includeQuota,
        cfg.includeVmDetails,
        cfg.deepDiscovery.enabled,
        cfg.applicationSplit.enabled,
        cfg.migrationPlan.enabled,
    )
    return cfg
