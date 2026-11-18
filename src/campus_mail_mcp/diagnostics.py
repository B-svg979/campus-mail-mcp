"""Credential-free IMAP network checks; also runnable as a standalone stdlib script."""
from __future__ import annotations

import argparse
import base64
import http.client
import imaplib
import json
import platform
import re
import socket
import ssl
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import getproxies, proxy_bypass


class ProxyError(OSError):
    """Safe proxy failure; never include a proxy URL, headers or remote error text."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {"stage": "PROXY_CONNECT"}


def imap_proxy(host, port, mode="direct"):
    if mode == "direct":
        return None
    if mode != "environment":
        raise ProxyError("CONFIG_ERROR", "IMAP 代理模式只能是 direct 或 environment。")
    proxies = getproxies()
    value = proxies.get("https") or proxies.get("http") or proxies.get("all")
    target = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    if not value or proxy_bypass(target):
        return None
    try:
        proxy = urlsplit(value if "://" in value else "http://" + value)
        valid = (
            proxy.scheme == "http" and proxy.hostname
            and proxy.path in ("", "/") and not proxy.query and not proxy.fragment
            and 1 <= (proxy.port or 80) <= 65535
        )
        if not valid:
            raise ValueError()
    except ValueError:
        raise ProxyError(
            "PROXY_CONFIG_ERROR", "当前 IMAP 连接支持已有 HTTP CONNECT 代理；请核对代理配置。"
        ) from None
    return proxy


def open_imap_socket(host, port, timeout, proxy=None):
    """Return a raw socket via the selected route. Never retry a denied proxy directly."""
    if proxy is None:
        return socket.create_connection((host, port), timeout=timeout)
    connection = http.client.HTTPConnection(proxy.hostname, proxy.port or 80, timeout=timeout)
    headers = {}
    if proxy.username is not None:
        credentials = unquote(proxy.username) + ":" + unquote(proxy.password or "")
        headers["Proxy-Authorization"] = "Basic " + base64.b64encode(
            credentials.encode()
        ).decode("ascii")
    try:
        connection.set_tunnel(host, port, headers=headers)
        connection.connect()
        raw = connection.sock
        connection.sock = None  # Ownership moves to the caller/IMAP client.
        return raw
    except OSError as exc:
        status = re.search(r"Tunnel connection failed: (\d{3})\b", str(exc))
        if status:
            number = int(status.group(1))
            code = {403: "PROXY_FORBIDDEN", 407: "PROXY_AUTH_REQUIRED"}.get(
                number, "PROXY_CONNECTION_FAILED"
            )
            raise ProxyError(
                code, "运行环境的代理未允许建立邮箱连接；请检查平台代理权限。",
                {"stage": "PROXY_CONNECT", "http_status": number},
            ) from None
        error = network_error(exc, "PROXY_CONNECT")
        raise ProxyError(error["code"], error["message"], error["details"]) from None
    except http.client.HTTPException:
        raise ProxyError("PROXY_CONNECTION_FAILED", "运行环境的代理响应无效。") from None
    finally:
        connection.close()


class ProxiedIMAP4(imaplib.IMAP4):
    def __init__(self, host, port, *, proxy, timeout):
        self._mail_proxy = proxy
        super().__init__(host, port, timeout=timeout)

    def _create_socket(self, timeout):
        return open_imap_socket(self.host, self.port, timeout, self._mail_proxy)


class ProxiedIMAP4SSL(imaplib.IMAP4_SSL):
    def __init__(self, host, port, *, proxy, ssl_context, timeout):
        self._mail_proxy = proxy
        super().__init__(host, port, ssl_context=ssl_context, timeout=timeout)

    def _create_socket(self, timeout):
        raw = open_imap_socket(self.host, self.port, timeout, self._mail_proxy)
        try:
            return self.ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def network_error(exc: Exception, stage: str = "connection") -> dict:
    """Classify errors without returning exception text, usernames or credentials."""
    if isinstance(exc, ProxyError):
        return {"code": exc.code, "message": exc.message, "details": exc.details}
    if isinstance(exc, socket.gaierror):
        code, message = "DNS_ERROR", "运行环境无法解析邮箱域名。"
    elif isinstance(exc, ssl.SSLCertVerificationError):
        code, message = "TLS_ERROR", "邮箱证书校验失败；请检查运行环境的 CA、系统时间和证书链。"
    elif isinstance(exc, ssl.SSLError):
        code, message = "TLS_ERROR", "邮箱 TLS 握手失败；证书校验保持开启。"
    elif isinstance(exc, TimeoutError):
        code, message = "CONNECTION_TIMEOUT", "邮箱连接或读取超时；请检查运行环境到邮箱端口的连通性。"
    elif isinstance(exc, ConnectionRefusedError):
        code, message = "CONNECTION_REFUSED", "邮箱端口连接被拒绝；请检查端点、端口及服务策略。"
    elif isinstance(exc, PermissionError):
        code, message = "PERMISSION_DENIED", "运行环境拒绝了操作；连接阶段请检查网络出站权限。"
    elif isinstance(exc, imaplib.IMAP4.abort):
        code, message = "CONNECTION_FAILED", "IMAP 会话被中断；这不能直接判定为密码错误。"
    else:
        code, message = "CONNECTION_FAILED", "邮箱网络连接失败；请查看诊断阶段及系统错误编号。"
    details = {"stage": stage, "error_type": type(exc).__name__}
    for name in ("errno", "winerror", "verify_code"):
        number = getattr(exc, name, None)
        if isinstance(number, int):
            details[name] = number
    return {"code": code, "message": message, "details": details}


def diagnose_imap_connection(
    host: str = "mail.xjtlu.edu.cn", port: int = 993,
    security: str = "ssl", timeout: float = 5, proxy_mode: str = "direct",
) -> dict:
    """Check the caller's runtime, never authenticate or read mailbox contents."""
    timeout = max(1, min(float(timeout), 10))
    result = {
        "ok": False,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": {"host": host, "port": port, "security": security},
        "runtime": {"os": platform.system(), "python": platform.python_version()},
        "execution_location": "运行此诊断的 Python／MCP 服务所在环境，不一定是打开网页的电脑",
        "credentials_used": False,
        "account_authenticated": False,
        "message_bodies_read": False,
        "checks": {"dns": False, "tcp": False, "tls": False, "imap": False},
        "note": "通过仅证明网络和 IMAP 服务可达；不证明账号认证或同步成功。",
        "proxy_mode": proxy_mode,
    }
    stage = "DNS_LOOKUP"
    try:
        proxy = imap_proxy(host, port, proxy_mode)
        result["connection_route"] = "configured_http_proxy" if proxy else "direct"
        try:
            socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            result["checks"]["dns"] = True
        except socket.gaierror:
            if proxy is None:
                raise
            result["dns_resolution"] = "delegated_to_proxy"
        context = ssl.create_default_context()
        if security == "ssl":
            stage = "PROXY_CONNECT" if proxy else "TCP_CONNECT"
            with open_imap_socket(host, port, timeout, proxy) as raw:
                result["checks"]["tcp"] = True
                stage = "TLS_HANDSHAKE"
                with context.wrap_socket(raw, server_hostname=host) as secure:
                    result["checks"]["tls"] = True
                    result["tls_version"] = secure.version()
                    stage = "IMAP_GREETING"
                    greeting = secure.recv(1024)
                    if not greeting.startswith((b"* OK", b"* PREAUTH")):
                        result["error"] = {
                            "code": "IMAP_PROTOCOL_ERROR",
                            "message": "连接已建立，但服务没有返回 IMAP 就绪标志。",
                            "details": {"stage": stage},
                        }
                        return result
                    result["checks"]["imap"] = True
        elif security == "starttls":
            stage = "IMAP_CONNECT"
            client = (
                ProxiedIMAP4(host, port, proxy=proxy, timeout=timeout)
                if proxy else imaplib.IMAP4(host, port, timeout=timeout)
            )
            try:
                result["checks"]["tcp"] = True
                result["checks"]["imap"] = True
                stage = "STARTTLS_HANDSHAKE"
                client.starttls(ssl_context=context)
                result["checks"]["tls"] = True
            finally:
                try:
                    client.logout()
                except Exception:
                    pass
        else:
            result["error"] = {
                "code": "CONFIG_ERROR", "message": "诊断只支持 ssl 或 starttls。",
                "details": {"stage": "CONFIG"},
            }
            return result
        result["ok"] = True
    except Exception as exc:
        result["error"] = network_error(exc, stage)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="IMAP 网络诊断：不登录、不读取邮件、不需要密码")
    parser.add_argument("--timeout", type=float, default=5)
    parser.add_argument("--proxy-mode", choices=["direct", "environment"], default="direct")
    parser.add_argument("--output", default="imap-diagnostic-report.json")
    args = parser.parse_args(argv)
    report = diagnose_imap_connection(timeout=args.timeout, proxy_mode=args.proxy_mode)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    try:
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    except OSError:
        print("诊断已完成，但报告文件无法保存；可复制上方 JSON。", file=sys.stderr)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
