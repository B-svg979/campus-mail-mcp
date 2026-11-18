"""A short-lived MCP caller must obtain data on its first tool request."""
import asyncio
import json
import sys
import time

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from campus_mail_mcp.config import Settings
from campus_mail_mcp.providers import demo_snapshot
from campus_mail_mcp.service import MailService

ENTRY = """
import os,time
from pathlib import Path
from campus_mail_mcp import providers
from campus_mail_mcp.cli import main
from campus_mail_mcp.config import MailError
def collect(settings):
    Path(os.environ['TEST_SYNC_STARTED']).touch()
    while not Path(os.environ['TEST_SYNC_GATE']).exists():
        time.sleep(0.01)
    if os.environ.get('TEST_SYNC_FAILURE'):
        raise MailError('AUTH_REQUIRED','Synthetic authentication failure')
    return providers.demo_snapshot(settings)
providers.collect=collect
raise SystemExit(main(['--env-file',os.devnull,'serve','--transport','stdio']))
"""


def decode(response):
    assert not response.isError
    return response.structuredContent or json.loads(response.content[0].text)


def parameters(tmp_path, wait=5, fail=False):
    return StdioServerParameters(command=sys.executable, args=["-c", ENTRY], env={
        "CAMPUS_MODE": "demo", "CAMPUS_DATA_DIR": str(tmp_path / "data"),
        "CAMPUS_INITIAL_SYNC_WAIT_SECONDS": str(wait),
        "TEST_SYNC_STARTED": str(tmp_path / "started"),
        "TEST_SYNC_GATE": str(tmp_path / "gate"),
        "TEST_SYNC_FAILURE": "1" if fail else "",
    })


@pytest.mark.parametrize("name", ["get_mail_status", "search_mail", "get_mail", "read_attachment"])
def test_first_tool_call_waits_for_snapshot_without_blocking_initialize(tmp_path, name):
    example = next(mail for mail in demo_snapshot(Settings()).mails if mail.attachments)
    arguments = {
        "get_mail_status": {}, "search_mail": {"query": "活动"},
        "get_mail": {"mail_id": example.id},
        "read_attachment": {"mail_id": example.id, "attachment_id": example.attachments[0].id},
    }[name]

    async def exercise():
        async with stdio_client(parameters(tmp_path)) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                async with asyncio.timeout(5):
                    await client.initialize()
                    while not (tmp_path / "started").exists():
                        await asyncio.sleep(0.01)
                # Collection is gated, so successful initialize proves that it did not wait.
                pending = asyncio.create_task(client.call_tool(name, arguments))
                await asyncio.sleep(0.1)
                assert not pending.done()
                (tmp_path / "gate").touch()
                result = decode(await asyncio.wait_for(pending, 5))
                assert result["ok"]
                assert result["meta"]["last_success_at"]
                if name == "get_mail_status":
                    assert result["data"]["status"] == "READY"
                elif name == "search_mail":
                    assert result["data"]["items"]
                else:
                    assert result["data"]["body"]["text"]

    asyncio.run(exercise())


def test_initial_sync_wait_expires_and_reports_syncing(tmp_path):
    async def exercise():
        async with stdio_client(parameters(tmp_path, wait=1)) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                async with asyncio.timeout(5):
                    while not (tmp_path / "started").exists():
                        await asyncio.sleep(0.01)
                started = time.monotonic()
                result = decode(await asyncio.wait_for(client.call_tool("get_mail_status", {}), 3))
                assert 0.7 <= time.monotonic() - started < 3
                assert result["data"]["status"] == "SYNCING"
                assert result["meta"]["last_success_at"] is None
                (tmp_path / "gate").touch()

    asyncio.run(exercise())


def test_first_query_returns_the_collection_failure(tmp_path):
    async def exercise():
        async with stdio_client(parameters(tmp_path, fail=True)) as (reader, writer):
            async with ClientSession(reader, writer) as client:
                await client.initialize()
                pending = asyncio.create_task(client.call_tool("search_mail", {}))
                await asyncio.sleep(0.1)
                (tmp_path / "gate").touch()
                result = decode(await asyncio.wait_for(pending, 5))
                assert not result["ok"] and result["error"]["code"] == "AUTH_REQUIRED"
                assert result["meta"]["last_success_at"] is None

    asyncio.run(exercise())


def test_offline_status_with_no_worker_does_not_wait(tmp_path):
    service = MailService(Settings(data_dir=tmp_path, initial_sync_wait_seconds=60))
    started = time.monotonic()
    assert service.get_mail_status()["data"]["status"] == "NOT_SYNCED"
    assert time.monotonic() - started < 1
