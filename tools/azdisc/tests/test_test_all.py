"""Tests for the test-all combination generator and render-all."""
from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config, VALID_LAYOUTS, VALID_DIAGRAM_MODES
from tools.azdisc.graph import build_graph
from tools.azdisc.tests.test_integration import assert_drawio_references_resolve
from tools.azdisc.test_all import (
    run_test_all,
    run_render_all,
    render_combinations,
    _discover_fixtures,
    _safe_layout_name,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _make_graph(tmp_path: Path) -> dict:
    """Build a graph from the small fixture and return it as a dict."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    fixture = FIXTURES / "inventory_small.json"
    shutil.copy2(fixture, tmp_path / "inventory.json")
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="test",
        subscriptions=["00000000-0000-0000-0000-000000000000"],
        seedResourceGroups=["rg"],
        outputDir=str(tmp_path),
    )
    build_graph(cfg)
    return json.loads((tmp_path / "graph.json").read_text())


class TestSafeLayoutName:
    def test_gt_replaced_with_dash(self):
        assert _safe_layout_name("REGION>RG>TYPE") == "REGION-RG-TYPE"
        assert _safe_layout_name("VNET>SUBNET") == "VNET-SUBNET"
        assert _safe_layout_name("SUB>REGION>RG>NET") == "SUB-REGION-RG-NET"


class TestRenderCombinations:
    """Unit tests for the shared render_combinations() core."""

    def test_returns_all_succeeded_on_valid_graph(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        s, f = render_combinations(
            graph, "test",
            ["sub"], ["rg"],
            tmp_path / "out",
        )
        expected = len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)
        assert s == expected
        assert f == 0

    def test_creates_one_subfolder_per_combination(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        dirs = [d for d in out.iterdir() if d.is_dir()]
        assert len(dirs) == len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)

    def test_each_combo_has_drawio_and_docs(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        for combo_dir in out.iterdir():
            assert (combo_dir / "diagram.drawio").exists(), combo_dir
            assert (combo_dir / "catalog.md").exists(), combo_dir
            assert (combo_dir / "edges.md").exists(), combo_dir
            assert (combo_dir / "routing.md").exists(), combo_dir
            assert (combo_dir / "migration.md").exists(), combo_dir

    def test_each_combo_drawio_is_valid_xml(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        for combo_dir in out.iterdir():
            tree = ET.parse(str(combo_dir / "diagram.drawio"))
            assert tree.getroot().tag == "mxfile"

    def test_each_combo_drawio_references_resolve(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        for combo_dir in out.iterdir():
            assert_drawio_references_resolve(combo_dir / "diagram.drawio")

    def test_graph_json_written_per_combo(self, tmp_path):
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        for combo_dir in out.iterdir():
            data = json.loads((combo_dir / "graph.json").read_text())
            assert "nodes" in data and "edges" in data

    def test_sub_rg_net_variant_folders_exist(self, tmp_path):
        """SUB>REGION>RG>NET should produce MSFT and L2R variant folders."""
        graph = _make_graph(tmp_path / "build")
        out = tmp_path / "out"
        render_combinations(graph, "test", ["sub"], ["rg"], out)
        assert (out / "SUB-REGION-RG-NET_MSFT").is_dir()
        assert (out / "SUB-REGION-RG-NET_L2R").is_dir()
        for mode in ("MSFT", "L2R"):
            drawio = out / f"SUB-REGION-RG-NET_{mode}" / "diagram.drawio"
            assert drawio.exists(), f"Missing drawio for SUB-REGION-RG-NET_{mode}"
            root = ET.parse(str(drawio)).getroot()
            assert root.tag == "mxfile"

    def test_landing_zone_fixture_in_test_all(self, tmp_path):
        """The app_landing_zone fixture should be discovered and rendered."""
        run_test_all(str(tmp_path))
        lz_dir = tmp_path / "app_landing_zone"
        assert lz_dir.is_dir(), "app_landing_zone fixture not rendered"
        # Should have all layout × mode combinations
        sub_dirs = [d for d in lz_dir.iterdir() if d.is_dir()]
        assert len(sub_dirs) == len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)
        # SUB>REGION>RG>NET variants should have subscription containers
        for mode in ("MSFT", "L2R"):
            drawio = lz_dir / f"SUB-REGION-RG-NET_{mode}" / "diagram.drawio"
            assert drawio.exists()


class TestRunTestAll:
    """Integration tests for the fixture-based test-all path."""

    def test_all_combinations_succeed(self, tmp_path):
        run_test_all(str(tmp_path))

    def test_expected_folder_count(self, tmp_path):
        run_test_all(str(tmp_path))
        fixtures = _discover_fixtures()
        expected = len(fixtures) * len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)
        drawio_files = list(tmp_path.rglob("diagram.drawio"))
        assert len(drawio_files) == expected

    def test_each_combination_has_valid_drawio_xml(self, tmp_path):
        run_test_all(str(tmp_path))
        for drawio_path in tmp_path.rglob("diagram.drawio"):
            root = ET.parse(str(drawio_path)).getroot()
            assert root.tag == "mxfile", f"Invalid root in {drawio_path}"

    def test_each_combination_drawio_references_resolve(self, tmp_path):
        run_test_all(str(tmp_path))
        for drawio_path in tmp_path.rglob("diagram.drawio"):
            assert_drawio_references_resolve(drawio_path)

    def test_no_build_temp_dirs_left_behind(self, tmp_path):
        run_test_all(str(tmp_path))
        assert not any(tmp_path.rglob(".build"))


class TestRunRenderAll:
    """Integration tests for the end-user render-all path."""

    def _setup_cfg(self, tmp_path: Path) -> Config:
        fixture = FIXTURES / "app_contoso.json"
        shutil.copy2(fixture, tmp_path / "inventory.json")
        (tmp_path / "unresolved.json").write_text("[]")
        cfg = Config(
            app="contoso",
            subscriptions=["00000000-0000-0000-0000-000000000001"],
            seedResourceGroups=["rg-contoso-prod"],
            outputDir=str(tmp_path),
        )
        build_graph(cfg)
        return cfg

    def test_render_all_succeeds(self, tmp_path):
        cfg = self._setup_cfg(tmp_path)
        run_render_all(cfg)

    def test_variants_folder_created(self, tmp_path):
        cfg = self._setup_cfg(tmp_path)
        run_render_all(cfg)
        assert (tmp_path / "variants").is_dir()

    def test_expected_variant_count(self, tmp_path):
        cfg = self._setup_cfg(tmp_path)
        run_render_all(cfg)
        variants = [d for d in (tmp_path / "variants").iterdir() if d.is_dir()]
        assert len(variants) == len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)

    def test_each_variant_has_drawio(self, tmp_path):
        cfg = self._setup_cfg(tmp_path)
        run_render_all(cfg)
        for variant_dir in (tmp_path / "variants").iterdir():
            assert (variant_dir / "diagram.drawio").exists(), variant_dir

    def test_primary_output_intact(self, tmp_path):
        """render-all must not overwrite the user's primary graph.json."""
        cfg = self._setup_cfg(tmp_path)
        original_graph = (tmp_path / "graph.json").read_text()
        run_render_all(cfg)
        assert (tmp_path / "graph.json").read_text() == original_graph

    def test_raises_if_graph_missing(self, tmp_path):
        cfg = Config(
            app="x", subscriptions=["s"], seedResourceGroups=["rg"],
            outputDir=str(tmp_path),
        )
        with pytest.raises(FileNotFoundError, match="graph.json not found"):
            run_render_all(cfg)
