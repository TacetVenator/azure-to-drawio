"""Regression tests for the optional azdisc_ui FastAPI app."""
from __future__ import annotations

import pytest


fastapi = pytest.importorskip("fastapi")
pytest.importorskip("httpx")
testclient = pytest.importorskip("fastapi.testclient")

from tools.azdisc_ui.__main__ import create_app


def test_ui_index_renders_html_response() -> None:
    """The index route should render successfully across Starlette versions."""
    client = testclient.TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Azure Discovery Web UI" in response.text
