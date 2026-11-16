import imaplib
import json
import socket
import ssl

import pytest

from campus_mail_mcp import diagnostics
from campus_mail_mcp.config import Settings
from campus_mail_mcp.service import MailService, safe_error


@pytest.mark.parametrize("error,code", [
    (socket.gaierror(-2, "private-server-text password=secret"), "DNS_ERROR"),
    (TimeoutError("private-server-text password=secret"), "CONNECTION_TIMEOUT"),
    (ConnectionRefusedError(61, "private-server-text password=secret"), "CONNECTION_REFUSED"),
    (PermissionError(1, "private-server-text password=secret"), "PERMISSION_DENIED"),
    (ssl.SSLCertVerificationError(1, "private-server-text password=secret"), "TLS_ERROR"),
    (imaplib.IMAP4.abort("private-server-text password=secret"), "CONNECTION_FAILED"),
])
def test_errors_are_specific_and_do_not_expose_remote_exception_text(error, code):
    safe = safe_error(error)
    assert safe.code == code
    assert safe.details["error_type"] == type(error).__name__
    assert "secret" not in json.dumps(safe.as_dict())
    assert "private-server-text" not in json.dumps(safe.as_dict())


def test_network_diagnosis_uses_verified_tls_and_never_logs_in(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET,)])
    calls = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def version(self):
            return "TLSv1.2"

        def recv(self, count):
            assert count == 1024
            calls.append("greeting_only")
            return b"* OK IMAP ready\r\n"

    class Context:
        def wrap_socket(self, raw, server_hostname):
            assert server_hostname == "mail.xjtlu.edu.cn"
            calls.append("verified_tls")
            return Connection()

    def context():
        real = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        assert real.check_hostname and real.verify_mode == ssl.CERT_REQUIRED
        return Context()

    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: Connection())
    monkeypatch.setattr(ssl, "create_default_context", context)
    result = diagnostics.diagnose_imap_connection()
    assert result["ok"] and all(result["checks"].values())
    assert calls == ["verified_tls", "greeting_only"]
    assert result["credentials_used"] is False
    assert result["account_authenticated"] is False
    assert result["message_bodies_read"] is False


def test_network_diagnosis_preserves_dns_failure_stage(monkeypatch):
    def fail(*args, **kwargs):
        raise socket.gaierror(-2, "sensitive-exception-text")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    result = diagnostics.diagnose_imap_connection()
    assert not result["ok"]
    assert result["error"]["code"] == "DNS_ERROR"
    assert result["error"]["details"]["stage"] == "DNS_LOOKUP"
    assert not any(result["checks"].values())
    assert "sensitive-exception-text" not in json.dumps(result)


def test_status_diagnosis_is_opt_in_and_independent_of_mailbox_credentials(tmp_path, monkeypatch):
    calls = []
    module = __import__("campus_mail_mcp.service", fromlist=["diagnose_imap_connection"])

    def probe(*args):
        calls.append(args)
        return {"ok": True, "credentials_used": False, "account_authenticated": False}

    monkeypatch.setattr(module, "diagnose_imap_connection", probe)
    service = MailService(Settings(mode="imap", data_dir=tmp_path))
    assert service.sync()["error"]["code"] == "AUTH_REQUIRED"
    assert "connection_diagnostics" not in service.get_mail_status()["data"]
    assert not calls
    status = service.get_mail_status(diagnose_connection=True)
    assert status["data"]["status"] == "AUTH_REQUIRED"
    assert status["data"]["connection_diagnostics"]["ok"]
    assert calls == [("mail.xjtlu.edu.cn", 993, "ssl", 10)]


def test_sync_keeps_safe_system_error_details(tmp_path):
    def fail(settings):
        raise ConnectionRefusedError(61, "sensitive-exception-text")

    service = MailService(Settings(data_dir=tmp_path), collector=fail)
    assert not service.sync()["ok"]
    error = service.get_mail_status()["meta"]["latest_error"]
    assert error["code"] == "CONNECTION_REFUSED"
    assert error["details"]["errno"] == 61
    assert "sensitive-exception-text" not in json.dumps(error)
