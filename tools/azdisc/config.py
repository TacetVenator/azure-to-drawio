"""Configuration schema and loader."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

log = logging.getLogger(__name__)

VALID_LAYOUTS = {"REGION>RG>TYPE"}


@dataclass
class Config:
    app: str
    subscriptions: List[str]
    seedResourceGroups: List[str]
    outputDir: str
    includeRbac: bool = False
    layout: str = "REGION>RG>TYPE"

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
        raise ValueError(f"Unsupported layout: {layout!r}. Valid: {VALID_LAYOUTS}")
    cfg = Config(
        app=data["app"],
        subscriptions=data["subscriptions"],
        seedResourceGroups=data["seedResourceGroups"],
        outputDir=data["outputDir"],
        includeRbac=data.get("includeRbac", False),
        layout=layout,
    )
    log.info("Loaded config for app=%s, subs=%d, seedRGs=%d", cfg.app, len(cfg.subscriptions), len(cfg.seedResourceGroups))
    return cfg
