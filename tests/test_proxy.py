import base64
import ipaddress
import json
import os
import select
import socket
import socketserver
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from campus_mail_mcp import diagnostics, providers
from campus_mail_mcp.config import Settings
from campus_mail_mcp.service import safe_error


@contextmanager
def running_server(handler):
    class Server(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    with Server(("127.0.0.1", 0), handler) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            worker.join(timeout=3)


@pytest.fixture
def mail_network(tmp_path, monkeypatch):
    for key in tuple(os.environ):
        if key.lower().endswith("_proxy"):
            monkeypatch.delenv(key)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "mail.school.test")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.DNSName("mail.school.test"), x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
        ]), critical=False).sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    trusted_context = ssl.create_default_context(cafile=str(cert_path))
    evidence = SimpleNamespace(commands=[], requests=[], encrypted=bytearray(), deny=False)

    class MailHandler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                with server_context.wrap_socket(self.request, server_side=True) as channel:
                    channel.settimeout(5)
                    channel.sendall(b"* OK test IMAP ready\r\n")
                    reader = channel.makefile("rb")
                    while line := reader.readline(8192):
                        tag, command, *_ = line.split()
                        evidence.commands.append(command)
                        if command == b"CAPABILITY":
                            channel.sendall(b"* CAPABILITY IMAP4rev1\r\n" + tag + b" OK ready\r\n")
                        elif command == b"LOGIN":
                            channel.sendall(tag + b" OK authenticated\r\n")
                        elif command == b"EXAMINE":
                            channel.sendall(b"* 0 EXISTS\r\n" + tag + b" OK [READ-ONLY] selected\r\n")
                        elif command == b"LOGOUT":
                            channel.sendall(b"* BYE done\r\n" + tag + b" OK logout\r\n")
                            break
                        else:
                            channel.sendall(tag + b" BAD unsupported\r\n")
            except (OSError, ssl.SSLError):
                pass  # A rejected test certificate closes before IMAP authentication.

    with running_server(MailHandler) as mail_port:
        class ProxyHandler(socketserver.StreamRequestHandler):
            def handle(self):
                request = [self.rfile.readline(8192)]
                while (line := self.rfile.readline(8192)) not in (b"\r\n", b"\n", b""):
                    request.append(line)
                evidence.requests.append(b"".join(request))
                if evidence.deny:
                    self.wfile.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
                    return
                with socket.create_connection(("127.0.0.1", mail_port), timeout=3) as upstream:
                    self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
                    deadline = time.monotonic() + 10
                    try:
                        while time.monotonic() < deadline:
                            readable, _, _ = select.select([self.request, upstream], [], [], 0.2)
                            for source in readable:
                                data = source.recv(65536)
                                if not data:
                                    return
                                evidence.encrypted.extend(data)
                                (upstream if source is self.request else self.request).sendall(data)
                    except (ConnectionResetError, BrokenPipeError):
                        return

        with running_server(ProxyHandler) as proxy_port:
            monkeypatch.setenv(
                "HTTPS_PROXY", f"http://proxy-user:proxy-password@127.0.0.1:{proxy_port}"
            )
            yield SimpleNamespace(
                evidence=evidence, context=trusted_context, mail_port=mail_port,
                proxy_port=proxy_port,
                settings=Settings(
                    mode="imap", imap_host="mail.school.test", imap_port=993,
                    imap_proxy_mode="environment", username="mail-user",
                    password="mail-password", timeout_seconds=3,
                ),
            )


def test_verified_tls_login_and_readonly_select_through_proxy(mail_network, monkeypatch):
    network = mail_network
    monkeypatch.setattr(providers.ssl, "create_default_context", lambda: network.context)
    client = providers._imap(network.settings)
    client.logout()
    assert network.evidence.commands == [b"CAPABILITY", b"LOGIN", b"EXAMINE", b"LOGOUT"]
    request = network.evidence.requests[0]
    assert request.startswith(b"CONNECT mail.school.test:993 HTTP/")
    encoded = base64.b64encode(b"proxy-user:proxy-password")
    assert b"Proxy-Authorization: Basic " + encoded in request
    assert b"mail-password" not in request + network.evidence.encrypted


def test_proxy_diagnosis_uses_same_route_without_mail_auth(mail_network, monkeypatch):
    network = mail_network
    monkeypatch.setattr(diagnostics.ssl, "create_default_context", lambda: network.context)
    original = socket.getaddrinfo

    def resolve(host, *args, **kwargs):
        if host == "mail.school.test":
            raise socket.gaierror(-2, "proxy must resolve the mailbox")
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    result = diagnostics.diagnose_imap_connection(proxy_mode="environment", host="mail.school.test")
    assert result["ok"] and result["checks"]["tls"] and result["checks"]["imap"]
    assert result["connection_route"] == "configured_http_proxy"
    assert result["dns_resolution"] == "delegated_to_proxy"
    assert not result["credentials_used"] and not network.evidence.commands
    assert "proxy-password" not in json.dumps(result)


def test_denied_proxy_never_falls_back_to_direct(mail_network, monkeypatch):
    network = mail_network
    network.evidence.deny = True
    original, destinations = socket.create_connection, []

    def connect(address, *args, **kwargs):
        destinations.append(address)
        return original(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", connect)
    with pytest.raises(diagnostics.ProxyError) as failure:
        providers._imap(network.settings)
    error = safe_error(failure.value).as_dict()
    assert error["code"] == "PROXY_FORBIDDEN" and error["details"]["http_status"] == 403
    assert destinations == [("127.0.0.1", network.proxy_port)]
    assert not network.evidence.commands
    assert "proxy-password" not in json.dumps(error)


@pytest.mark.parametrize("wrong_hostname", [False, True])
def test_proxy_does_not_bypass_certificate_checks(mail_network, monkeypatch, wrong_hostname):
    network = mail_network
    context = network.context if wrong_hostname else ssl.create_default_context()
    settings = replace(network.settings, imap_host="wrong.school.test") if wrong_hostname else network.settings
    monkeypatch.setattr(providers.ssl, "create_default_context", lambda: context)
    with pytest.raises(ssl.SSLCertVerificationError):
        providers._imap(settings)
    assert b"LOGIN" not in network.evidence.commands


@pytest.mark.parametrize("mode", ["direct", "environment"])
def test_direct_and_no_proxy_keep_local_connections_working(mail_network, monkeypatch, mode):
    network = mail_network
    network.evidence.deny = True
    monkeypatch.setenv("NO_PROXY", "localhost")
    monkeypatch.setattr(providers.ssl, "create_default_context", lambda: network.context)
    settings = replace(
        network.settings, imap_host="localhost", imap_port=network.mail_port, imap_proxy_mode=mode
    )
    client = providers._imap(settings)
    client.logout()
    assert not network.evidence.requests
    assert b"EXAMINE" in network.evidence.commands


def test_unsupported_proxy_configuration_is_safe_and_does_not_connect(monkeypatch):
    monkeypatch.setattr(diagnostics, "getproxies", lambda: {"https": "https://user:secret@proxy.test:443"})
    monkeypatch.setattr(diagnostics, "proxy_bypass", lambda _: False)
    with pytest.raises(diagnostics.ProxyError) as failure:
        diagnostics.imap_proxy("mail.school.test", 993, "environment")
    error = safe_error(failure.value).as_dict()
    assert error["code"] == "PROXY_CONFIG_ERROR"
    assert "secret" not in json.dumps(error) and "proxy.test" not in json.dumps(error)
