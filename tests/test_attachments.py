import io
import zipfile
from email.message import EmailMessage

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from campus_mail_mcp.config import MailError, Settings
from campus_mail_mcp.content import extract_attachment, identifier, parse_mime


def pdf_bytes(encrypted=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        }
    )
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 200 Td (Deadline: 2026-11-13) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("local-test-password")
    result = io.BytesIO()
    writer.write(result)
    return result.getvalue()


def test_pdf_text_and_page_evidence():
    parsed = extract_attachment(pdf_bytes(), "notice.pdf", "application/pdf")
    assert parsed["page_count"] == 1
    assert parsed["pages"][0]["page"] == 1
    assert "Deadline: 2026-11-13" in parsed["text"]
    assert not parsed["truncated"]


def test_encrypted_pdf_is_explicit_error():
    with pytest.raises(MailError) as error:
        extract_attachment(pdf_bytes(True), "notice.pdf", "application/pdf")
    assert error.value.code == "ENCRYPTED_ATTACHMENT"


def test_docx_plain_text():
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as archive:
        archive.writestr(
            "word/document.xml",
            (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                "<w:body><w:p><w:r><w:t>提交截止：11月13日</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
    parsed = extract_attachment(result.getvalue(), "notice.docx", "application/octet-stream")
    assert "提交截止：11月13日" in parsed["text"]
    assert parsed["pages"] == []


def test_large_attachment_and_unsupported_format_are_not_silent(tmp_path):
    message = EmailMessage()
    message.set_content("body")
    message.add_attachment(
        b"x" * 100, maintype="application", subtype="octet-stream", filename="huge.bin"
    )
    mail = parse_mime(
        message.as_bytes(),
        identifier("large"),
        Settings(data_dir=tmp_path, max_attachment_bytes=10),
    )
    assert mail.attachments[0].content is None
    assert mail.attachments[0].unavailable_reason == "SIZE_LIMIT"
    with pytest.raises(MailError) as error:
        extract_attachment(b"not executable", "program.exe", "application/octet-stream")
    assert error.value.code == "UNSUPPORTED_ATTACHMENT"
