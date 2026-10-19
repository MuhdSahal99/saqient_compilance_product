"""Phase B: e-invoice store, validation reviews, go-live readiness and rejections.

Every invoice, schema and rule here is synthetic (app/demo_einvoice.py).
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app import demo_einvoice as demo
from app.einvoice import xmlsafe
from app.engine.einvoice_checks import invoice_hash, parse_tlv
from app.models import LegalEntity, Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_datasets import make_entity

XML = "application/xml"
ZIP = "application/zip"


# ---------------------------------------------------------------- helpers


def upload_batch(
    client: ApiClient,
    entity: LegalEntity,
    data: bytes,
    filename: str = "invoices.zip",
    mime: str = ZIP,
) -> Any:
    return client.post(
        "/api/einvoice-batches",
        data={"entity_id": str(entity.id), "name": "Synthetic batch"},
        files={"file": (filename, data, mime)},
    )


def synthetic_pack(admin: ApiClient, with_bundle: bool = True, jurisdiction: str = "AE") -> str:
    """A published synthetic pack with the e-invoice and VAT rules and the test schema."""
    r = admin.post(
        "/api/rule-packs", json={"name": "Synthetic e-invoice pack", "jurisdiction": jurisdiction}
    )
    assert r.status_code == 201, r.text
    vid = r.json()["versions"][0]["id"]
    put = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": demo.rules()})
    assert put.status_code == 200, put.text
    if with_bundle:
        f = admin.post(
            f"/api/rule-pack-versions/{vid}/files",
            data={
                "file_key": "syn.einvoice.xsd",
                "title": "Synthetic UBL-shaped schema",
                "entry_point": demo.XSD_ENTRY,
            },
            files={"file": ("schema.zip", demo.xsd_bundle(), ZIP)},
        )
        assert f.status_code == 201, f.text
    pub = admin.post(f"/api/rule-pack-versions/{vid}/publish")
    assert pub.status_code == 200, pub.text
    return str(vid)


def checklist(client: ApiClient, requirements: list[dict[str, Any]]) -> str:
    r = client.post(
        "/api/checklists",
        json={
            "name": "Synthetic e-invoice checks",
            "kind": "internal_policy",
            "requirements": requirements,
        },
    )
    assert r.status_code == 201, r.text
    pub = client.post(f"/api/checklist-versions/{r.json()['id']}/publish")
    assert pub.status_code == 200, pub.text
    return str(r.json()["id"])


def req(code: str, config: dict[str, Any], severity: str = "high") -> dict[str, Any]:
    return {
        "code": code,
        "title": f"Synthetic {code}",
        "severity": severity,
        "check_config": config,
    }


VALIDATE_AE = {
    "type": "einvoice_validate",
    "profile": "pint_ae",
    "rules_prefix": "syn.einvoice",
    "default_country": "AE",
}
VALIDATE_SA = {
    "type": "einvoice_validate",
    "profile": "zatca",
    "rules_prefix": "syn.einvoice",
    "default_country": "SA",
    "parts": ["mandatory", "qr", "chain", "duplicates"],
    "expect_complete_chain": True,
}


def results(client: ApiClient, review_id: str) -> dict[str, dict[str, Any]]:
    return {
        x["requirement_code"]: x for x in client.get(f"/api/reviews/{review_id}/results").json()
    }


def findings(client: ApiClient, review_id: str) -> list[dict[str, Any]]:
    r = client.get("/api/findings", params={"review_id": review_id, "page_size": 200})
    assert r.status_code == 200, r.text
    return r.json()["items"]  # type: ignore[no-any-return]


# ---------------------------------------------------------------- synthetic builders


def test_synthetic_builders_are_self_consistent() -> None:
    root = xmlsafe.parse_xml(demo.invoice_xml(demo.InvoiceSpec(number="X", uuid="u")))
    schema = xmlsafe.compile_schema(xmlsafe.read_bundle(demo.xsd_bundle()), demo.XSD_ENTRY)
    assert schema.validate(root)
    chain = demo.zatca_chain(3)
    roots = [xmlsafe.parse_xml(x) for _, x in chain]
    # Each PIH equals the previous invoice's recomputed hash.
    for prev, cur in zip(roots, roots[1:], strict=False):
        pih = cur.xpath(
            "cac:AdditionalDocumentReference[cbc:ID='PIH']/cac:Attachment/"
            "cbc:EmbeddedDocumentBinaryObject",
            namespaces={"cac": demo.CAC, "cbc": demo.CBC},
        )[0].text
        assert pih == invoice_hash(prev, demo.HASH_ENCODING)
    # The hash does not depend on the QR reference (it is excluded from C14N input).
    no_qr = xmlsafe.parse_xml(chain[0][1])
    qr = no_qr.xpath(
        "cac:AdditionalDocumentReference[cbc:ID='QR']",
        namespaces={"cac": demo.CAC, "cbc": demo.CBC},
    )[0]
    no_qr.remove(qr)
    assert invoice_hash(roots[0], "base64_digest") == invoice_hash(no_qr, "base64_digest")
    assert parse_tlv(bytes([1, 2]) + b"ab" + bytes([4, 1]) + b"9") == {1: b"ab", 4: b"9"}


# ---------------------------------------------------------------- upload


def test_upload_xml_and_zip_dedupes_and_records_parse_errors(tenant_a: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    one = demo.invoice_xml(demo.InvoiceSpec(number="SYN-1", uuid="u-1"))
    r = upload_batch(analyst, entity, one, "one.xml", XML)
    assert r.status_code == 201, r.text
    b = r.json()
    assert b["file_count"] == 1 and b["duplicate_count"] == 0
    f = b["files"][0]
    assert f["invoice_number"] == "SYN-1" and f["profile"] == "pint_ae"
    assert f["payable_amount"] == "262.5000" or f["payable_amount"] == "262.50"
    assert f["issue_date"] == "2026-03-15" and f["currency"] == "AED"

    two = demo.invoice_xml(demo.InvoiceSpec(number="SYN-2", uuid="u-2"))
    z = demo.zip_of(
        [
            ("a/one.xml", one),
            ("two.xml", two),
            ("broken.xml", b"<Invoice>"),
            ("__MACOSX/._two.xml", b"junk"),
        ]
    )
    r = upload_batch(analyst, entity, z)
    assert r.status_code == 201, r.text
    b = r.json()
    # one.xml was already stored for the entity; broken.xml is kept with its parse error.
    assert b["duplicate_count"] == 1 and b["file_count"] == 2 and b["failed_count"] == 1
    broken = next(x for x in b["files"] if x["filename"] == "broken.xml")
    assert broken["parse_error"]
    dl = analyst.get(f"/api/einvoice-files/{f['id']}/download")
    assert dl.status_code == 200 and dl.content == one
    assert dl.headers["x-content-type-options"] == "nosniff"
    listing = analyst.get("/api/einvoice-batches", params={"entity_id": str(entity.id)}).json()
    assert len(listing) == 2


def test_upload_refuses_unsafe_xml_and_zip(tenant_a: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]>'
        b"<Invoice>&e;</Invoice>"
    )
    r = upload_batch(analyst, entity, xxe, "x.xml", XML)
    # Stored as unreadable or refused outright; never resolved.
    if r.status_code == 201:
        assert r.json()["files"][0]["parse_error"]
        assert (
            b"root:" not in analyst.get(f"/api/einvoice-files/{r.json()['files'][0]['id']}").content
        )
    else:
        assert r.status_code == 422
    traversal = demo.zip_of([("../evil.xml", demo.invoice_xml(demo.InvoiceSpec("A", "u")))])
    assert upload_batch(analyst, entity, traversal).status_code == 422
    not_xml = demo.zip_of([("notes.txt", b"hello")])
    assert upload_batch(analyst, entity, not_xml).status_code == 422
    assert upload_batch(analyst, entity, b"plain text", "a.txt", "text/plain").status_code == 422


def test_upload_roles_and_tenant_isolation(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    data = demo.invoice_xml(demo.InvoiceSpec(number="SYN-9", uuid="u-9"))
    assert (
        upload_batch(login(tenant_a.users[Role.VIEWER]), entity, data, "a.xml", XML).status_code
        == 403
    )
    r = upload_batch(login(tenant_a.users[Role.ANALYST]), entity, data, "a.xml", XML)
    assert r.status_code == 201
    batch_id, file_id = r.json()["id"], r.json()["files"][0]["id"]
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.get(f"/api/einvoice-batches/{batch_id}").status_code == 200

    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert upload_batch(other, entity, data, "a.xml", XML).status_code == 404
    assert other.get(f"/api/einvoice-batches/{batch_id}").status_code == 404
    assert other.get(f"/api/einvoice-files/{file_id}").status_code == 404
    assert other.get(f"/api/einvoice-files/{file_id}/download").status_code == 404
    assert other.get(f"/api/einvoice-files/{uuid.uuid4()}").status_code == 404
    assert other.get("/api/einvoice-batches", params={"entity_id": str(entity.id)}).json() == []


# ---------------------------------------------------------------- validation review


def _ae_batch(analyst: ApiClient, entity: LegalEntity) -> str:
    specs = [
        demo.InvoiceSpec(number="SYN-OK", uuid="u-ok"),
        # Missing issue date (mandatory SYN-02).
        demo.InvoiceSpec(number="SYN-NODATE", uuid="u-nd", omit=("IssueDate",)),
        # Not a valid xs:date (schema).
        demo.InvoiceSpec(number="SYN-BADDATE", uuid="u-bd", issue_date="2026-13-45"),
        # Line net stated as 150.00 instead of 2 × 100.00 (arithmetic line_net).
        demo.InvoiceSpec(
            number="SYN-LINE",
            uuid="u-ln",
            lines=[demo.Line("2", "100.00", net="150.00"), demo.Line("1", "50.00")],
        ),
        # Type code outside the code list, seller TRN of the wrong shape.
        demo.InvoiceSpec(number="SYN-CODE", uuid="u-cd", type_code="999", seller_trn="12345"),
        # Payable amount not equal to tax-inclusive total.
        demo.InvoiceSpec(number="SYN-PAY", uuid="u-ok", payable_override="1.00"),
    ]
    files = [(f"{s.number}.xml", demo.invoice_xml(s)) for s in specs]
    r = upload_batch(analyst, entity, demo.zip_of(files))
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_pint_ae_validation_raises_one_finding_per_failure(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin)
    cv = checklist(reviewer, [req("EINV-01", VALIDATE_AE)])
    batch = _ae_batch(analyst, entity)
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "Synthetic PINT check",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "einvoice_batch_ids": [batch],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["einvoice_count"] == 6 and review["entity_id"] == str(entity.id)
    run = review["latest_run"]
    assert run["engine_version"] == "deterministic-1.4.0"
    assert any("Unverified" in w for w in run["warnings"])

    res = results(analyst, review["id"])["EINV-01"]
    assert res["outcome"] == "exceptions_found"
    keys = {g["key"] for g in res["meta"]["groups"]}
    assert {
        "schema",
        "mandatory:SYN-02",
        "arithmetic:line_net",
        "code_list:SYN-CL-1",
        "arithmetic:payable",
        "duplicate:invoice_uuid",
    } <= keys, keys
    assert any(k.startswith("tax_id:") for k in keys)
    assert res["meta"]["files"][0]["sha256"]

    found = findings(analyst, review["id"])
    by_key = {f["finding_key"]: f for f in found}
    assert set(by_key) == keys
    line = by_key["arithmetic:line_net"]
    ev = line["evidence"][0]
    assert ev["type"] == "xml" and ev["invoice_number"] == "SYN-LINE"
    assert ev["xpath"].startswith("/inv:Invoice/cac:InvoiceLine")
    assert ev["value"] == "150.00"
    assert line["title"].endswith(": Synthetic EINV-01")
    nodate = by_key["mandatory:SYN-02"]["evidence"]
    assert [e["invoice_number"] for e in nodate] == ["SYN-NODATE"]
    schema_ev = by_key["schema"]["evidence"]
    assert any(
        e["invoice_number"] == "SYN-BADDATE" and "IssueDate" in e["xpath"] for e in schema_ev
    )

    # Re-running on the same inputs keeps the same findings and hashes.
    first_hash = res["result_hash"]
    assert reviewer.post(f"/api/reviews/{review['id']}/runs").status_code == 200
    assert results(analyst, review["id"])["EINV-01"]["result_hash"] == first_hash
    assert len(findings(analyst, review["id"])) == len(found)


def test_validation_without_schema_bundle_is_reported(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    cv = checklist(login(tenant_a.users[Role.REVIEWER]), [req("EINV-01", VALIDATE_AE)])
    data = demo.invoice_xml(demo.InvoiceSpec(number="SYN-OK", uuid="u-ok"))
    batch = upload_batch(analyst, entity, data, "a.xml", XML).json()["id"]
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "x",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "einvoice_batch_ids": [batch],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    res = results(analyst, r.json()["id"])["EINV-01"]
    assert res["outcome"] == "not_applicable" and res["needs_attention"]
    assert "syn.einvoice.xsd" in res["message"]


def test_zatca_chain_qr_and_counter_checks(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a, currency="SAR")
    rpv = synthetic_pack(admin, jurisdiction="SA")
    cv = checklist(login(tenant_a.users[Role.REVIEWER]), [req("ZATCA-01", VALIDATE_SA)])
    chain = demo.zatca_chain(4, break_at=3)
    # Drop invoice 2 from the upload so the counter has a gap after the break.
    files = [chain[0], chain[2], chain[3]]
    bad_qr = demo.invoice_xml(
        demo.InvoiceSpec(
            number="SYN-SA-QR",
            uuid="00000000-0000-4000-8000-000000000099",
            currency="SAR",
            seller_country="SA",
            seller_trn="800000000000008",
            buyer_trn=None,
            customization="urn:synthetic:zatca",
            icv=5,
            pih=demo.INITIAL_PIH,
            qr=True,
            qr_total_override="999.99",
        )
    )
    files.append(("sa-qr.xml", bad_qr))
    batch = upload_batch(analyst, entity, demo.zip_of(files)).json()
    assert {f["profile"] for f in batch["files"]} == {"zatca"}
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "ZATCA",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "einvoice_batch_ids": [batch["id"]],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    res = results(analyst, r.json()["id"])["ZATCA-01"]
    keys = {g["key"] for g in res["meta"]["groups"]}
    assert "chain:gap" in keys, keys
    assert "chain:pih_mismatch" in keys
    assert "qr:tag4_mismatch" in keys
    qr_finding = next(
        f for f in findings(analyst, r.json()["id"]) if f["finding_key"] == "qr:tag4_mismatch"
    )
    assert [e["invoice_number"] for e in qr_finding["evidence"]] == ["SYN-SA-QR"]
    assert res["meta"]["hash_method"].startswith("SHA-256 over C14N 1.0")


# ---------------------------------------------------------------- readiness deadline


def test_go_live_deadline_by_size_basis_and_override(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin, with_bundle=False)
    cv = checklist(
        reviewer,
        [
            req(
                "READY-01",
                {
                    "type": "einvoice_deadline",
                    "waves_rule": "syn.einvoice.go_live_waves",
                    "warn_days": 120,
                },
            )
        ],
    )

    def run(as_of: str) -> dict[str, Any]:
        r = reviewer.post(
            "/api/reviews",
            json={
                "title": "Readiness",
                "checklist_version_id": cv,
                "entity_id": str(entity.id),
                "rule_pack_version_id": rpv,
                "as_of_date": as_of,
            },
        )
        assert r.status_code == 201, r.text
        return results(reviewer, r.json()["id"])["READY-01"]

    # No size basis yet: the check asks for it.
    res = run("2026-10-01")
    assert res["outcome"] == "not_applicable" and "size basis" in res["message"]

    p = admin.patch(
        f"/api/entities/{entity.id}",
        json={
            "size_basis_amount": "60000000",
            "size_basis_currency": "AED",
            "size_basis_year": 2025,
        },
    )
    assert p.status_code == 200, p.text
    # 60m ≥ 50m: synthetic wave 1, go-live 2027-01-01; 2026-10-01 is 92 days before.
    # The wave's ASP milestone (2026-09-30) has passed.
    res = run("2026-10-01")
    assert res["meta"]["go_live"] == "2027-01-01" and res["meta"]["days_remaining"] == 92
    assert res["meta"]["wave"] == "Synthetic wave 1 (large)"
    keys = {g["key"] for g in res["meta"]["groups"]}
    assert keys == {"deadline:go_live_soon", "deadline:asp"}, keys

    # Far ahead of both dates: nothing to flag.
    res = run("2026-01-01")
    assert res["outcome"] == "no_exceptions" and res["meta"]["days_remaining"] == 365

    # A notified date overrides the wave and needs a note.
    bad = admin.patch(
        f"/api/entities/{entity.id}", json={"einvoice_go_live_override": "2028-01-01"}
    )
    assert bad.status_code == 422
    ok = admin.patch(
        f"/api/entities/{entity.id}",
        json={
            "einvoice_go_live_override": "2028-01-01",
            "einvoice_go_live_note": "Synthetic notification letter.",
        },
    )
    assert ok.status_code == 200, ok.text
    res = run("2026-10-01")
    assert res["meta"]["go_live_source"] == "override" and res["meta"]["go_live"] == "2028-01-01"
    assert date.fromisoformat(res["meta"]["go_live"]) > date(2027, 12, 31)


# ---------------------------------------------------------------- rejections


FATOORA = [
    {
        "invoiceNumber": "SYN-1",
        "uuid": "u-1",
        "invoiceHash": "h1",
        "clearanceStatus": "NOT_CLEARED",
        "validationResults": {
            "errorMessages": [{"code": "SYN-E1", "message": "Synthetic error"}],
            "warningMessages": [],
        },
    },
    {
        "invoiceNumber": "SYN-2",
        "uuid": "u-2",
        "invoiceHash": "h2",
        "clearanceStatus": "CLEARED",
        "validationResults": {
            "errorMessages": [],
            "warningMessages": [{"code": "SYN-W1", "message": "Synthetic warning"}],
        },
    },
]


def test_rejection_file_becomes_findings_linked_to_stored_invoices(
    tenant_a: Tenant, db: Session
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    xml = [
        (f"{n}.xml", demo.invoice_xml(demo.InvoiceSpec(number=n, uuid=u)))
        for n, u in (("SYN-1", "u-1"), ("SYN-2", "u-2"))
    ]
    batch = upload_batch(analyst, entity, demo.zip_of(xml)).json()["id"]
    ds = analyst.post(
        "/api/datasets",
        data={
            "entity_id": str(entity.id),
            "kind": "einvoice_rejections",
            "name": "Synthetic results",
        },
        files={"file": ("results.json", json.dumps(FATOORA).encode(), "application/json")},
    )
    assert ds.status_code == 201, ds.text
    version = ds.json()["latest_version"]
    assert version["status"] == "ready", version
    assert version["row_count"] == 2
    cv = checklist(reviewer, [req("REJ-01", {"type": "einvoice_rejections"})])
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "Rejections",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "einvoice_batch_ids": [batch],
            "dataset_version_ids": [version["id"]],
        },
    )
    assert r.status_code == 201, r.text
    found = findings(analyst, r.json()["id"])
    assert [f["finding_key"] for f in found] == ["rejection:u-1"]
    types = [e["type"] for e in found[0]["evidence"]]
    assert types == ["dataset_rows", "xml"]
    assert found[0]["evidence"][1]["invoice_number"] == "SYN-1"


def test_review_refuses_einvoices_of_another_entity_or_tenant(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    e1, e2 = make_entity(db, tenant_a), make_entity(db, tenant_a)
    cv = checklist(
        login(tenant_a.users[Role.REVIEWER]), [req("REJ-01", {"type": "einvoice_rejections"})]
    )
    data = demo.invoice_xml(demo.InvoiceSpec(number="SYN-1", uuid="u-1"))
    batch = upload_batch(analyst, e1, data, "a.xml", XML).json()["id"]
    r = analyst.post(
        "/api/reviews",
        json={
            "title": "x",
            "checklist_version_id": cv,
            "entity_id": str(e2.id),
            "einvoice_batch_ids": [batch],
        },
    )
    assert r.status_code == 422, r.text
    other = login(tenant_b.users[Role.ORG_ADMIN])
    other_cv = checklist(
        login(tenant_b.users[Role.REVIEWER]), [req("REJ-01", {"type": "einvoice_rejections"})]
    )
    eb = make_entity(db, tenant_b)
    r = other.post(
        "/api/reviews",
        json={
            "title": "x",
            "checklist_version_id": other_cv,
            "entity_id": str(eb.id),
            "einvoice_batch_ids": [batch],
        },
    )
    assert r.status_code == 404, r.text


def test_einvoice_report_shows_xml_evidence(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = synthetic_pack(admin)
    cv = checklist(reviewer, [req("EINV-01", VALIDATE_AE)])
    bad = demo.invoice_xml(demo.InvoiceSpec(number="SYN-PAY", uuid="u-p", payable_override="1"))
    batch = upload_batch(reviewer, entity, bad, "pay.xml", XML).json()["id"]
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "PINT sample",
            "checklist_version_id": cv,
            "entity_id": str(entity.id),
            "einvoice_batch_ids": [batch],
            "rule_pack_version_id": rpv,
        },
    )
    rid = r.json()["id"]
    for f in findings(reviewer, rid):
        reviewer.post(
            f"/api/findings/{f['id']}/decision",
            json={"decision": "confirmed", "rationale": "Payable amount is wrong."},
        )
    rep = reviewer.post(f"/api/reviews/{rid}/signoff").json()["id"]
    html = reviewer.get(f"/api/reports/{rep}/export?format=html").text
    assert "E-invoices in scope" in html and "pay.xml" in html
    assert "E-invoice SYN-PAY · /inv:Invoice/cac:LegalMonetaryTotal/cbc:PayableAmount" in html
    assert "Schema syn.einvoice.xsd" in html
    assert "nothing was submitted to any platform" in html
    csv_text = reviewer.get(f"/api/reports/{rep}/export?format=csv").text
    assert "E-invoice SYN-PAY" in csv_text
