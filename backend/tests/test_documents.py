from __future__ import annotations

import io
import zipfile

from sqlalchemy import select

from app import demo_content as dc
from app.models import AuditEvent, DocumentVersion, Role, SourceBlock
from app.storage import get_storage
from tests.conftest import Tenant, login, upload

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_upload_txt_extracts_paragraph_blocks(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, tags="synthetic, vendor")
    assert r.status_code == 201, r.text
    doc = client.get(f"/api/documents/{r.json()['id']}").json()
    v = doc["latest_version"]
    assert v["status"] == "ready"
    assert v["page_count"] is None  # never invent pages for TXT
    assert doc["tags"] == ["synthetic", "vendor"]
    blocks = client.get(f"/api/document-versions/{v['id']}/blocks").json()["items"]
    assert blocks[0]["ref"] == "para-1"
    assert all(b["page_number"] is None for b in blocks)
    assert any("Policy owner" in b["text"] for b in blocks)


def test_upload_pdf_keeps_page_numbers(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, dc.policy_pdf_bytes(), "policy.pdf", "application/pdf")
    v = client.get(f"/api/documents/{r.json()['id']}").json()["latest_version"]
    assert v["status"] == "ready" and v["page_count"] == 2
    blocks = client.get(f"/api/document-versions/{v['id']}/blocks").json()["items"]
    incident = next(b for b in blocks if "100% secure" in b["text"])
    assert incident["page_number"] == 2 and incident["ref"].startswith("p2.")
    assert all(b["paragraph_number"] is None for b in blocks)


def test_upload_docx_keeps_sections_and_arabic(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, dc.policy_docx_bytes(), "policy.docx", DOCX_MIME)
    v = client.get(f"/api/documents/{r.json()['id']}").json()["latest_version"]
    assert v["status"] == "ready"
    blocks = client.get(f"/api/document-versions/{v['id']}/blocks").json()["items"]
    retention = next(b for b in blocks if "Retention periods" in b["text"])
    assert retention["section_heading"] == "2. Data retention"
    assert retention["page_number"] is None
    assert any("مالك السياسة" in b["text"] for b in blocks)


def test_rejects_mismatched_signature_extension_and_mime(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    cases = [
        (b"not a pdf", "fake.pdf", "application/pdf", "PDF signature"),
        (b"MZ\x90\x00binary", "evil.exe", "application/octet-stream", "Unsupported"),
        (dc.policy_txt_bytes(), "policy.txt", "application/pdf", "declared type"),
        (b"PK\x03\x04garbage", "x.docx", DOCX_MIME, "corrupted"),
        (b"\x00\x01\x02", "bin.txt", "text/plain", "binary"),
        (b"", "empty.txt", "text/plain", "empty"),
    ]
    for data, name, mime, expected in cases:
        r = client.post(
            "/api/documents", data={"title": "x"}, files={"file": (name, data or b"", mime)}
        )
        assert r.status_code == 422, (name, r.text)
        assert expected.lower() in r.json()["detail"].lower(), (name, r.json())


def test_rejects_zip_that_is_not_docx(tenant_a: Tenant) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hi")
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, buf.getvalue(), "x.docx", DOCX_MIME)
    assert r.status_code == 422 and "not a Word document" in r.json()["detail"]


def test_upload_size_limit(tenant_a: Tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_upload_mb", 0)
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client)
    assert r.status_code == 413


def test_scanned_pdf_fails_with_useful_message_and_can_retry(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, dc.blank_pdf_bytes(), "scan.pdf", "application/pdf")
    doc = client.get(f"/api/documents/{r.json()['id']}").json()
    v = doc["latest_version"]
    assert v["status"] == "failed"
    assert "OCR is not enabled" in v["failure_message"]
    assert doc["latest_job"]["status"] == "failed"
    retry = client.post(f"/api/document-versions/{v['id']}/retry")
    assert retry.status_code == 200
    assert retry.json()["status"] == "failed"  # still no text; failure is permanent, not looped
    assert retry.json()["attempts"] == 1


