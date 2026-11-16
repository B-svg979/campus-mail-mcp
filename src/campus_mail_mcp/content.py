from __future__ import annotations

import hashlib
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from xml.etree import ElementTree

from bs4 import BeautifulSoup

from .config import MailError, Settings

UTC = timezone.utc


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def identifier(*values: str) -> str:
    return hashlib.sha256("\x00".join(values).encode()).hexdigest()[:32]


def html_text(value: str) -> str:
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "noscript", "iframe", "object", "svg"]):
        tag.decompose()
    return clean_text(soup.get_text("\n", strip=True))


def clean_text(value: str) -> str:
    # Keep quotes and evidence; remove NUL and control characters, not content.
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    return re.sub(r"\n{4,}", "\n\n\n", value.replace("\r\n", "\n")).strip()


@dataclass
class Attachment:
    id: str
    filename: str
    content_type: str
    size: int
    content: bytes | None = None
    unavailable_reason: str | None = None


@dataclass
class Mail:
    id: str
    subject: str
    sender: str
    recipients: list[str]
    received_at: str | None
    body_text: str
    message_id: str = ""
    folder: str = "INBOX"
    is_read: bool | None = None
    body_truncated: bool = False
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class Snapshot:
    mails: list[Mail]
    coverage_from: str
    coverage_to: str
    complete: bool = True
    warnings: list[str] = field(default_factory=list)


def parse_mime(
    raw: bytes, mail_id: str, settings: Settings, received: datetime | None = None
) -> Mail:
    message = BytesParser(policy=policy.default).parsebytes(raw)
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        try:
            content = body.get_content()
        except (LookupError, UnicodeError):
            content = (body.get_payload(decode=True) or b"").decode("utf-8", errors="replace")
        if isinstance(content, str):
            text = (
                html_text(content)
                if body.get_content_type() == "text/html"
                else clean_text(content)
            )
    if received is None and message.get("Date"):
        try:
            received = parsedate_to_datetime(str(message["Date"]))
            if received.tzinfo is None:
                received = None  # Do not invent a timezone for imported messages.
        except (TypeError, ValueError, OverflowError):
            pass
    result = Mail(
        id=mail_id,
        subject=clean_text(str(message.get("Subject", "(无主题)"))),
        sender=clean_text(str(message.get("From", ""))),
        recipients=[a for _, a in getaddresses([str(message.get("To", ""))])],
        received_at=utc_text(received) if received else None,
        message_id=str(message.get("Message-ID", "")),
        body_text=text[: settings.max_body_chars],
        body_truncated=len(text) > settings.max_body_chars,
    )
    for index, part in enumerate(message.iter_attachments()):
        data = part.get_payload(decode=True)
        if data is None and part.get_content_type() == "message/rfc822":
            data = part.as_bytes()
        data = data or b""
        filename = clean_text(part.get_filename() or f"attachment-{index + 1}")
        too_large = len(data) > settings.max_attachment_bytes
        result.attachments.append(
            Attachment(
                id=identifier(mail_id, str(index), filename),
                filename=filename,
                content_type=part.get_content_type(),
                size=len(data),
                content=None if too_large else data,
                unavailable_reason="SIZE_LIMIT" if too_large else None,
            )
        )
    return result


def extract_attachment(data: bytes, filename: str, content_type: str) -> dict:
    """Return bounded plain text. Never execute files or load external resources."""
    suffix = filename.lower().rsplit(".", 1)[-1]
    if suffix == "pdf" or content_type == "application/pdf":
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise MailError("ENCRYPTED_ATTACHMENT", "加密 PDF 需要先在本机解密。")
            page_count = len(reader.pages)
            pages, total_chars = [], 0
            for index, page in enumerate(reader.pages):
                if index >= 50 or total_chars >= 200000:
                    break
                text = clean_text(page.extract_text() or "")
                remaining = 200000 - total_chars
                pages.append({"page": index + 1, "text": text[:remaining]})
                total_chars += len(text)
            truncated = len(pages) < page_count or total_chars > 200000
            return {
                "format": "pdf",
                "pages": pages,
                "page_count": page_count,
                "truncated": truncated,
                "text": "\n\n".join(f"[第 {p['page']} 页]\n{p['text']}" for p in pages),
            }
        except MailError:
            raise
        except Exception as exc:
            raise MailError("PARSE_FAILED", "PDF 无法解析；此版本不含 OCR。") from exc
    if suffix == "docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                info = archive.getinfo("word/document.xml")
                if info.file_size > 8 * 1024 * 1024:
                    raise MailError("SIZE_LIMIT", "DOCX 解压后的正文超过限制。")
                xml = archive.read(info)
            if b"<!DOCTYPE" in xml.upper() or b"<!ENTITY" in xml.upper():
                raise MailError("UNSUPPORTED_ATTACHMENT", "不支持包含实体声明的文档。")
            root = ElementTree.fromstring(xml)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            text = "\n".join("".join(p.itertext()) for p in root.iter(f"{ns}p"))
            return {
                "format": "docx",
                "text": clean_text(text)[:200000],
                "truncated": len(text) > 200000,
                "pages": [],
            }
        except MailError:
            raise
        except Exception as exc:
            raise MailError("PARSE_FAILED", "DOCX 无法解析。") from exc
    if suffix in {"txt", "csv", "md", "json", "html", "htm"} or content_type.startswith("text/"):
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            text = data.decode("utf-16", errors="replace")
        else:
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = data.decode("gb18030", errors="replace")
        text = (
            html_text(text)
            if suffix in {"html", "htm"} or content_type == "text/html"
            else clean_text(text)
        )
        return {
            "format": "text",
            "text": text[:200000],
            "truncated": len(text) > 200000,
            "pages": [],
        }
    raise MailError(
        "UNSUPPORTED_ATTACHMENT",
        "支持 TXT/CSV/Markdown/JSON/HTML、PDF、DOCX；不含 OCR、旧 DOC 或压缩包。",
    )
