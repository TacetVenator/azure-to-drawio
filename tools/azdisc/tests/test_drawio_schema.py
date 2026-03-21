import importlib.util
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from tools.azdisc.config import Config
from tools.azdisc.drawio import generate_drawio
from tools.azdisc.graph import build_graph

FIXTURES = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[3]
XSD = ROOT / "assets" / "mxfile.xsd"


def test_generated_drawio_parses_as_xml(tmp_path):
    (tmp_path / "inventory.json").write_text((FIXTURES / "app_contoso.json").read_text())
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="schema-test",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        layout="SUB>REGION>RG>NET",
        diagramMode="MSFT",
    )
    build_graph(cfg)
    generate_drawio(cfg)
    tree = ET.parse(str(tmp_path / "diagram.drawio"))
    assert tree.getroot().tag == "mxfile"


def test_generated_drawio_validates_against_mxfile_xsd_when_validator_available(tmp_path):
    (tmp_path / "inventory.json").write_text((FIXTURES / "app_contoso.json").read_text())
    (tmp_path / "unresolved.json").write_text("[]")
    cfg = Config(
        app="schema-test",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-contoso-prod"],
        outputDir=str(tmp_path),
        layout="SUB>REGION>RG>NET",
        diagramMode="MSFT",
    )
    build_graph(cfg)
    generate_drawio(cfg)
    drawio_path = tmp_path / "diagram.drawio"

    if shutil.which("xmllint"):
        result = subprocess.run(["xmllint", "--noout", "--schema", str(XSD), str(drawio_path)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return

    if importlib.util.find_spec("lxml"):
        from lxml import etree  # type: ignore

        schema = etree.XMLSchema(etree.parse(str(XSD)))
        doc = etree.parse(str(drawio_path))
        assert schema.validate(doc), schema.error_log.last_error
        return

    pytest.skip("No XSD validator available locally; structural XML parsing still covered")
