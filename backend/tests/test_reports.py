from __future__ import annotations

import csv
import io

from sqlalchemy import select

from app.models import AuditEvent, Role
from app.services.reports import csv_safe
from tests.conftest import ApiClient, Tenant, login, upload
from tests.test_reviews import findings


def signed_off_report(
    tenant: Tenant,
    data: bytes | None = None,
    filename: str = "policy.txt",
    mime: str = "text/plain",
    title: str = "Synthetic policy",
) -> tuple[ApiClient, dict]:  # type: ignore[type-arg]
    reviewer = login(tenant.users[Role.REVIEWER])
    doc = upload(reviewer, data, filename, mime, title=title).json()
    review = reviewer.post(
        "/api/reviews",
        json={
            "title": "Report review",
            "document_version_id": doc["latest_version"]["id"],
            "checklist_version_id": str(tenant.checklist_version.id),
        },
    ).json()  # type: ignore[union-attr]
    for f in findings(reviewer, review["id"]):
        rationale = (
            '=HYPERLINK("http://evil.example")'
            if f["requirement_code"] == "DEMO-05"
            else "Confirmed in review."
        )
        reviewer.post(
            f"/api/findings/{f['id']}/decision",
            json={"decision": "confirmed", "rationale": rationale},
        )
    report = reviewer.post(f"/api/reviews/{review['id']}/signoff").json()
    return reviewer, report


def test_html_report_contents(tenant_a: Tenant) -> None:
    client, report = signed_off_report(tenant_a)
    r = client.get(f"/api/reports/{report['id']}/export", params={"format": "html"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    html = r.text
    for expected in (
        "Org a",
        "Report review",
        "version 1",
        "Test checklist",
        "deterministic",
        "Paragraph",
        "100% secure",
        "Limitations",
        "does not certify legal or regulatory compliance",
        "reviewer a",
    ):
        assert expected in html, expected
    assert "storage" not in html.lower()
    assert "default-src 'none'" in r.headers["content-security-policy"]


def test_html_report_escapes_document_text(tenant_a: Tenant) -> None:
    client, report = signed_off_report(tenant_a, title="<script>alert(1)</script>")
    html = client.get(f"/api/reports/{report['id']}/export", params={"format": "html"}).text
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_pdf_report_has_page_references(tenant_a: Tenant) -> None:
    from pypdf import PdfReader

    from app import demo_content as dc

    client, report = signed_off_report(tenant_a, dc.policy_pdf_bytes(), "p.pdf", "application/pdf")
    r = client.get(f"/api/reports/{report['id']}/export", params={"format": "pdf"})
    assert r.status_code == 200 and r.content.startswith(b"%PDF-")
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    assert "Page 2" in text and "not certify" in text


def test_csv_export_neutralises_formulas(tenant_a: Tenant, db) -> None:  # type: ignore[no-untyped-def]
    client, report = signed_off_report(tenant_a)
    r = client.get(f"/api/reports/{report['id']}/export", params={"format": "csv"})
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert len(rows) == 3
    rationale = next(
        row["decision_rationale"] for row in rows if row["requirement_code"] == "DEMO-05"
    )
    assert rationale.startswith("'=")
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "report.exported"))


def test_csv_safe() -> None:
    for bad in ("=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"):
        assert csv_safe(bad).startswith("'")
    assert csv_safe("normal") == "normal" and csv_safe(None) == ""


def test_viewer_can_export_but_not_sign_off(tenant_a: Tenant) -> None:
    _, report = signed_off_report(tenant_a)
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.get("/api/reports").json()["total"] == 1
    assert (
        viewer.get(f"/api/reports/{report['id']}/export", params={"format": "csv"}).status_code
        == 200
    )
    assert viewer.post(f"/api/reviews/{report['review_id']}/signoff").status_code == 403


def test_unknown_format_rejected(tenant_a: Tenant) -> None:
    client, report = signed_off_report(tenant_a)
    assert (
        client.get(f"/api/reports/{report['id']}/export", params={"format": "xlsx"}).status_code
        == 422
    )
