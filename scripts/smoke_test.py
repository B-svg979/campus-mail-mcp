"""A real MCP client: initialize -> tools/list -> tools/call over Streamable HTTP.

Reads CAMPUS_TOKEN from the selected .env, never prints it. It prints only counts,
mode and tool names; no email subject, body, sender or attachment content.
"""

import argparse
import asyncio
import json
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from campus_mail_mcp.config import Settings


def tool_data(result):
    data = result.structuredContent or json.loads(result.content[0].text)
    if result.isError or not data["ok"]:
        raise RuntimeError("MCP tool call failed")
    return data


async def check(url, settings, exercise_demo=False):
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {settings.token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("get_mail_status", {})
            data = tool_data(result)
            names = sorted(tool.name for tool in tools.tools)
            expected = ["get_mail", "get_mail_status", "read_attachment", "search_mail"]
            if names != expected:
                raise RuntimeError("Unexpected tool list")
            read_flow_verified = False
            if exercise_demo:
                if not data["meta"]["is_demo"]:
                    raise RuntimeError("--exercise-demo only runs against synthetic demo data")
                found = tool_data(await session.call_tool("search_mail", {"query": "活动"}))
                item = found["data"]["items"][0]
                mail = tool_data(await session.call_tool("get_mail", {"mail_id": item["id"]}))
                attachment = mail["data"]["attachments"][0]
                parsed = tool_data(
                    await session.call_tool(
                        "read_attachment",
                        {
                            "mail_id": item["id"],
                            "attachment_id": attachment["id"],
                        },
                    )
                )
                if "报名截止" not in parsed["data"]["body"]["text"]:
                    raise RuntimeError("Demo attachment evidence not found")
                read_flow_verified = True
            print(
                json.dumps(
                    {
                        "ok": True,
                        "tools": names,
                        "mode": data["meta"]["mode"],
                        "is_demo": data["meta"]["is_demo"],
                        "status": data["data"]["status"],
                        "read_flow_verified": read_flow_verified,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8765/mcp")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument(
        "--exercise-demo",
        action="store_true",
        help="在 demo 模式进一步验证搜索、正文和附件的完整调用链",
    )
    args = parser.parse_args()
    try:
        asyncio.run(check(args.url, Settings.load(args.env_file), args.exercise_demo))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "hint": "检查服务是否启动、URL 是否为 /mcp、Token 和 allowed hosts 是否匹配。",
                },
                ensure_ascii=False,
            )
        )
        sys.exit(1)
