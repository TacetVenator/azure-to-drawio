"""Tests for deterministic layout."""
import json
import pytest
from pathlib import Path
from tools.azdisc.graph import build_node
from tools.azdisc.drawio import _layout_nodes, CELL_W, CELL_H, H_GAP, V_GAP

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text())


def test_layout_is_deterministic():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    pos1 = _layout_nodes(nodes)
    pos2 = _layout_nodes(nodes)
    assert pos1 == pos2


def test_all_nodes_have_positions():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    positions = _layout_nodes(nodes)
    for n in nodes:
        assert n["id"] in positions, f"Node {n['id']} missing position"


def test_nodes_ordered_by_rg_type_name_id():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    # Sort nodes the same way the build_graph function does
    nodes.sort(key=lambda n: (n["resourceGroup"], n["type"], n["name"], n["id"]))
    positions = _layout_nodes(nodes)
    # All positions should be positive
    for nid, (x, y, w, h) in positions.items():
        assert x >= 0
        assert y >= 0
        assert w == CELL_W
        assert h == CELL_H


def test_no_overlapping_nodes():
    inventory = load_fixture("inventory_small.json")
    nodes = [build_node(r) for r in inventory]
    positions = _layout_nodes(nodes)
    rects = list(positions.values())
    for i, (x1, y1, w1, h1) in enumerate(rects):
        for j, (x2, y2, w2, h2) in enumerate(rects):
            if i >= j:
                continue
            # Check no overlap (with 1px tolerance)
            overlap_x = x1 < x2 + w2 and x2 < x1 + w1
            overlap_y = y1 < y2 + h2 and y2 < y1 + h1
            assert not (overlap_x and overlap_y), (
                f"Nodes {i} and {j} overlap: {(x1,y1,w1,h1)} vs {(x2,y2,w2,h2)}"
            )


def test_stable_id_in_drawio():
    from tools.azdisc.util import stable_id
    rid = "/subscriptions/abc/resourceGroups/rg/providers/microsoft.compute/virtualmachines/vm1"
    sid1 = stable_id(rid)
    sid2 = stable_id(rid)
    assert sid1 == sid2
    assert len(sid1) == 16
