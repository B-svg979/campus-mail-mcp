import json
import os
import stat
import threading

from dotenv import dotenv_values

from campus_mail_mcp.cli import main


def test_init_generates_private_config_without_printing_token(tmp_path, capsys):
    path = tmp_path / "local.env"
    assert main(["--env-file", str(path), "init"]) == 0
    output = capsys.readouterr().out
    values = dotenv_values(path)
    assert len(values["CAMPUS_TOKEN"]) >= 32
    assert values["CAMPUS_TOKEN"] not in output
    if os.name == "posix":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    original = path.read_bytes()
    assert main(["--env-file", str(path), "init"]) == 1
    assert path.read_bytes() == original
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "CONFIG_EXISTS"


def test_missing_mail_credentials_has_safe_error(tmp_path, capsys, monkeypatch):
    for name in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_ADDRESS", "CAMPUS_MODE"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "local.env"
    assert main(["--env-file", str(path), "init", "--mode", "ews"]) == 0
    capsys.readouterr()
    assert main(["--env-file", str(path), "test-connection"]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "AUTH_REQUIRED"


def test_stdio_startup_error_does_not_pollute_protocol(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CAMPUS_MODE", "invalid-mode")
    assert main(["--env-file", str(tmp_path / "missing.env"), "serve", "--transport", "stdio"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["error"]["code"] == "CONFIG_ERROR"


def test_stdio_initializes_and_reports_syncing_while_first_collection_is_blocked(
    tmp_path, capsys, monkeypatch
):
    from campus_mail_mcp import providers, server

    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    for name in ("MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_ADDRESS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CAMPUS_MODE", "demo")
    monkeypatch.setenv("CAMPUS_DATA_DIR", str(tmp_path / "data"))

    def slow_collect(settings):
        started.set()
        if not release.wait(5):
            raise TimeoutError("first collection still blocked")
        try:
            return providers.demo_snapshot(settings)
        finally:
            finished.set()

    class Server:
        def __init__(self, service):
            self.service = service

        def run(self, transport):
            assert transport == "stdio"
            assert started.wait(1)
            assert not finished.is_set()
            assert self.service.get_mail_status()["data"]["status"] == "SYNCING"
            release.set()

    monkeypatch.setattr(providers, "collect", slow_collect)
    monkeypatch.setattr(server, "create_mcp", Server)
    try:
        assert main(["--env-file", str(tmp_path / "missing.env"),
                     "serve", "--transport", "stdio"]) == 0
        assert finished.wait(1)
        assert capsys.readouterr().out == ""
    finally:
        release.set()
