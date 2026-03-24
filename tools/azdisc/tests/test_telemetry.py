"""Tests for the telemetry enrichment module (pure/non-Azure functions)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.azdisc.config import Config, load_config
from tools.azdisc.telemetry import (
    _LA_WORKSPACE_CACHE,
    _collect_nic_ips,
    _looks_like_uuid,
    _resolve_hostname,
    _resolve_la_workspace_identifier,
    _run_la_query,
    run_telemetry_enrichment,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_MINIMAL_GRAPH = {
    "nodes": [
        {
            "id": "/subscriptions/00000000-0000-0000-0000-000000000001/resourceGroups/rg-test/providers/Microsoft.Compute/virtualMachines/vm1",
            "name": "vm1",
            "type": "microsoft.compute/virtualmachines",
            "location": "eastus",
            "resourceGroup": "rg-test",
            "subscriptionId": "00000000-0000-0000-0000-000000000001",
            "tags": {},
            "properties": {},
        }
    ],
    "edges": [],
}

_NODE_BY_NAME = {
    "myaccount": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Storage/storageAccounts/myaccount",
    "myserver": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Sql/servers/myserver",
    "myvault": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.KeyVault/vaults/myvault",
    "myweb": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Web/sites/myweb",
    "mybus": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ServiceBus/namespaces/mybus",
    "mycosmos": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.DocumentDB/databaseAccounts/mycosmos",
    "mysearch": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Search/searchServices/mysearch",
    "mycognitive": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.CognitiveServices/accounts/mycognitive",
    "myregistry": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.ContainerRegistry/registries/myregistry",
    "myredis": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Cache/Redis/myredis",
    "myhdinsight": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.HDInsight/clusters/myhdinsight",
    "myeventgrid": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.EventGrid/topics/myeventgrid",
    "mymysql": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.DBforMySQL/servers/mymysql",
    "mypostgres": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.DBforPostgreSQL/servers/mypostgres",
}


def _make_config(tmp_path: Path) -> Config:
    return Config(
        app="test-app",
        subscriptions=["00000000-0000-0000-0000-000000000001"],
        seedResourceGroups=["rg-test"],
        outputDir=str(tmp_path),
    )


# ---------------------------------------------------------------------------
# Tests: _resolve_hostname
# ---------------------------------------------------------------------------


class TestResolveHostname:
    def test_blob_storage(self):
        result = _resolve_hostname("myaccount.blob.core.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_queue_storage(self):
        result = _resolve_hostname("myaccount.queue.core.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_table_storage(self):
        result = _resolve_hostname("myaccount.table.core.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_file_storage(self):
        result = _resolve_hostname("myaccount.file.core.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_dfs_storage(self):
        result = _resolve_hostname("myaccount.dfs.core.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_sql_server(self):
        result = _resolve_hostname("myserver.database.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myserver"]

    def test_servicebus(self):
        result = _resolve_hostname("mybus.servicebus.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mybus"]

    def test_web_app(self):
        result = _resolve_hostname("myweb.azurewebsites.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myweb"]

    def test_key_vault(self):
        result = _resolve_hostname("myvault.vault.azure.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myvault"]

    def test_cosmos_db(self):
        result = _resolve_hostname("mycosmos.documents.azure.com", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mycosmos"]

    def test_search_service(self):
        result = _resolve_hostname("mysearch.search.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mysearch"]

    def test_cognitive_services(self):
        result = _resolve_hostname("mycognitive.cognitiveservices.azure.com", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mycognitive"]

    def test_container_registry(self):
        result = _resolve_hostname("myregistry.azurecr.io", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myregistry"]

    def test_redis_cache(self):
        result = _resolve_hostname("myredis.redis.cache.windows.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myredis"]

    def test_hdinsight(self):
        result = _resolve_hostname("myhdinsight.azurehdinsight.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myhdinsight"]

    def test_eventgrid(self):
        result = _resolve_hostname("myeventgrid.eventgrid.azure.net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myeventgrid"]

    def test_mysql(self):
        result = _resolve_hostname("mymysql.mysql.database.azure.com", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mymysql"]

    def test_postgres(self):
        result = _resolve_hostname("mypostgres.postgres.database.azure.com", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["mypostgres"]

    def test_unrecognised_hostname_returns_none(self):
        result = _resolve_hostname("some-external-service.example.com", _NODE_BY_NAME)
        assert result is None

    def test_unknown_azure_name_returns_none(self):
        result = _resolve_hostname("notinventory.blob.core.windows.net", _NODE_BY_NAME)
        assert result is None

    def test_case_insensitive(self):
        result = _resolve_hostname("MyAccount.Blob.Core.Windows.Net", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]

    def test_hostname_with_port_stripped(self):
        result = _resolve_hostname("myaccount.blob.core.windows.net:443", _NODE_BY_NAME)
        assert result == _NODE_BY_NAME["myaccount"]


# ---------------------------------------------------------------------------
# Tests: _collect_nic_ips
# ---------------------------------------------------------------------------


class TestCollectNicIps:
    def _make_nic_node(self, node_id: str, ips: list) -> dict:
        ip_configs = [
            {"properties": {"privateIPAddress": ip}} for ip in ips
        ]
        return {
            "id": node_id,
            "type": "microsoft.network/networkinterfaces",
            "name": node_id.split("/")[-1],
            "properties": {"ipConfigurations": ip_configs},
        }

    def test_single_nic_single_ip(self):
        node = self._make_nic_node(
            "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic1",
            ["10.0.0.4"],
        )
        result = _collect_nic_ips([node])
        assert result["10.0.0.4"] == "/subscriptions/sub1/resourcegroups/rg1/providers/microsoft.network/networkinterfaces/nic1"

    def test_nic_multiple_ips(self):
        node = self._make_nic_node(
            "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic2",
            ["10.0.0.5", "10.0.0.6"],
        )
        result = _collect_nic_ips([node])
        assert "10.0.0.5" in result
        assert "10.0.0.6" in result

    def test_non_nic_nodes_ignored(self):
        vm_node = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Compute/virtualMachines/vm1",
            "type": "microsoft.compute/virtualmachines",
            "name": "vm1",
            "properties": {},
        }
        result = _collect_nic_ips([vm_node])
        assert result == {}

    def test_nic_with_no_ip_configs(self):
        node = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/Microsoft.Network/networkInterfaces/nic3",
            "type": "microsoft.network/networkinterfaces",
            "name": "nic3",
            "properties": {"ipConfigurations": []},
        }
        result = _collect_nic_ips([node])
        assert result == {}

    def test_empty_nodes_list(self):
        assert _collect_nic_ips([]) == {}


# ---------------------------------------------------------------------------
# Tests: Log Analytics workspace resolution and query handling
# ---------------------------------------------------------------------------


def test_resolve_la_workspace_identifier_converts_arm_id_to_customer_id(monkeypatch):
    _LA_WORKSPACE_CACHE.clear()
    workspace_arm_id = "/subscriptions/sub1/resourceGroups/rg-log/providers/Microsoft.OperationalInsights/workspaces/ws1"

    calls = []

    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        return Result(0, json.dumps({"customerId": "customer-guid-1234"}))

    monkeypatch.setattr("tools.azdisc.telemetry.subprocess.run", fake_run)

    resolved = _resolve_la_workspace_identifier(workspace_arm_id)

    assert resolved == "customer-guid-1234"
    assert calls[0][:5] == ["az", "monitor", "log-analytics", "workspace", "show"]
    assert calls[0][5:] == ["--ids", workspace_arm_id, "--output", "json"]


def test_run_la_query_uses_resolved_customer_id_and_logs_troubleshooting(monkeypatch, caplog):
    _LA_WORKSPACE_CACHE.clear()
    workspace_arm_id = "/subscriptions/sub1/resourceGroups/rg-log/providers/Microsoft.OperationalInsights/workspaces/ws1"

    calls = []

    class Result:
        def __init__(self, returncode, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        if cmd[:5] == ["az", "monitor", "log-analytics", "workspace", "show"]:
            return Result(0, json.dumps({"customerId": "customer-guid-1234"}))
        return Result(1, "", "ERROR: (PathNotFoundError) The requested path does not exist")

    monkeypatch.setattr("tools.azdisc.telemetry.subprocess.run", fake_run)

    rows = _run_la_query(workspace_arm_id, "AppDependencies | take 1", ["sub1"])

    assert rows == []
    assert calls[1][:4] == ["az", "monitor", "log-analytics", "query"]
    assert "customer-guid-1234" in calls[1]
    assert "Troubleshooting:" in caplog.text
    assert "query target customer-guid-1234" in caplog.text


# ---------------------------------------------------------------------------
# Tests: _looks_like_uuid
# ---------------------------------------------------------------------------


class TestLooksLikeUuid:
    def test_valid_uuid_lowercase(self):
        assert _looks_like_uuid("12345678-1234-1234-1234-123456789abc") is True

    def test_valid_uuid_uppercase(self):
        assert _looks_like_uuid("12345678-1234-1234-1234-123456789ABC") is True

    def test_email_address(self):
        assert _looks_like_uuid("user@example.com") is False

    def test_partial_uuid(self):
        assert _looks_like_uuid("12345678-1234-1234") is False

    def test_empty_string(self):
        assert _looks_like_uuid("") is False

    def test_plain_name(self):
        assert _looks_like_uuid("my-service-principal") is False

    def test_uuid_with_whitespace(self):
        assert _looks_like_uuid("  12345678-1234-1234-1234-123456789abc  ") is True


# ---------------------------------------------------------------------------
# Tests: run_telemetry_enrichment raises FileNotFoundError
# ---------------------------------------------------------------------------


def test_run_telemetry_enrichment_missing_graph_json(tmp_path):
    cfg = _make_config(tmp_path)
    with pytest.raises(FileNotFoundError, match="graph.json"):
        run_telemetry_enrichment(cfg)


def test_run_telemetry_enrichment_reports_invalid_graph_json(tmp_path):
    (tmp_path / "graph.json").write_text('{"nodes": [}')
    cfg = _make_config(tmp_path)

    with pytest.raises(RuntimeError, match="Telemetry stage graph artifact") as excinfo:
        run_telemetry_enrichment(cfg)

    assert "graph.json" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Tests: run_telemetry_enrichment skips gracefully with minimal fixture
# ---------------------------------------------------------------------------


def test_run_telemetry_enrichment_no_relevant_resources(tmp_path):
    """With a graph that has only a VM node, all phases should skip gracefully."""
    graph_path = tmp_path / "graph.json"
    graph_path.write_text(json.dumps(_MINIMAL_GRAPH))

    cfg = _make_config(tmp_path)
    # Should complete without raising
    run_telemetry_enrichment(cfg)

    # Verify graph.json is intact and VM node is still present
    result = json.loads(graph_path.read_text())
    assert len(result["nodes"]) == 1
    assert result["nodes"][0]["name"] == "vm1"
    # No new telemetry edges expected
    assert result["telemetryEdges"] == []


# ---------------------------------------------------------------------------
# Tests: Config defaults and validation
# ---------------------------------------------------------------------------


def test_config_enable_telemetry_defaults_false(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "app": "test",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg1"],
        "outputDir": str(tmp_path),
    }))
    cfg = load_config(str(config_file))
    assert cfg.enableTelemetry is False


def test_config_telemetry_lookback_days_defaults_to_7(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "app": "test",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg1"],
        "outputDir": str(tmp_path),
    }))
    cfg = load_config(str(config_file))
    assert cfg.telemetryLookbackDays == 7


def test_config_telemetry_lookback_days_custom(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "app": "test",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg1"],
        "outputDir": str(tmp_path),
        "telemetryLookbackDays": 30,
    }))
    cfg = load_config(str(config_file))
    assert cfg.telemetryLookbackDays == 30


@pytest.mark.parametrize("bad_value", [0, -1, "seven", 0.5, None])
def test_config_telemetry_lookback_days_invalid_raises(tmp_path, bad_value):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({
        "app": "test",
        "subscriptions": ["sub1"],
        "seedResourceGroups": ["rg1"],
        "outputDir": str(tmp_path),
        "telemetryLookbackDays": bad_value,
    }))
    with pytest.raises(ValueError, match="telemetryLookbackDays"):
        load_config(str(config_file))