def test_pdf_page_limit(tenant_a: Tenant, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import get_settings

    monkeypatch.setattr(get_settings(), "max_pdf_pages", 1)
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, dc.policy_pdf_bytes(), "policy.pdf", "application/pdf")
    v = client.get(f"/api/documents/{r.json()['id']}").json()["latest_version"]
    assert v["status"] == "failed" and "limit is 1" in v["failure_message"]


def test_blank_pages_produce_extraction_warning(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, dc.policy_pdf_bytes(blank_last_page=True), "p.pdf", "application/pdf")
    v = client.get(f"/api/documents/{r.json()['id']}").json()["latest_version"]
    assert v["status"] == "ready"
    assert any("page(s) 3" in w for w in v["extraction_warnings"])


def test_duplicate_detection_and_versions(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    first = upload(client).json()
    dup = upload(client)
    assert dup.status_code == 409
    assert dup.json()["duplicate_document_id"] == first["id"]
    # New version of the same document
    r = client.post(
        f"/api/documents/{first['id']}/versions",
        files={"file": ("v2.docx", dc.policy_docx_bytes(), DOCX_MIME)},
    )
    assert r.status_code == 201
    body = r.json()
    assert [v["version_number"] for v in body["versions"]] == [1, 2]
    assert body["latest_version"]["file_format"] == "docx"


def test_original_filename_is_metadata_only(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client = login(tenant_a.users[Role.ANALYST])
    r = upload(client, filename="../../etc/passwd.txt")
    v = db.scalar(select(DocumentVersion))
    assert v.original_filename == "passwd.txt"
    assert ".." not in v.storage_key and "passwd" not in v.storage_key
    assert "storage_key" not in r.text


def test_private_download_requires_auth_and_audits(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from app.main import app

    client = login(tenant_a.users[Role.VIEWER])
    writer = login(tenant_a.users[Role.ANALYST])
    v = upload(writer).json()["latest_version"]
    r = client.get(f"/api/document-versions/{v['id']}/download")
    assert r.status_code == 200 and r.content == dc.policy_txt_bytes()
    assert "attachment" in r.headers["content-disposition"]
    assert TestClient(app).get(f"/api/document-versions/{v['id']}/download").status_code == 401
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "document.downloaded"))


def test_search_extracted_text(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    upload(client, title="Doc one")
    upload(client, b"Nothing relevant here.\n", "other.txt", title="Doc two")
    hits = client.get("/api/documents", params={"q": "subcontractors"}).json()
    assert [d["title"] for d in hits["items"]] == ["Doc one"]
    assert client.get("/api/documents", params={"q": "zzz-none"}).json()["total"] == 0


def test_filter_by_latest_version_status(tenant_a: Tenant) -> None:
    client = login(tenant_a.users[Role.ANALYST])
    upload(client, title="Readable")
    upload(client, dc.blank_pdf_bytes(), "scan.pdf", "application/pdf", title="Scanned")
    ready = client.get("/api/documents", params={"status": "ready", "page_size": 100})
    assert ready.status_code == 200
    assert [d["title"] for d in ready.json()["items"]] == ["Readable"]
    failed = client.get("/api/documents", params={"status": "failed"}).json()
    assert [d["title"] for d in failed["items"]] == ["Scanned"]


def test_delete_removes_file_and_text_but_keeps_audit(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    writer = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    doc = upload(writer).json()
    key = db.scalar(select(DocumentVersion.storage_key))
    assert get_storage().exists(key)
    assert writer.delete(f"/api/documents/{doc['id']}").status_code == 403  # analyst can't
    assert reviewer.delete(f"/api/documents/{doc['id']}").status_code == 204
    assert not get_storage().exists(key)
    assert db.scalar(select(SourceBlock)) is None
    assert reviewer.get(f"/api/documents/{doc['id']}").status_code == 404
    assert reviewer.get("/api/documents").json()["total"] == 0
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "document.deleted"))


def test_cannot_delete_document_used_by_review(tenant_a: Tenant) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    doc = upload(reviewer).json()
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "R",
            "document_version_id": doc["latest_version"]["id"],
            "checklist_version_id": str(tenant_a.checklist_version.id),
        },
    )  # type: ignore[union-attr]
    assert r.status_code == 201
    d = reviewer.delete(f"/api/documents/{doc['id']}")
    assert d.status_code == 409 and "used by 1 review" in d.json()["detail"]
