import json

import pytest
from starlette.testclient import TestClient

from campus_mail_mcp.config import MailError, Settings
from campus_mail_mcp.server import create_app
from campus_mail_mcp.service import MailService

TOKEN = "transport-test-token-" + "x" * 40
AUTH = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json, text/event-stream"}


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, token=TOKEN)
    service = MailService(settings)
    assert service.sync()["ok"]
    with TestClient(
        create_app(settings, service, background_sync=False), base_url="http://127.0.0.1:8765"
    ) as client:
        yield client


def rpc(client, method, params=None, headers=None):
    return client.post(
        "/mcp",
        headers=headers or AUTH,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_auth_applies_to_all_mcp_methods(client):
    for method in ("GET", "POST", "DELETE"):
        assert client.request(method, "/mcp").status_code == 401
        assert (
            client.request(method, "/mcp", headers={"Authorization": "Bearer wrong"}).status_code
            == 401
        )
    assert client.get("/healthz").json()["service"] == "campus-mail-mcp"
    assert "mail" not in client.get("/healthz").json()


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"])
def test_real_protocol_init_discovery_and_call(client, version):
    response = rpc(
        client,
        "initialize",
        {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": {"name": "school-platform-test", "version": "1"},
        },
    )
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "Campus Mail MCP"
    response = rpc(client, "tools/list")
    assert response.status_code == 200
    tools = response.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == {
        "get_mail_status",
        "search_mail",
        "get_mail",
        "read_attachment",
    }
    assert all(tool["annotations"]["readOnlyHint"] for tool in tools)
    result = rpc(
        client, "tools/call", {"name": "search_mail", "arguments": {"query": "活动"}}
    ).json()["result"]
    assert not result.get("isError")
    # Older hosts receive JSON text; structuredContent was added in a later spec.
    data = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert data["ok"]
    assert data["meta"]["is_demo"]


def test_host_origin_and_request_size_protection(client):
    assert (
        rpc(client, "tools/list", headers={**AUTH, "Host": "attacker.example"}).status_code == 421
    )
    assert (
        rpc(
            client, "tools/list", headers={**AUTH, "Origin": "https://attacker.example"}
        ).status_code
        == 403
    )
    response = client.post(
        "/mcp", headers={**AUTH, "Content-Type": "application/json"}, content=b"x" * 70000
    )
    assert response.status_code == 413


def test_missing_token_refuses_http_start(tmp_path):
    with pytest.raises(MailError, match="随机"):
        create_app(Settings(data_dir=tmp_path))
