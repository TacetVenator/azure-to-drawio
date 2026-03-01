"""Tests for the test-all combination generator."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import VALID_LAYOUTS, VALID_DIAGRAM_MODES
from tools.azdisc.test_all import run_test_all, _discover_fixtures, _safe_layout_name


class TestTestAll:
    """Verify that test-all generates every combination successfully."""

    def test_all_combinations_succeed(self, tmp_path):
        run_test_all(str(tmp_path))

    def test_expected_folder_count(self, tmp_path):
        run_test_all(str(tmp_path))
        fixtures = _discover_fixtures()
        expected = len(fixtures) * len(VALID_LAYOUTS) * len(VALID_DIAGRAM_MODES)
        combo_dirs = [
            d for d in tmp_path.rglob("diagram.drawio")
        ]
        assert len(combo_dirs) == expected

    def test_each_combination_has_valid_drawio_xml(self, tmp_path):
        run_test_all(str(tmp_path))
        for drawio_path in tmp_path.rglob("diagram.drawio"):
            tree = ET.parse(str(drawio_path))
            root = tree.getroot()
            assert root.tag == "mxfile", f"Invalid root in {drawio_path}"

    def test_each_combination_has_graph_json(self, tmp_path):
        run_test_all(str(tmp_path))
        for graph_path in tmp_path.rglob("graph.json"):
            data = json.loads(graph_path.read_text())
            assert "nodes" in data
            assert "edges" in data
            assert len(data["nodes"]) > 0

    def test_each_combination_has_docs(self, tmp_path):
        run_test_all(str(tmp_path))
        for combo_dir in tmp_path.rglob("diagram.drawio"):
            parent = combo_dir.parent
            assert (parent / "catalog.md").exists()
            assert (parent / "edges.md").exists()
            assert (parent / "routing.md").exists()

    def test_safe_layout_name(self):
        assert _safe_layout_name("REGION>RG>TYPE") == "REGION-RG-TYPE"
        assert _safe_layout_name("VNET>SUBNET") == "VNET-SUBNET"
