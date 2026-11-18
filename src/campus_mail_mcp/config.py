from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from dotenv import dotenv_values


class MailError(Exception):
    """A safe, user-facing error. Never put remote exception text here."""

    def __init__(self, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details

    def as_dict(self) -> dict:
        result = {"code": self.code, "message": self.message}
        if self.details:
            result["details"] = self.details
        return result


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    token: str = ""
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_hosts: tuple[str, ...] = ("localhost:*", "127.0.0.1:*", "[::1]:*")
    allowed_origins: tuple[str, ...] = ()
    timezone: str = "Asia/Shanghai"
    sync_seconds: int = 900
    initial_sync_wait_seconds: int = 0
    lookback_days: int = 30
    max_messages: int = 200
    timeout_seconds: int = 20
    max_message_bytes: int = 10 * 1024 * 1024
    max_attachment_bytes: int = 5 * 1024 * 1024
    max_body_chars: int = 200000
    eml_dir: Path = Path("mail-import")
    username: str = ""
    password: str = ""
    address: str = ""
    ews_url: str = "https://mail.xjtlu.edu.cn/EWS/Exchange.asmx"
    ews_auth: str = "NTLM"
    imap_host: str = "mail.xjtlu.edu.cn"
    imap_port: int = 993
    imap_security: str = "ssl"
    imap_proxy_mode: str = "direct"
    imap_folder: str = "INBOX"
    imap_auth: str = "password"
    imap_access_token: str = ""

    @classmethod
    def load(cls, env_file: str | Path = ".env") -> Settings:
        # Explicit environment wins over .env. No implicit parent-directory search.
        values = {**dotenv_values(env_file, interpolate=False), **os.environ}

        def val(key, default=""):
            return str(values.get(key) or default)

        def integer(key, default, low, high):
            try:
                number = int(val(key, str(default)))
            except ValueError as exc:
                raise MailError("CONFIG_ERROR", f"{key} 必须是整数。") from exc
            if not low <= number <= high:
                raise MailError("CONFIG_ERROR", f"{key} 必须在 {low}–{high} 之间。")
            return number

        def items(key, default=""):
            return tuple(x.strip() for x in val(key, default).split(",") if x.strip())

        settings = cls(
            mode=val("CAMPUS_MODE", "demo"),
            token=val("CAMPUS_TOKEN"),
            data_dir=Path(val("CAMPUS_DATA_DIR", "./data")).expanduser().resolve(),
            host=val("CAMPUS_HOST", "127.0.0.1"),
            port=integer("CAMPUS_PORT", 8765, 1024, 65535),
            allowed_hosts=items("CAMPUS_ALLOWED_HOSTS", "localhost:*,127.0.0.1:*,[::1]:*"),
            allowed_origins=items("CAMPUS_ALLOWED_ORIGINS"),
            timezone=val("CAMPUS_TIMEZONE", "Asia/Shanghai"),
            sync_seconds=integer("CAMPUS_SYNC_SECONDS", 900, 60, 86400),
            initial_sync_wait_seconds=integer("CAMPUS_INITIAL_SYNC_WAIT_SECONDS", 0, 0, 120),
            lookback_days=integer("CAMPUS_LOOKBACK_DAYS", 30, 1, 365),
            max_messages=integer("CAMPUS_MAX_MESSAGES", 200, 1, 2000),
            timeout_seconds=integer("CAMPUS_TIMEOUT_SECONDS", 20, 3, 120),
            max_message_bytes=integer("CAMPUS_MAX_MESSAGE_BYTES", 10485760, 1024, 52428800),
            max_attachment_bytes=integer("CAMPUS_MAX_ATTACHMENT_BYTES", 5242880, 1024, 10485760),
            max_body_chars=integer("CAMPUS_MAX_BODY_CHARS", 200000, 1000, 1000000),
            eml_dir=Path(val("CAMPUS_EML_DIR", "./mail-import")).expanduser().resolve(),
            username=val("MAIL_USERNAME"),
            password=val("MAIL_PASSWORD"),
            address=val("MAIL_ADDRESS"),
            ews_url=val("MAIL_EWS_URL", cls.ews_url),
            ews_auth=val("MAIL_EWS_AUTH", "NTLM").upper(),
            imap_host=val("MAIL_IMAP_HOST", cls.imap_host),
            imap_port=integer("MAIL_IMAP_PORT", 993, 1, 65535),
            imap_security=val("MAIL_IMAP_SECURITY", "ssl"),
            imap_proxy_mode=val("MAIL_IMAP_PROXY_MODE", "direct").lower(),
            imap_folder=val("MAIL_IMAP_FOLDER", "INBOX"),
            imap_auth=val("MAIL_IMAP_AUTH", "password"),
            imap_access_token=val("MAIL_IMAP_ACCESS_TOKEN"),
        )
        settings.validate()
        return settings

    def validate(self):
        if self.mode not in {"demo", "ews", "imap", "eml"}:
            raise MailError("CONFIG_ERROR", "CAMPUS_MODE 只能是 demo / ews / imap / eml。")
        try:
            ZoneInfo(self.timezone)
        except (KeyError, ValueError) as exc:
            raise MailError("CONFIG_ERROR", "时区名称无效。") from exc
        if self.ews_auth not in {"NTLM", "BASIC"}:
            raise MailError("CONFIG_ERROR", "此版本的 EWS 支持 NTLM 或 BASIC；不含云端 OAuth。")
        parsed = urlsplit(self.ews_url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise MailError("CONFIG_ERROR", "EWS 必须使用不含凭据的 HTTPS 地址。")
        if self.imap_security not in {"ssl", "starttls"}:
            raise MailError("CONFIG_ERROR", "IMAP 只支持 ssl 或 starttls。")
        if self.imap_proxy_mode not in {"direct", "environment"}:
            raise MailError("CONFIG_ERROR", "MAIL_IMAP_PROXY_MODE 只能是 direct 或 environment。")
        if self.imap_auth not in {"password", "xoauth2"}:
            raise MailError("CONFIG_ERROR", "MAIL_IMAP_AUTH 必须是 password 或 xoauth2。")
        if any(c in self.imap_folder for c in ("\r", "\n", '"', "\\")):
            raise MailError("CONFIG_ERROR", "IMAP 文件夹不能包含控制符、引号或反斜线。")
        if "*" in self.allowed_hosts:
            raise MailError("CONFIG_ERROR", "请列出实际域名，不要使用全通配的 Host。")

    @property
    def source_key(self) -> str:
        identity = {
            "demo": "demo-v1",
            "ews": f"{self.ews_url}|{self.address.lower()}|{self.username.lower()}|INBOX",
            "imap": f"{self.imap_host}|{self.imap_port}|{self.username.lower()}|{self.imap_folder}",
            "eml": str(self.eml_dir.resolve()),
        }[self.mode]
        return hashlib.sha256(f"{self.mode}:{identity}".encode()).hexdigest()

    def require_mail_credentials(self):
        if self.mode == "ews" and not (self.username and self.password and self.address):
            raise MailError(
                "AUTH_REQUIRED", "请在工具运行环境配置邮箱用户名、密码和完整邮箱地址。"
            )
        if self.mode == "imap":
            secret = self.imap_access_token if self.imap_auth == "xoauth2" else self.password
            if not self.username or not secret:
                raise MailError("AUTH_REQUIRED", "请在工具运行环境配置 IMAP 用户名及密码/访问令牌。")
