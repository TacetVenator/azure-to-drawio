"""Generate diagrams for every combination of layout × diagramMode × fixture.

This module exercises the offline pipeline (graph → drawio → docs) against
each test fixture with every valid (layout, diagramMode) pair.  No Azure
credentials are needed — it works entirely from the JSON fixtures shipped
in the test suite.

Output tree (default root: out/test-all/):
    <fixture_stem>/
        <layout>_<diagramMode>/
            graph.json
            diagram.drawio
            diagram.svg        (if drawio CLI available)
            diagram.png        (if drawio CLI available)
            icons_used.json
            catalog.md
            edges.md
            routing.md
"""
from __future__ import annotations

import logging
import shutil
from itertools import product
from pathlib import Path
from typing import List, Tuple

from .config import Config, VALID_LAYOUTS, VALID_DIAGRAM_MODES
from .graph import build_graph
from .drawio import generate_drawio
from .docs import generate_docs

log = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "tests" / "fixtures"


def _discover_fixtures() -> List[Path]:
    """Return all JSON fixture files sorted by name."""
    fixtures = sorted(FIXTURES_DIR.glob("*.json"))
    if not fixtures:
        raise FileNotFoundError(f"No fixture files found in {FIXTURES_DIR}")
    return fixtures


def _safe_layout_name(layout: str) -> str:
    """Convert layout string to a filesystem-safe folder name."""
    return layout.replace(">", "-")


def run_test_all(output_root: str = "out/test-all") -> None:
    """Generate diagrams for every combination and write to *output_root*.

    Iterates over:
        fixtures × layouts × diagramModes

    Each combination gets its own subfolder under *output_root*.
    """
    root = Path(output_root)
    fixtures = _discover_fixtures()
    layouts = sorted(VALID_LAYOUTS)
    modes = sorted(VALID_DIAGRAM_MODES)

    combos: List[Tuple[Path, str, str]] = [
        (fx, lay, dm)
        for fx, lay, dm in product(fixtures, layouts, modes)
    ]

    log.info(
        "test-all: %d fixtures × %d layouts × %d modes = %d combinations",
        len(fixtures), len(layouts), len(modes), len(combos),
    )

    succeeded = 0
    failed = 0

    for fixture, layout, diagram_mode in combos:
        label = f"{fixture.stem}/{_safe_layout_name(layout)}_{diagram_mode}"
        out_dir = root / fixture.stem / f"{_safe_layout_name(layout)}_{diagram_mode}"
        out_dir.mkdir(parents=True, exist_ok=True)

        # Seed the output directory with the fixture as inventory.json
        shutil.copy2(fixture, out_dir / "inventory.json")
        (out_dir / "unresolved.json").write_text("[]")

        cfg = Config(
            app=fixture.stem,
            subscriptions=["00000000-0000-0000-0000-000000000000"],
            seedResourceGroups=["fixture"],
            outputDir=str(out_dir),
            layout=layout,
            diagramMode=diagram_mode,
        )

        try:
            build_graph(cfg)
            generate_drawio(cfg)
            generate_docs(cfg)
            succeeded += 1
            log.info("  OK   %s", label)
        except Exception:
            failed += 1
            log.exception("  FAIL %s", label)

    log.info(
        "test-all complete: %d/%d succeeded, %d failed",
        succeeded, len(combos), failed,
    )
    if failed:
        raise SystemExit(f"test-all: {failed} combination(s) failed")
