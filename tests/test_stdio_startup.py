"""Real MCP startup must remain usable while a mailbox TLS handshake is stalled."""
import asyncio
import json
import os
import secrets
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_can_initialize_and_report_status_before_mailbox_connects(tmp_path):
    async def exercise():
        connected = asyncio.Event()
        connections = []

        async def stalled_mailbox(reader, writer):
            connections.append(writer)
            connected.set()
            # Consume ClientHello but never send TLS data or an IMAP greeting.
            try:
                await reader.read()
            finally:
                writer.close()

        server = await asyncio.start_server(stalled_mailbox, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "campus_mail_mcp.cli", "--env-file", os.devnull,
                  "serve", "--transport", "stdio"],
            env={
                "CAMPUS_MODE": "imap",
                "CAMPUS_DATA_DIR": str(tmp_path / "data"),
                "CAMPUS_TOKEN": secrets.token_urlsafe(36),
                "CAMPUS_TIMEOUT_SECONDS": "20",
                "MAIL_IMAP_HOST": "127.0.0.1",
                "MAIL_IMAP_PORT": str(port),
                "MAIL_IMAP_SECURITY": "ssl",
                "MAIL_USERNAME": "synthetic-test-user",
                "MAIL_PASSWORD": "synthetic-test-only",
            },
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    # The mailbox cannot finish for 20 seconds; MCP must answer sooner.
                    async with asyncio.timeout(5):
                        await session.initialize()
                        await connected.wait()
                        result = await session.call_tool("get_mail_status", {})
                    assert not result.isError
                    data = result.structuredContent or json.loads(result.content[0].text)
                    assert data["ok"]
                    assert data["data"]["status"] == "SYNCING"
                    assert data["meta"]["is_demo"] is False
                    assert data["data"]["cached_message_count"] == 0
        finally:
            server.close()
            await server.wait_closed()
            for writer in connections:
                writer.close()

    asyncio.run(exercise())
