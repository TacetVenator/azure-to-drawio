"""Diagram generation for all layout × diagramMode combinations.

Two entry points:
  - run_test_all(): for CI / development — exercises all combinations against
    the bundled test fixtures, no Azure credentials needed.
  - run_render_all(cfg): for end-users — reads the already-built graph.json
    from a real app's outputDir and generates all layout × mode variants
    alongside the existing output.

Both share render_combinations(), the common core that writes one subfolder
per (layout, diagramMode) pair.

Output tree for test-all (default root: out/test-all/):
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

Output tree for render-all (inside the user's outputDir):
    variants/
        <layout>_<diagramMode>/
            graph.json
            diagram.drawio
            ...
"""
from __future__ import annotations

import json
import logging
import shutil
from itertools import product
from pathlib import Path
from typing import Dict, List, Tuple

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


def render_combinations(
    graph: Dict,
    app: str,
    subscriptions: List[str],
    seed_rgs: List[str],
    output_root: Path,
) -> Tuple[int, int]:
    """Generate drawio + docs for every layout × diagramMode under output_root.

    Each combination gets its own subfolder named <layout>_<mode>/ and
    receives a copy of graph.json so generate_drawio and generate_docs
    can find it.

    Returns (succeeded_count, failed_count).
    """
    succeeded = 0
    failed = 0

    for layout, diagram_mode in product(sorted(VALID_LAYOUTS), sorted(VALID_DIAGRAM_MODES)):
        label = f"{_safe_layout_name(layout)}_{diagram_mode}"
        combo_dir = output_root / label
        combo_dir.mkdir(parents=True, exist_ok=True)
        (combo_dir / "graph.json").write_text(json.dumps(graph))

        cfg = Config(
            app=app,
            subscriptions=subscriptions,
            seedResourceGroups=seed_rgs,
            outputDir=str(combo_dir),
            layout=layout,
            diagramMode=diagram_mode,
        )

        try:
            generate_drawio(cfg)
            generate_docs(cfg)
            succeeded += 1
            log.info("  OK   %s", label)
        except Exception:
            failed += 1
            log.exception("  FAIL %s", label)

    return succeeded, failed


def run_test_all(output_root: str = "out/test-all") -> None:
    """Generate diagrams for every fixture × layout × diagramMode combination.

    The graph is built once per fixture (not once per combo) for efficiency.
    Each combination gets its own subfolder under <output_root>/<fixture_stem>/.
    """
    root = Path(output_root)
    fixtures = _discover_fixtures()
    n_combos = len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)

    log.info(
        "test-all: %d fixtures × %d layouts × %d modes = %d combinations",
        len(fixtures), len(VALID_LAYOUTS), len(VALID_DIAGRAM_MODES), len(fixtures) * n_combos,
    )

    total_succeeded = 0
    total_failed = 0

    for fixture in fixtures:
        fixture_root = root / fixture.stem

        # Build graph once in a temporary subdirectory, then discard it
        build_dir = fixture_root / ".build"
        build_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture, build_dir / "inventory.json")
        (build_dir / "unresolved.json").write_text("[]")

        build_cfg = Config(
            app=fixture.stem,
            subscriptions=["00000000-0000-0000-0000-000000000000"],
            seedResourceGroups=["fixture"],
            outputDir=str(build_dir),
        )
        build_graph(build_cfg)
        graph = json.loads((build_dir / "graph.json").read_text())
        shutil.rmtree(build_dir)

        s, f = render_combinations(
            graph, fixture.stem,
            ["00000000-0000-0000-0000-000000000000"], ["fixture"],
            fixture_root,
        )
        total_succeeded += s
        total_failed += f

    log.info(
        "test-all complete: %d/%d succeeded, %d failed",
        total_succeeded, total_succeeded + total_failed, total_failed,
    )
    if total_failed:
        raise SystemExit(f"test-all: {total_failed} combination(s) failed")


def run_render_all(cfg: Config) -> None:
    """Generate all layout × diagramMode combinations from an existing graph.json.

    Reads graph.json from cfg.outputDir (produced by the 'graph' stage) and
    writes each combination into a variants/<layout>_<mode>/ subfolder
    alongside the existing output, leaving the user's primary output intact.

    Typical usage:
        python3 -m tools.azdisc run      app/myapp/config.json
        python3 -m tools.azdisc render-all app/myapp/config.json
    """
    graph_path = cfg.out("graph.json")
    if not graph_path.exists():
        raise FileNotFoundError(
            f"graph.json not found at {graph_path}. Run 'graph' (or 'run') first."
        )

    graph = json.loads(graph_path.read_text())
    variants_root = cfg.out("variants")
    n_combos = len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)

    log.info(
        "render-all: generating %d combinations into %s",
        n_combos, variants_root,
    )

    succeeded, failed = render_combinations(
        graph, cfg.app, cfg.subscriptions, cfg.seedResourceGroups, variants_root,
    )

    log.info(
        "render-all complete: %d/%d succeeded, %d failed",
        succeeded, succeeded + failed, failed,
    )
    if failed:
        raise SystemExit(f"render-all: {failed} combination(s) failed")
