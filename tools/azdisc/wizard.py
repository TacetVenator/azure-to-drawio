"""Interactive wizard for discovery, visualization, and migration planning."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from .config import load_config
from .discover import run_expand, run_policy, run_rbac, run_seed
from .docs import generate_docs
from .drawio import generate_drawio
from .graph import build_graph
from .insights import generate_vm_details_csv, run_advisor, run_quota
from .master_report import generate_master_report
from .migration_plan import generate_migration_plan
from .split import build_split_preview, run_split
from .telemetry import run_telemetry_enrichment
from .test_all import run_render_all, run_report_all

PromptFn = Callable[[str], str]
EchoFn = Callable[[str], None]
ExecuteFn = Callable[[str, str], None]


def _prompt_text(prompt: str, input_fn: PromptFn, *, default: str = "", allow_empty: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        raw = input_fn(f"{prompt}{suffix}: ").strip()
        if raw:
            return raw
        if default:
            return default
        if allow_empty:
            return ""


def _prompt_yes_no(prompt: str, input_fn: PromptFn, *, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input_fn(f"{prompt} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False


def _prompt_choice(prompt: str, choices: Iterable[Tuple[str, str]], input_fn: PromptFn, *, default: str) -> str:
    choice_map = {key: label for key, label in choices}
    rendered = ", ".join(f"{key}={label}" for key, label in choice_map.items())
    while True:
        raw = input_fn(f"{prompt} ({rendered}) [{default}]: ").strip().lower()
        if not raw:
            return default
        if raw in choice_map:
            return raw


def _split_csv(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _split_tags(value: str) -> Dict[str, str]:
    tags: Dict[str, str] = {}
    for item in _split_csv(value):
        if "=" not in item:
            raise ValueError(f"Tag filters must use key=value form, got {item!r}")
        key, raw_value = item.split("=", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if not key or not raw_value:
            raise ValueError(f"Tag filters must use non-empty key=value form, got {item!r}")
        tags[key] = raw_value
    return tags


def _wizard_config_data(config_path: Path, input_fn: PromptFn, echo: EchoFn) -> Tuple[Dict[str, object], List[str], Dict[str, object]]:
    echo("Azure Discovery Wizard")
    app = _prompt_text("Application or engagement name", input_fn, default=config_path.stem.replace("_", "-") or "azdisc")
    subscriptions = _split_csv(_prompt_text("Subscriptions (comma-separated)", input_fn))
    output_dir = _prompt_text("Output directory", input_fn, default=str(config_path.parent / "out"))

    intent = _prompt_choice(
        "Primary intent",
        [
            ("d", "diagram current state"),
            ("a", "application-sliced diagrams"),
            ("m", "migration planning pack"),
            ("f", "full discovery + migration"),
        ],
        input_fn,
        default="f",
    )

    scope = _prompt_choice(
        "Discovery scope",
        [
            ("r", "specific resource groups"),
            ("t", "exact tag filters"),
            ("k", "tag-key presence"),
            ("m", "management groups"),
            ("s", "all listed subscriptions"),
        ],
        input_fn,
        default="r",
    )

    seed_rgs: List[str] = []
    seed_tags: Dict[str, str] = {}
    seed_tag_keys: List[str] = []
    seed_management_groups: List[str] = []
    seed_all_subs = False

    if scope == "r":
        seed_rgs = _split_csv(_prompt_text("Resource groups (comma-separated)", input_fn))
    elif scope == "t":
        seed_tags = _split_tags(_prompt_text("Tag filters key=value (comma-separated)", input_fn))
    elif scope == "k":
        seed_tag_keys = _split_csv(_prompt_text("Tag keys to require (comma-separated)", input_fn))
    elif scope == "m":
        seed_management_groups = _split_csv(_prompt_text("Management groups (comma-separated)", input_fn))
    else:
        seed_all_subs = True

    include_rbac = _prompt_yes_no("Collect RBAC assignments", input_fn, default=intent in {"m", "f"})
    include_policy = _prompt_yes_no("Collect Azure Policy state", input_fn, default=intent in {"m", "f"})
    enable_telemetry = _prompt_yes_no("Enable telemetry enrichment", input_fn, default=intent in {"m", "f"})
    include_advisor = _prompt_yes_no("Collect Azure Advisor recommendations", input_fn, default=intent in {"m", "f"})
    include_quota = _prompt_yes_no("Collect regional quota snapshots", input_fn, default=intent in {"m", "f"})
    include_vm_details = _prompt_yes_no("Generate VM details CSV", input_fn, default=intent in {"m", "f"})
    telemetry_days = 7
    if enable_telemetry:
        telemetry_days = int(_prompt_text("Telemetry lookback days", input_fn, default="7"))

    enable_split = intent in {"a", "f"} or _prompt_yes_no("Generate per-application slices after discovery", input_fn, default=False)
    application_split = {
        "enabled": enable_split,
        "tagKeys": ["Application", "App", "Workload", "Service"],
        "values": ["*"],
        "includeSharedDependencies": True,
        "outputLayout": "subdirs",
    }
    if enable_split:
        tag_keys_raw = _prompt_text(
            "Application split tag keys (comma-separated)",
            input_fn,
            default="Application,App,Workload,Service",
        )
        values_mode = _prompt_choice(
            "Application values",
            [("a", "auto-discover from extracted data"), ("e", "explicit values")],
            input_fn,
            default="a",
        )
        application_split["tagKeys"] = _split_csv(tag_keys_raw)
        if values_mode == "e":
            application_split["values"] = _split_csv(_prompt_text("Explicit application values", input_fn))
        application_split["includeSharedDependencies"] = _prompt_yes_no(
            "Include shared dependencies in each application slice",
            input_fn,
            default=True,
        )

    enable_migration = intent in {"m", "f"} or _prompt_yes_no("Generate migration planning packs", input_fn, default=False)
    migration_plan = {
        "enabled": enable_migration,
        "audience": "mixed",
        "applicationScope": "both" if enable_split else "root",
        "includeCopilotPrompts": True,
    }
    local_analysis = {
        "enabled": False,
        "provider": "ollama",
        "model": "",
        "intents": ["*"],
        "packScope": "both" if enable_split else "root",
    }
    if enable_migration:
        migration_plan["audience"] = {
            "m": "mixed",
            "t": "technical",
            "e": "executive",
        }[_prompt_choice("Migration pack audience", [("m", "mixed"), ("t", "technical"), ("e", "executive")], input_fn, default="m")]
        if enable_split:
            migration_plan["applicationScope"] = {
                "b": "both",
                "r": "root",
                "s": "split",
            }[_prompt_choice("Migration pack scope", [("b", "root and split packs"), ("r", "root only"), ("s", "split only")], input_fn, default="b")]
        migration_plan["includeCopilotPrompts"] = _prompt_yes_no("Include Copilot prompts", input_fn, default=True)
        if _prompt_yes_no("Run consultant-style local analysis with Ollama", input_fn, default=False):
            local_analysis["enabled"] = True
            local_analysis["model"] = _prompt_text("Ollama model name", input_fn, default="gemma3:latest")

    generate_variant_report = _prompt_yes_no("Generate all diagram/report variants", input_fn, default=False)
    generate_master = _prompt_yes_no("Generate the master architecture report", input_fn, default=True)
    execute_now = _prompt_yes_no("Run the selected workflow now", input_fn, default=False)

    config_data: Dict[str, object] = {
        "app": app,
        "subscriptions": subscriptions,
        "outputDir": output_dir,
        "includeRbac": include_rbac,
        "includePolicy": include_policy,
        "includeAdvisor": include_advisor,
        "includeQuota": include_quota,
        "includeVmDetails": include_vm_details,
        "enableTelemetry": enable_telemetry,
        "telemetryLookbackDays": telemetry_days,
        "layout": "SUB>REGION>RG>NET",
        "diagramMode": "MSFT",
        "spacing": "compact",
        "expandScope": "related",
        "inventoryGroupBy": "type",
        "networkDetail": "full",
        "edgeLabels": False,
        "subnetColors": False,
        "groupByTag": application_split["tagKeys"][:1] if enable_split else [],
        "layoutMagic": False,
        "applicationSplit": application_split,
        "migrationPlan": migration_plan,
        "localAnalysis": local_analysis,
    }
    if seed_rgs:
        config_data["seedResourceGroups"] = seed_rgs
    if seed_tags:
        config_data["seedTags"] = seed_tags
    if seed_tag_keys:
        config_data["seedTagKeys"] = seed_tag_keys
    if seed_management_groups:
        config_data["seedManagementGroups"] = seed_management_groups
    if seed_all_subs:
        config_data["seedEntireSubscriptions"] = True

    actions = ["run"]
    if generate_variant_report:
        actions.append("report-all")
    if generate_master:
        actions.append("master-report")
    metadata = {
        "intent": intent,
        "executeNow": execute_now,
        "variantReport": generate_variant_report,
        "masterReport": generate_master,
    }
    return config_data, actions, metadata


def _command_lines(config_path: Path, actions: List[str]) -> List[str]:
    return [f"python3 -m tools.azdisc {action} {config_path}" for action in actions]


def _prompt_pack(config_data: Dict[str, object], actions: List[str]) -> List[str]:
    outputs: List[str] = [
        "diagram.drawio",
        "catalog.md",
        "edges.md",
        "routing.md",
        "migration.md",
    ]
    if config_data.get("includeRbac"):
        outputs.append("rbac.json")
    if config_data.get("includePolicy"):
        outputs.append("policy.json")
    if config_data.get("applicationSplit", {}).get("enabled"):
        outputs.append("applications/<slug>/...")
        outputs.append("applications.md")
    if config_data.get("migrationPlan", {}).get("enabled"):
        outputs.append("migration-plan/")
    if config_data.get("localAnalysis", {}).get("enabled"):
        outputs.append("local-analysis/")

    if config_data.get("seedEntireSubscriptions"):
        seed_scope = "listed subscriptions"
    elif config_data.get("seedManagementGroups"):
        seed_scope = "management groups: " + ", ".join(config_data.get("seedManagementGroups", []))
    else:
        seed_scope = "configured RG/tag seed scope"
    prompts = [
        "Use the generated config to explain the current Azure deployment, separating known facts, inferred dependencies, and blind spots.",
        "Review the generated migration-plan outputs and identify missing assumptions, hidden dependencies, governance gaps, and rollback risks.",
        f"Using the discovery artifacts for {config_data['app']}, propose a target landing-zone placement, migration waves, and decisions still required from app, platform, and security stakeholders.",
    ]
    lines = [
        f"# Wizard Instructions — {config_data['app']}",
        "",
        "## Summary",
        f"- Seed scope: {seed_scope}",
        f"- Primary outputs: {', '.join(outputs)}",
        f"- Recommended actions: {', '.join(actions)}",
        "",
        "## Commands",
    ]
    lines.extend(f"- `{command}`" for command in _command_lines(Path('<config.json>'), actions))
    lines += [
        "",
        "## Expected Outcomes",
        "- Current-state discovery and diagrams for the selected scope.",
        "- Migration-oriented documentation with dependencies, gaps, and governance evidence.",
    ]
    if config_data.get("applicationSplit", {}).get("enabled"):
        lines.append("- Per-application inventory, diagrams, and reports based on the selected common tags.")
    if config_data.get("migrationPlan", {}).get("enabled"):
        lines.append("- Migration planning templates, questionnaires, decision trees, wave plans, and Copilot prompts.")
    if config_data.get("localAnalysis", {}).get("enabled"):
        lines.append("- Consultant-style local analysis reports generated through Ollama with indexed evidence packs.")
    lines += [
        "",
        "## Copilot Prompts",
    ]
    lines.extend(f"- {prompt}" for prompt in prompts)
    return lines


def _write_instructions(config_path: Path, config_data: Dict[str, object], actions: List[str]) -> Path:
    instructions_path = config_path.with_name(f"{config_path.stem}_wizard_instructions.md")
    lines = _prompt_pack(config_data, actions)
    rendered = "\n".join(lines).replace("<config.json>", str(config_path)) + "\n"
    instructions_path.write_text(rendered)
    return instructions_path


def _default_execute(action: str, config_path: str) -> None:
    cfg = load_config(config_path)
    if action == "run":
        run_seed(cfg)
        run_expand(cfg)
        run_rbac(cfg)
        run_policy(cfg)
        build_graph(cfg)
        if cfg.enableTelemetry:
            run_telemetry_enrichment(cfg)
        generate_drawio(cfg)
        if cfg.includeAdvisor:
            run_advisor(cfg)
        if cfg.includeQuota:
            run_quota(cfg)
        if cfg.includeVmDetails:
            generate_vm_details_csv(cfg)
        generate_docs(cfg)
        if cfg.applicationSplit.enabled:
            run_split(cfg)
        if cfg.migrationPlan.enabled:
            generate_migration_plan(cfg)
        generate_master_report(cfg)
        return
    if action == "report-all":
        run_report_all(cfg)
        return
    if action == "render-all":
        run_render_all(cfg)
        return
    if action == "master-report":
        generate_master_report(cfg)
        return
    if action == "split-preview":
        print(build_split_preview(cfg), end="")
        return
    if action == "migration-plan":
        generate_migration_plan(cfg)
        return
    raise ValueError(f"Unsupported wizard action: {action}")


def run_wizard(
    config_path: str,
    *,
    input_fn: PromptFn = input,
    echo: EchoFn = print,
    execute_fn: ExecuteFn = _default_execute,
) -> Dict[str, object]:
    path = Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not _prompt_yes_no(f"Overwrite existing config at {path}", input_fn, default=False):
        raise RuntimeError(f"Wizard aborted because {path} already exists.")

    try:
        config_data, actions, metadata = _wizard_config_data(path, input_fn, echo)
    except EOFError as exc:
        raise RuntimeError("Wizard input was interrupted before configuration completed.") from exc

    path.write_text(json.dumps(config_data, indent=2) + "\n")
    instructions_path = _write_instructions(path, config_data, actions)

    echo(f"Wrote config to {path}")
    echo(f"Wrote instructions to {instructions_path}")
    for command in _command_lines(path, actions):
        echo(command)

    if metadata["executeNow"]:
        for action in actions:
            echo(f"Running {action}...")
            execute_fn(action, str(path))

    return {
        "configPath": str(path),
        "instructionsPath": str(instructions_path),
        "actions": actions,
        "config": config_data,
        "executed": bool(metadata["executeNow"]),
    }
