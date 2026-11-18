"""Exercise the four tools with synthetic data in an isolated child process."""
import argparse
import asyncio
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def decode(result):
    value = result.structuredContent or json.loads(result.content[0].text)
    if result.isError or not value.get("ok"):
        raise RuntimeError("Tool returned an error; no credentials or mail data are printed")
    return value


async def check(args):
    with tempfile.TemporaryDirectory(prefix="campus-mail-selftest-") as temp:
        env = {
            "CAMPUS_MODE": "demo",
            "CAMPUS_DATA_DIR": str(Path(temp) / "data"),
            "CAMPUS_TOKEN": secrets.token_urlsafe(36),
            "XIPU_MAIL_MODE": "demo",
            "XIPU_MAIL_DAYS": "7",
            "XIPU_MAIL_LIMIT": "50",
            "PYTHONNOUSERSITE": "1",
        }
        if args.without_system_timezones:
            env["PYTHONTZPATH"] = ""
        if args.platform:
            command_args = ["-m", "campus_mail_platform.launcher"]
        elif args.entry:
            command_args = [str(Path(args.entry).resolve())]
        else:
            command_args = [
                "-m", "campus_mail_mcp.cli", "--env-file", os.devnull,
                "serve", "--transport", "stdio"
            ]
        params = StdioServerParameters(command=sys.executable, args=command_args, env=env)
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = sorted(t.name for t in tools.tools)
                assert names == ["get_mail", "get_mail_status", "read_attachment", "search_mail"]
                status = decode(await session.call_tool("get_mail_status", {}))
                assert status["meta"]["is_demo"] is True
                version = status["data"].get("tool_version")
                assert version == args.expect_version, f"Expected {args.expect_version}, got {version}"
                # First sync is intentionally asynchronous; wait only for synthetic data.
                for _ in range(100):
                    if status["data"]["status"] == "READY":
                        break
                    assert status["data"]["status"] in {"NOT_SYNCED", "SYNCING"}
                    await asyncio.sleep(0.05)
                    status = decode(await session.call_tool("get_mail_status", {}))
                else:
                    raise RuntimeError("Synthetic first sync did not complete within five seconds")
                found = decode(await session.call_tool("search_mail", {"query": "活动"}))
                mail = decode(await session.call_tool("get_mail", {
                    "mail_id": found["data"]["items"][0]["id"]
                }))
                attachment = decode(await session.call_tool("read_attachment", {
                    "mail_id": mail["data"]["id"],
                    "attachment_id": mail["data"]["attachments"][0]["id"],
                }))
                assert "报名截止" in attachment["data"]["body"]["text"]
                print(json.dumps({
                    "ok": True, "tool_version": version, "is_demo": True,
                    "tools": names, "body_and_attachment_read": True,
                    "without_system_timezones": args.without_system_timezones,
                    "credentials_used": False,
                }, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--entry", help="Optional extracted platform python/launch.py")
    parser.add_argument("--platform", action="store_true", help="Use the installed platform wheel")
    parser.add_argument("--expect-version", default="0.1.5")
    parser.add_argument("--without-system-timezones", action="store_true")
    asyncio.run(check(parser.parse_args()))
