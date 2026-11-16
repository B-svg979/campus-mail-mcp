from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
from pathlib import Path

from dotenv import dotenv_values, set_key

from .config import MailError, Settings
from .providers import check_connection
from .service import MailService, safe_error


def write_env(path: Path, values: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(descriptor)
    path.chmod(0o600)
    for key, value in values.items():
        set_key(str(path), key, str(value), quote_mode="always")
    path.chmod(0o600)


def initialize(path: Path, mode: str):
    if path.exists():
        raise MailError(
            "CONFIG_EXISTS", "配置文件已存在，init 不会覆盖。修改 .env 或使用 configure。"
        )
    write_env(
        path,
        {
            "CAMPUS_MODE": mode,
            "CAMPUS_TOKEN": secrets.token_urlsafe(36),
            "CAMPUS_DATA_DIR": f"./data-{mode}",
            "CAMPUS_HOST": "127.0.0.1",
            "CAMPUS_PORT": "8765",
            "CAMPUS_ALLOWED_HOSTS": "localhost:*,127.0.0.1:*,[::1]:*",
            "CAMPUS_ALLOWED_ORIGINS": "",
            "CAMPUS_TIMEZONE": "Asia/Shanghai",
            "CAMPUS_SYNC_SECONDS": "900",
            "CAMPUS_LOOKBACK_DAYS": "30",
            "CAMPUS_MAX_MESSAGES": "200",
            "MAIL_EWS_URL": "https://mail.xjtlu.edu.cn/EWS/Exchange.asmx",
            "MAIL_EWS_AUTH": "NTLM",
            "MAIL_USERNAME": "",
            "MAIL_PASSWORD": "",
            "MAIL_ADDRESS": "",
            "MAIL_IMAP_HOST": "mail.xjtlu.edu.cn",
            "MAIL_IMAP_PORT": "993",
            "MAIL_IMAP_SECURITY": "ssl",
            "MAIL_IMAP_FOLDER": "INBOX",
            "MAIL_IMAP_AUTH": "password",
            "MAIL_IMAP_ACCESS_TOKEN": "",
            "CAMPUS_EML_DIR": "./mail-import",
        },
    )
    return {
        "ok": True,
        "config_file": str(path.resolve()),
        "mode": mode,
        "note": "随机 Bearer Token 已保存在配置文件，不在终端输出。配置文件应只通过程序读取，不要 source。",
    }


def configure(path: Path, mode: str):
    if not path.exists():
        initialize(path, mode)
    current = dotenv_values(path, interpolate=False)
    values = {"CAMPUS_MODE": mode}
    print("在本机配置单一邮箱。密码输入时不显示，也不会发给 MCP 客户端。", file=sys.stderr)
    username = input("邮箱登录用户名：").strip()
    if not username:
        raise MailError("INVALID_ARGUMENT", "用户名不能为空。")
    password = getpass.getpass("邮箱密码/应用密码（保存在本机 .env）：")
    if not password:
        raise MailError("INVALID_ARGUMENT", "密码不能为空。")
    values.update(MAIL_USERNAME=username, MAIL_PASSWORD=password)
    if mode == "ews":
        address = input("完整邮箱地址（例如 name@student.xjtlu.edu.cn）：").strip()
        endpoint = input(f"EWS HTTPS 地址 [{Settings.ews_url}]：").strip() or Settings.ews_url
        values.update(MAIL_ADDRESS=address, MAIL_EWS_URL=endpoint, MAIL_EWS_AUTH="NTLM")
    else:
        host = input(f"IMAP 主机 [{Settings.imap_host}]：").strip() or Settings.imap_host
        values.update(MAIL_IMAP_HOST=host, MAIL_IMAP_AUTH="password")
    # Separate caches for each mailbox/provider; never relabel demo data as live mail.
    from .content import identifier

    values["CAMPUS_DATA_DIR"] = (
        f"./data-{mode}-{identifier(username, values.get('MAIL_ADDRESS', ''))[:8]}"
    )
    if not current.get("CAMPUS_TOKEN"):
        values["CAMPUS_TOKEN"] = secrets.token_urlsafe(36)
    write_env(path, values)
    return {
        "ok": True,
        "mode": mode,
        "note": "配置已保存。运行 test-connection 验证，不会读取正文。",
    }


def output(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(description="校园邮件 MCP：配置、同步、服务与本机诊断")
    parser.add_argument("--env-file", default=".env", help="显式配置文件，默认当前工作目录 .env")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="生成配置和随机 Bearer Token，不覆盖现有配置")
    init.add_argument("--mode", choices=["demo", "ews", "imap", "eml"], default="demo")
    config = sub.add_parser("configure", help="在本机交互式配置邮箱凭据")
    config.add_argument("--mode", choices=["ews", "imap"], default="imap")
    sub.add_parser("test-connection", help="只测试认证/文件夹元数据，不读取正文")
    sub.add_parser("sync", help="同步配置范围内邮件；仅输出统计")
    sub.add_parser("status", help="查看本地同步统计，不输出邮件内容")
    serve = sub.add_parser("serve", help="启动 MCP 工具服务")
    serve.add_argument(
        "--transport", choices=["streamable-http", "stdio"], default="streamable-http"
    )
    args = parser.parse_args(argv)
    os.umask(0o077)
    try:
        path = Path(args.env_file)
        if args.command == "init":
            output(initialize(path, args.mode))
            return 0
        if args.command == "configure":
            output(configure(path, args.mode))
            return 0
        settings = Settings.load(path)
        if args.command == "test-connection":
            output(check_connection(settings))
            return 0
        service = MailService(settings)
        if args.command == "sync":
            result = service.sync()
            output(result)
            return 0 if result["ok"] else 1
        if args.command == "status":
            output(service.get_mail_status())
            return 0
        from .server import create_app, create_mcp

        if args.transport == "stdio":
            # STDIO is a local process transport; sync stays outside the tool API.
            # Initial sync runs here, then periodic sync runs on a daemon worker.
            import threading
            import time

            service.sync()

            def periodic():
                while True:
                    time.sleep(settings.sync_seconds)
                    service.sync()

            threading.Thread(target=periodic, daemon=True).start()
            create_mcp(service).run(transport="stdio")
        else:
            import uvicorn

            uvicorn.run(
                create_app(settings, service),
                host=settings.host,
                port=settings.port,
                access_log=False,
                log_level="warning",
            )
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            return 130
        error = safe_error(exc)
        failure = {"ok": False, "error": error.as_dict()}
        if args.command == "serve" and args.transport == "stdio":
            # stdout belongs exclusively to MCP JSON-RPC, including during startup.
            print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        else:
            output(failure)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
