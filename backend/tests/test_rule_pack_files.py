"""Rule packs Phase B: structured (json) values and attached XSD bundles."""

from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models import Role
from app.services import rule_packs as svc
from tests.conftest import ApiClient, Tenant, login

SOURCE = "https://example.org/synthetic-source"

MAIN_XSD = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:t"
  xmlns:c="urn:c" elementFormDefault="qualified">
  <xs:import namespace="urn:c" schemaLocation="common/c.xsd"/>
  <xs:element name="Inv"><xs:complexType><xs:sequence><xs:element ref="c:ID"/>
  </xs:sequence></xs:complexType></xs:element></xs:schema>"""
COMMON_XSD = b"""<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:c"
  elementFormDefault="qualified"><xs:element name="ID" type="xs:string"/></xs:schema>"""


def bundle(files: dict[str, bytes] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, body in (files or {"main.xsd": MAIN_XSD, "common/c.xsd": COMMON_XSD}).items():
            z.writestr(name, body)
    return buf.getvalue()


def _draft(client: ApiClient, jurisdiction: str = "AE") -> tuple[str, str]:
    r = client.post("/api/rule-packs", json={"name": "E-inv pack", "jurisdiction": jurisdiction})
    assert r.status_code == 201, r.text
    return r.json()["id"], r.json()["versions"][0]["id"]


def _json_rule(key: str, value: object, **over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "rule_key": key,
        "title": "Structured rule",
        "value_type": "json",
        "value": json.dumps(value),
        "effective_from": "2020-01-01",
        "source_url": SOURCE,
    }
    base.update(over)
    return base


def _attach(client: ApiClient, vid: str, data: bytes, entry: str = "main.xsd", **form: str):  # type: ignore[no-untyped-def]
    return client.post(
        f"/api/rule-pack-versions/{vid}/files",
        data={
            "file_key": "einvoice.test.xsd",
            "title": "Test schema",
            "entry_point": entry,
            **form,
        },
        files={"file": ("bundle.zip", data, "application/zip")},
    )


def test_json_rules_parse_decimals_and_check_shape(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    _, vid = _draft(admin)
    fields = [{"id": "BT-1", "label": "Invoice number", "xpath": "/inv:Invoice/cbc:ID"}]
    formats = {"AE": {"length": 15, "prefix": "1"}}
    waves = [{"label": "Wave 1", "min_revenue": 1.5, "currency": "AED", "go_live": "2030-01-01"}]
    rules = [
        _json_rule("ae.einvoice.mandatory_fields", fields),
        _json_rule("ae.tax_id_formats", formats),
        _json_rule("ae.einvoice.go_live_waves", waves),
    ]
    r = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": rules})
    assert r.status_code == 200, r.text
    assert admin.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 200
    got = svc.resolve(
        db, tenant_a.org.id, uuid.UUID(vid), "ae.einvoice.go_live_waves", date.today()
    )
    # Numbers in JSON rules are Decimal, never float.
    assert got.value[0]["min_revenue"] == Decimal("1.5")
    snap = got.snapshot()
    assert snap["value"] is None and len(snap["value_sha256"]) == 64


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (_json_rule("ae.einvoice.mandatory_fields", [{"id": "X", "label": "x"}]), "xpath"),
        (
            _json_rule(
                "ae.einvoice.mandatory_fields",
                [{"id": "X", "label": "x", "xpath": "//*[contains(., 'a')]"}],
            ),
            "xpath",
        ),
        (_json_rule("ae.tax_id_formats", {"ae": {"length": 15}}), "ae"),
        (_json_rule("ae.anything", "just a string"), "object or an array"),
        ({**_json_rule("ae.x", {}), "value": "{not json"}, "not valid JSON"),
        ({**_json_rule("ae.x", {}), "value_type": "string", "value": "x" * 201}, "200"),
    ],
)
def test_json_rule_validation(tenant_a: Tenant, rule: dict[str, object], message: str) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    _, vid = _draft(admin)
    r = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [rule]})
    assert r.status_code == 422, r.text
    assert message in r.text


def test_xsd_bundle_attach_verify_and_copy(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    pack_id, vid = _draft(admin)
    r = _attach(reviewer, vid, bundle(), source_url=SOURCE)
    assert r.status_code == 201, r.text
    f = r.json()["files"][0]
    assert f["verification_status"] == "draft" and len(f["sha256"]) == 64
    assert r.json()["unverified_count"] == 1
    # Only admins verify.
    assert reviewer.post(f"/api/rule-pack-files/{f['id']}/verify").status_code == 403
    v = admin.post(f"/api/rule-pack-files/{f['id']}/verify")
    assert v.status_code == 200 and v.json()["verification_status"] == "verified"
    admin.put(
        f"/api/rule-pack-versions/{vid}/rules",
        json={"rules": [_json_rule("ae.codes", ["380"])]},
    )
    assert admin.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 200
    # Published: immutable.
    assert _attach(admin, vid, bundle()).status_code == 409
    resolved = svc.resolve_file(db, tenant_a.org.id, uuid.UUID(vid), "einvoice.test.xsd")
    assert resolved.verified and resolved.warning() is None
    assert resolved.read()[:2] == b"PK"
    # A new draft carries the file by reference, verification included.
    d = admin.post(f"/api/rule-packs/{pack_id}/drafts")
    assert d.status_code == 201 and d.json()["files"][0]["sha256"] == f["sha256"]
    assert d.json()["files"][0]["verification_status"] == "verified"


@pytest.mark.parametrize(
    ("data", "entry", "message"),
    [
        (b"not a zip", "main.xsd", "not a ZIP"),
        (bundle(), "missing.xsd", "no file"),
        (bundle({"../evil.xsd": MAIN_XSD}), "../evil.xsd", "unsafe path"),
        (bundle({"main.xsd": MAIN_XSD, "run.sh": b"echo"}), "main.xsd", "may only contain"),
        (bundle({"main.xsd": MAIN_XSD}), "main.xsd", "compile"),
        (
            bundle(
                {
                    "main.xsd": b'<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
                    b'<xs:include schemaLocation="https://example.org/x.xsd"/></xs:schema>'
                }
            ),
            "main.xsd",
            "compile",
        ),
        (
            bundle({"main.xsd": b'<!DOCTYPE x [<!ENTITY e "y">]><x>&e;</x>'}),
            "main.xsd",
            "DTD",
        ),
    ],
)
def test_bad_bundles_are_refused(tenant_a: Tenant, data: bytes, entry: str, message: str) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    _, vid = _draft(admin)
    r = _attach(admin, vid, data, entry)
    assert r.status_code == 422, r.text
    assert message in r.json()["detail"]


def test_synthetic_files_cannot_be_verified(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    _, vid = _draft(admin, "SYNTHETIC")
    f = _attach(admin, vid, bundle(), source_url=SOURCE).json()["files"][0]
    r = admin.post(f"/api/rule-pack-files/{f['id']}/verify")
    assert r.status_code == 422 and "Synthetic" in r.text


@pytest.mark.parametrize("role", [Role.ANALYST, Role.VIEWER])
def test_files_need_reviewer_or_admin(tenant_a: Tenant, role: Role) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    _, vid = _draft(admin)
    assert _attach(login(tenant_a.users[role]), vid, bundle()).status_code == 403


def test_files_are_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin_a = login(tenant_a.users[Role.ORG_ADMIN])
    admin_b = login(tenant_b.users[Role.ORG_ADMIN])
    _, vid = _draft(admin_a)
    f = _attach(admin_a, vid, bundle(), source_url=SOURCE).json()["files"][0]
    assert _attach(admin_b, vid, bundle()).status_code == 404
    assert admin_b.post(f"/api/rule-pack-files/{f['id']}/verify").status_code == 404
    assert admin_b.post(f"/api/rule-pack-files/{uuid.uuid4()}/verify").status_code == 404
    with pytest.raises(svc.RuleNotFound):
        svc.resolve_file(db, tenant_b.org.id, uuid.UUID(vid), "einvoice.test.xsd")
