from dataclasses import replace
from datetime import datetime, timedelta
from email.message import EmailMessage

import pytest

from campus_mail_mcp.config import MailError, Settings
from campus_mail_mcp.content import UTC, Mail, Snapshot, identifier, parse_mime, utc_text
from campus_mail_mcp.service import MailService, date_bound


@pytest.fixture
def service(tmp_path):
    settings = Settings(data_dir=tmp_path, token="a" * 48)
    result = MailService(settings)
    assert result.sync()["ok"]
    return result


def test_demo_end_to_end_and_attachment(service):
    status = service.get_mail_status()
    assert status["meta"]["is_demo"] is True
    assert status["data"]["cached_message_count"] == 6
    search = service.search_mail("活动 报名")
    assert len(search["data"]["items"]) == 1
    mail = service.get_mail(search["data"]["items"][0]["id"])["data"]
    result = service.read_attachment(mail["id"], mail["attachments"][0]["id"])
    assert result["ok"]
    assert "报名截止" in result["data"]["body"]["text"]
    assert result["meta"]["is_demo"]


def test_signed_pagination_and_snapshot_change(service):
    page = service.search_mail(limit=2)["data"]
    assert page["has_more"]
    second = service.search_mail(limit=2, cursor=page["next_cursor"])
    assert second["ok"]
    assert not set(x["id"] for x in page["items"]) & set(x["id"] for x in second["data"]["items"])
    invalid = service.search_mail(query="different", limit=2, cursor=page["next_cursor"])
    assert invalid["error"]["code"] == "INVALID_CURSOR"
    assert service.sync()["ok"]
    expired = service.search_mail(limit=2, cursor=page["next_cursor"])
    assert expired["error"]["code"] == "CURSOR_EXPIRED"
    assert service.search_mail(cursor="not-a-valid-cursor")["error"]["code"] == "INVALID_CURSOR"


def test_failed_sync_retains_cache_and_reports_staleness(service):
    def fail(settings):
        raise MailError("AUTH_REQUIRED", "请重新认证。")

    service.collector = fail
    assert not service.sync()["ok"]
    result = service.search_mail()
    assert result["ok"] and result["data"]["total_in_cache"] == 6
    assert result["meta"]["stale"]
    assert result["meta"]["latest_error"]["code"] == "AUTH_REQUIRED"


def test_first_auth_failure_is_not_empty_mailbox(tmp_path):
    service = MailService(Settings(mode="imap", data_dir=tmp_path, token="a" * 48))
    assert not service.sync()["ok"]
    result = service.search_mail()
    assert not result["ok"]
    assert result["error"]["code"] == "AUTH_REQUIRED"


def test_cache_cannot_be_relabelled_as_another_account(service):
    with pytest.raises(MailError, match="绑定其他"):
        MailService(
            replace(service.settings, mode="ews", username="another", address="other@example.org")
        )


def test_timezone_date_bounds_and_range(service):
    assert date_bound("2026-11-09", "Asia/Shanghai") == "2026-11-08T16:00:00Z"
    assert date_bound("2026-11-09", "Asia/Shanghai", end=True) == "2026-11-09T16:00:00Z"
    assert not service.search_mail(start_date="2026-11-10", end_date="2026-11-09")["ok"]
    assert not service.search_mail(start_date="2026-11-09T09:00:00")["ok"]
    assert not service.search_mail(limit=100)["ok"]


def test_literal_search_and_body_chunking(service):
    now = datetime.now(UTC)
    text = "A_100% 报名\n" + "证据内容" * 1000
    mail = Mail(identifier("literal"), "literal", "sender@example.org", [], utc_text(now), text)
    service.store.replace(Snapshot([mail], utc_text(now - timedelta(days=1)), utc_text(now)))
    assert service.search_mail("100%")["data"]["total_in_cache"] == 1
    assert service.search_mail("100_")["data"]["total_in_cache"] == 0
    assert service.search_mail("' OR 1=1 --")["data"]["total_in_cache"] == 0
    first = service.get_mail(mail.id, max_chars=500)["data"]["body"]
    second = service.get_mail(mail.id, first["next_offset"], max_chars=500)["data"]["body"]
    assert first["text"] + second["text"] == text[:1000]
    assert not service.get_mail("../../.env")["ok"]


def test_html_and_mime_preserve_evidence_but_not_script(tmp_path):
    message = EmailMessage()
    message["Subject"] = "报名截止"
    message["From"] = "Example <teacher@example.org>"
    message["Date"] = "Mon, 09 Nov 2026 09:30:00 +0800"
    message.set_content("<p>截止：11 月 13 日</p><script>steal()</script>", subtype="html")
    message.add_attachment(
        b"attachment evidence", maintype="text", subtype="plain", filename="../../notes.txt"
    )
    settings = Settings(data_dir=tmp_path)
    mail = parse_mime(message.as_bytes(), identifier("mime"), settings)
    assert "11 月 13 日" in mail.body_text
    assert "steal" not in mail.body_text
    assert mail.received_at == "2026-11-09T01:30:00Z"
    assert mail.attachments[0].content == b"attachment evidence"
    assert not (tmp_path / "notes.txt").exists()


def test_missing_date_is_not_invented(tmp_path):
    message = EmailMessage()
    message.set_content("test")
    mail = parse_mime(message.as_bytes(), identifier("no-date"), Settings(data_dir=tmp_path))
    assert mail.received_at is None


def test_config_rejects_insecure_protocol_and_interpolation(tmp_path, monkeypatch):
    path = tmp_path / "test.env"
    path.write_text("MAIL_PASSWORD='${not_an_env_var} $(literal)'\nCAMPUS_MODE=imap\n")
    monkeypatch.delenv("MAIL_PASSWORD", raising=False)
    assert Settings.load(path).password == "${not_an_env_var} $(literal)"
    with pytest.raises(MailError):
        replace(Settings(), imap_security="plain").validate()
    with pytest.raises(MailError):
        replace(Settings(), ews_url="http://example.org/EWS").validate()
