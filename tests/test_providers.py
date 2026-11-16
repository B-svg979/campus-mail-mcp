from datetime import datetime, timedelta
from email.message import EmailMessage
from types import SimpleNamespace

import pytest

from campus_mail_mcp import providers
from campus_mail_mcp.config import Settings
from campus_mail_mcp.content import UTC


def test_imap_uses_readonly_uid_peek_and_verified_tls(monkeypatch, tmp_path):
    now = datetime.now(UTC) - timedelta(hours=1)
    message = EmailMessage()
    message["Subject"] = "学校邮件"
    message.set_content("请阅读通知。")
    raw = message.as_bytes()
    calls = []
    month = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()[now.month - 1]
    date = f"{now.day:02}-{month}-{now.year} {now:%H:%M:%S} +0000"

    class FakeIMAP:
        def __init__(self, *args, **kwargs):
            assert kwargs["ssl_context"].check_hostname
            assert kwargs["ssl_context"].verify_mode == 2

        def login(self, *args):
            calls.append("login")

        def select(self, folder, readonly=False):
            assert readonly is True
            calls.append("EXAMINE")
            return "OK", [b"1"]

        def response(self, name):
            assert name == "UIDVALIDITY"
            return name, [b"99"]

        def uid(self, command, *args):
            calls.append((command, args))
            if command == "SEARCH":
                return "OK", [b"7"]
            if args[1] == "(RFC822.SIZE)":
                return "OK", [f"1 (UID 7 RFC822.SIZE {len(raw)})".encode()]
            assert args[1] == "(UID FLAGS INTERNALDATE BODY.PEEK[])"
            return "OK", [
                (f'1 (UID 7 FLAGS () INTERNALDATE "{date}" BODY[] {{{len(raw)}}}'.encode(), raw),
                b")",
            ]

        def logout(self):
            calls.append("logout")

    monkeypatch.setattr(providers.imaplib, "IMAP4_SSL", FakeIMAP)
    settings = Settings(mode="imap", username="student", password="local-secret", data_dir=tmp_path)
    snapshot = providers.collect(settings)
    assert snapshot.complete
    assert snapshot.mails[0].subject == "学校邮件"
    assert snapshot.mails[0].is_read is False
    assert calls[-1] == "logout"
    assert all(not isinstance(c, tuple) or c[0] not in {"STORE", "EXPUNGE", "COPY"} for c in calls)


def test_ews_reads_inbox_without_writes(monkeypatch, tmp_path):
    from exchangelib import FileAttachment

    calls = []
    now = datetime.now(UTC) - timedelta(minutes=1)
    item = SimpleNamespace(
        id="ews-item",
        message_id="<one@example.org>",
        subject="Exchange notice",
        sender=SimpleNamespace(email_address="teacher@example.org"),
        to_recipients=[],
        datetime_received=now,
        text_body="deadline evidence",
        body=None,
        is_read=False,
        size=100,
        attachments=[
            FileAttachment(name="note.txt", content_type="text/plain", size=4, content=b"note")
        ],
    )

    class Query:
        def filter(self, **kwargs):
            calls.append("filter")
            assert "datetime_received__gte" in kwargs
            return self

        def only(self, *fields):
            assert "body" in fields and "is_read" in fields
            return self

        def order_by(self, field):
            assert field == "-datetime_received"
            return self

        def __getitem__(self, selection):
            return [item][selection]

    monkeypatch.setattr(providers, "_ews", lambda settings: SimpleNamespace(inbox=Query()))
    settings = Settings(
        mode="ews",
        data_dir=tmp_path,
        username="local",
        password="secret",
        address="local@example.org",
    )
    snapshot = providers.collect(settings)
    assert snapshot.complete
    assert snapshot.mails[0].attachments[0].content == b"note"
    assert item.is_read is False
    assert calls == ["filter"]


def test_eml_import_is_explicitly_partial_and_skips_symlinks(tmp_path):
    folder = tmp_path / "imports"
    folder.mkdir()
    message = EmailMessage()
    message["Subject"] = "Import"
    message.set_content("imported")
    (folder / "one.eml").write_bytes(message.as_bytes())
    try:
        (folder / "link.eml").symlink_to(folder / "one.eml")
    except (OSError, NotImplementedError):
        pytest.skip("This runtime does not permit creating symlinks")
    settings = Settings(mode="eml", data_dir=tmp_path / "data", eml_dir=folder)
    snapshot = providers.collect(settings)
    assert not snapshot.complete
    assert len(snapshot.mails) == 1
    assert any("UNKNOWN_DATE" in warning for warning in snapshot.warnings)
