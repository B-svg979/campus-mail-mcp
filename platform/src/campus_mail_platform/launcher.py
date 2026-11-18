"""Platform STDIO entry point. Contains no mailbox credentials or mail data."""
import hashlib
import os
import secrets
import sys
import tempfile
from pathlib import Path


def main():
    mode = os.environ.get("XIPU_MAIL_MODE") or "demo"
    if mode not in ("demo", "imap"):
        raise SystemExit("XIPU_MAIL_MODE must be demo or imap")
    cfg = {
        "CAMPUS_MODE": mode,
        "MAIL_USERNAME": os.environ.get("XIPU_MAIL_USERNAME", ""),
        "MAIL_PASSWORD": os.environ.get("XIPU_MAIL_PASSWORD", ""),
        "MAIL_IMAP_HOST": "mail.xjtlu.edu.cn",
        "MAIL_IMAP_PORT": "993",
        "MAIL_IMAP_SECURITY": "ssl",
        "MAIL_IMAP_PROXY_MODE": "environment",
        "MAIL_IMAP_AUTH": "password",
        "MAIL_IMAP_FOLDER": "INBOX",
        "CAMPUS_LOOKBACK_DAYS": os.environ.get("XIPU_MAIL_DAYS") or "7",
        "CAMPUS_MAX_MESSAGES": os.environ.get("XIPU_MAIL_LIMIT") or "50",
        "CAMPUS_SYNC_SECONDS": "900",
        "CAMPUS_INITIAL_SYNC_WAIT_SECONDS": "60",
        "CAMPUS_TIMEZONE": "Asia/Shanghai",
        "CAMPUS_TOKEN": secrets.token_urlsafe(36),
    }
    # Avoid importing unrelated platform MAIL_* settings or a shared .env file.
    for key in tuple(os.environ):
        if key.startswith(("CAMPUS_", "MAIL_")):
            os.environ.pop(key)
    wheels = list(Path(__file__).parent.glob("campus_mail_mcp-*-py3-none-any.whl"))
    if len(wheels) != 1:
        raise SystemExit("Tool package must contain exactly one core wheel")
    wheel = wheels[0]
    expected = Path(__file__).with_name("wheel.sha256").read_text().strip()
    if hashlib.sha256(wheel.read_bytes()).hexdigest() != expected:
        raise SystemExit("Tool package checksum mismatch")
    sys.path.insert(0, str(wheel))
    os.umask(0o077)
    with tempfile.TemporaryDirectory(prefix="campus-mail-mcp-") as root:
        cfg["CAMPUS_DATA_DIR"] = str(Path(root) / "data")
        os.environ.update(cfg)
        from campus_mail_mcp.cli import main as mail_main
        return mail_main(["--env-file", os.devnull, "serve", "--transport", "stdio"])


if __name__ == "__main__":
    raise SystemExit(main())
