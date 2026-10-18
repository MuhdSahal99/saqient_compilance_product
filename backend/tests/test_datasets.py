from __future__ import annotations

import hashlib
import io
import uuid
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from sqlalchemy.orm import Session

from app.config import get_settings
from app.datasets.build import from_parquet
from app.models import DatasetVersion, LegalEntity, Role
from app.storage import get_storage
from tests.conftest import ApiClient, Tenant, login

FIXTURES = Path(__file__).parent / "fixtures" / "datasets"
CSV = "text/csv"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

GL_CSV = (
    b"Journal,Date,Account,Narration,Debit,Credit\n"
    b'JE-1,2025-01-05,4000,Synthetic sale,,"1,250.00"\n'
    b"JE-1,2025-01-05,1100,Synthetic sale,1250.00,\n"
    b"JE-2,2025-01-06,5000,Synthetic expense,(0.50),\n"
    b"JE-2,2025-01-06,2000,Synthetic expense,,-0.50\n"
)


def make_entity(db: Session, tenant: Tenant, currency: str = "AED") -> LegalEntity:
    e = LegalEntity(
        org_id=tenant.org.id,
        name=f"Synthetic entity {uuid.uuid4().hex[:6]}",
        country="AE",
        fiscal_year_end_month=12,
        fiscal_year_end_day=31,
        functional_currency=currency,
        timezone="Asia/Dubai",
    )
    db.add(e)
    db.commit()
    return e


def upload(
    client: ApiClient,
    entity: LegalEntity,
    data: bytes,
    filename: str = "gl.csv",
    mime: str = CSV,
    kind: str = "general_ledger",
    **form: str,
):  # type: ignore[no-untyped-def]
    return client.post(
        "/api/datasets",
        data={
            "entity_id": str(entity.id),
            "kind": kind,
            "name": form.pop("name", "FY25 GL"),
            **form,
        },
        files={"file": (filename, data, mime)},
    )


def version_of(resp) -> dict:  # type: ignore[no-untyped-def,type-arg]
    assert resp.status_code == 201, resp.text
    return resp.json()["latest_version"]  # type: ignore[no-any-return]


GL_MAPPING = {
    "entry_id": "Journal",
    "posting_date": "Date",
    "account_code": "Account",
    "description": "Narration",
    "debit": "Debit",
    "credit": "Credit",
}


def test_csv_gl_import_mapping_and_parquet(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    v = version_of(upload(analyst, entity, GL_CSV))
    assert v["status"] == "needs_mapping"
    assert v["raw_sha256"] == hashlib.sha256(GL_CSV).hexdigest()
    assert v["source_columns"] == ["Journal", "Date", "Account", "Narration", "Debit", "Credit"]
    assert v["column_mapping"] == GL_MAPPING  # suggested from headers
    detail = analyst.get(f"/api/dataset-versions/{v['id']}").json()
    assert detail["preview"][0]["Journal"] == "JE-1"

    resp = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": GL_MAPPING})
    assert resp.status_code == 200, resp.text
    out = resp.json()
    assert out["status"] == "ready", out
    assert out["row_count"] == 4
    assert out["derived_fields"] == ["amount"]
    # (0.50) and -0.50 are negatives: 1250.00 - 0.50 on each side.
    assert out["totals"]["debit"] == "1249.5000"
    assert out["totals"]["credit"] == "1249.5000"
    assert Decimal(out["totals"]["amount"]) == Decimal("0")

    row = db.get(DatasetVersion, uuid.UUID(v["id"]))
    assert row is not None and row.parquet_storage_key
    data = get_storage().get(row.parquet_storage_key)
    assert hashlib.sha256(data).hexdigest() == out["parquet_sha256"]
    frame = from_parquet(data)
    assert frame["row_id"].to_list() == [1, 2, 3, 4]
    assert str(frame.schema["debit"]) == "Decimal(precision=20, scale=4)"
    assert frame["credit"].to_list()[0] == Decimal("1250.0000")
    assert frame["debit"].to_list()[2] == Decimal("-0.5000")  # (0.50)
    assert frame["currency"].unique().to_list() == ["AED"]
    assert frame["posting_date"].to_list()[0] == date(2025, 1, 5)

    rows = analyst.get(f"/api/dataset-versions/{v['id']}/rows?row_ids=2,3").json()
    assert [r["row_id"] for r in rows["rows"]] == [2, 3]
    assert rows["rows"][0]["debit"] == "1250.0000"
    assert rows["total"] == 4


def test_invalid_values_fail_with_row_ids(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    csv = (
        b"Journal,Date,Account,Debit,Credit\n"
        b"JE-1,2025-01-05,4000,10.12345,\n"
        b"JE-1,05/01/2025,4000,10,\n"
        b",2025-01-05,4000,1e5,\n"
    )
    v = version_of(upload(analyst, entity, csv))
    mapping = {k: v for k, v in GL_MAPPING.items() if k != "description"}
    out = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": mapping}).json()
    assert out["status"] == "failed"
    assert out["error_count"] == 4
    found = {(e["row_id"], e["field"]) for e in out["errors"]}
    assert found == {(1, "debit"), (2, "posting_date"), (3, "entry_id"), (3, "debit")}
    assert out["parquet_sha256"] is None
    # Fixing the date format lets a corrected file be remapped later; the mapping can be retried.
    retry = analyst.put(
        f"/api/dataset-versions/{v['id']}/mapping",
        json={"mapping": mapping, "date_format": "%d/%m/%Y"},
    ).json()
    assert retry["status"] == "failed"


def test_european_decimals_and_date_format(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    csv = b"Account;Debit;Credit\n1100;1.234,50;\n4000;;1.234,50\n"
    v = version_of(upload(analyst, entity, csv, kind="trial_balance", name="TB"))
    out = analyst.put(
        f"/api/dataset-versions/{v['id']}/mapping",
        json={
            "mapping": {"account_code": "Account", "debit": "Debit", "credit": "Credit"},
            "decimal_separator": ",",
        },
    ).json()
    assert out["status"] == "ready", out
    assert out["totals"]["debit"] == "1234.5000"
    assert out["derived_fields"] == ["balance"]


def _xlsx(rows: list[list[object]]) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_values_and_excel_dates(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    data = _xlsx(
        [
            ["Invoice No", "Invoice Date", "Customer", "Net", "VAT"],
            ["S-1", date(2025, 2, 1), "Synthetic Buyer A", 1000, 50],
            ["S-2", date(2025, 2, 2), "Synthetic Buyer B", 200.5, 10.03],
        ]
    )
    v = version_of(upload(analyst, entity, data, "sales.xlsx", XLSX, kind="sales_register"))
    assert v["status"] == "needs_mapping"
    out = analyst.put(
        f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": v["column_mapping"]}
    ).json()
    assert out["status"] == "ready", out
    assert out["totals"]["net_amount"] == "1200.5000"
    assert out["totals"]["tax_amount"] == "60.0300"


def test_xlsx_formulas_and_macros_rejected(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    formula = _xlsx([["Account", "Balance"], ["1100", "=1+1"]])
    resp = upload(analyst, entity, formula, "tb.xlsx", XLSX, kind="trial_balance")
    assert resp.status_code == 422 and "formulas" in resp.json()["detail"]
    assert upload(analyst, entity, formula, "tb.xlsm", XLSX).status_code == 422
    buf = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(_xlsx([["a"], ["1"]]))) as src,
        zipfile.ZipFile(buf, "w") as dst,
    ):
        for item in src.infolist():
            dst.writestr(item, src.read(item))
        dst.writestr("xl/vbaProject.bin", b"macro")
    resp = upload(analyst, entity, buf.getvalue(), "tb.xlsx", XLSX, kind="trial_balance")
    assert resp.status_code == 422 and "Macro" in resp.json()["detail"]
    assert upload(analyst, entity, b"not a zip", "tb.xlsx", XLSX).status_code == 422


def test_mt940_builds_with_fixed_mapping(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    data = (FIXTURES / "statement.mt940").read_bytes()
    v = version_of(upload(analyst, entity, data, "s.mt940", "text/plain", kind="bank_statement"))
    assert v["status"] == "ready", v
    rows = analyst.get(f"/api/dataset-versions/{v['id']}/rows").json()["rows"]
    assert [r["amount"] for r in rows] == ["-1500.2500", "2500.0000"]
    assert [r["debit"] for r in rows] == ["1500.2500", "0.0000"]
    assert rows[0]["transaction_date"] == "2025-01-02"
    assert rows[0]["description"] == "Synthetic supplier payment"
    assert rows[0]["currency"] == "AED"
    # MT940 is only accepted for bank statements, and has no editable mapping.
    assert upload(analyst, entity, data, "s.mt940", "text/plain", name="x").status_code == 422
    remap = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": {}})
    assert remap.status_code == 422


def test_camt053_builds_and_xxe_is_refused(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    data = (FIXTURES / "statement.camt053.xml").read_bytes()
    v = version_of(upload(analyst, entity, data, "s.xml", "application/xml", kind="bank_statement"))
    assert v["status"] == "ready", v
    rows = analyst.get(f"/api/dataset-versions/{v['id']}/rows").json()["rows"]
    assert [r["amount"] for r in rows] == ["-1500.2500", "2500.0000"]
    assert rows[0]["counterparty"] == "Synthetic Supplies Co"
    assert rows[1]["transaction_date"] == "2025-01-03"
    xxe = (
        b'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<Document><Ntry><Amt Ccy="AED">&x;</Amt></Ntry></Document>'
    )
    bad = version_of(
        upload(analyst, entity, xxe, "x.xml", "application/xml", kind="bank_statement", name="X")
    )
    assert bad["status"] == "failed"
    assert "safely" in (bad["failure_message"] or "")


def test_bank_csv_debit_credit_derives_signed_amount(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    csv = b"Date,Details,Withdrawal,Deposit,Currency\n2025-01-02,Rent,500,,aed\n2025-01-03,Receipt,,700,AED\n"
    v = version_of(upload(analyst, entity, csv, "bank.csv", kind="bank_statement", name="Bank"))
    assert v["column_mapping"] == {
        "transaction_date": "Date",
        "description": "Details",
        "debit": "Withdrawal",
        "credit": "Deposit",
        "currency": "Currency",
    }
    out = analyst.put(
        f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": v["column_mapping"]}
    ).json()
    assert out["status"] == "ready"
    rows = analyst.get(f"/api/dataset-versions/{v['id']}/rows").json()["rows"]
    assert [r["amount"] for r in rows] == ["-500.0000", "700.0000"]
    assert {r["currency"] for r in rows} == {"AED"}


@pytest.mark.parametrize(
    "mapping,detail",
    [
        (
            {
                "entry_id": "Journal",
                "account_code": "Account",
                "debit": "Debit",
                "credit": "Credit",
            },
            "posting_date",
        ),
        ({**GL_MAPPING, "debit": "Nope"}, "not in the file"),
        ({**GL_MAPPING, "bogus": "Debit"}, "Unknown field"),
        (
            {"entry_id": "Journal", "posting_date": "Date", "account_code": "Account"},
            "debit+credit or amount",
        ),
        ({**GL_MAPPING, "credit": "Debit"}, "one field only"),
    ],
)
def test_mapping_validation(
    tenant_a: Tenant, db: Session, mapping: dict[str, str], detail: str
) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    v = version_of(upload(analyst, entity, GL_CSV))
    resp = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": mapping})
    assert resp.status_code == 422
    assert detail in resp.json()["detail"]


@pytest.mark.parametrize(
    "data,filename,mime,detail",
    [
        (b"", "gl.csv", CSV, "empty"),
        (b"a,b\n1,2\n", "gl.pdf", "application/pdf", "Unsupported"),
        (b"a,b\n1,2\n", "gl.csv", "image/png", "declared type"),
        (b"\x00\x01binary", "gl.csv", CSV, "binary"),
        ("Konto,Betrag\n1,2\n".encode("utf-16"), "gl.csv", CSV, None),
    ],
)
def test_upload_validation(
    tenant_a: Tenant, db: Session, data: bytes, filename: str, mime: str, detail: str | None
) -> None:
    entity = make_entity(db, tenant_a)
    resp = upload(login(tenant_a.users[Role.ANALYST]), entity, data, filename, mime)
    if resp.status_code == 201:  # UTF-16 passes the signature check but fails parsing
        assert resp.json()["latest_version"]["status"] == "failed"
        assert "UTF-8" in resp.json()["latest_version"]["failure_message"]
    else:
        assert resp.status_code == 422
        if detail:
            assert detail in resp.json()["detail"]


def test_csv_header_and_row_limits(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    dup = version_of(upload(analyst, entity, b"a,a\n1,2\n", name="dup"))
    assert dup["status"] == "failed"
    settings = get_settings()
    old = settings.dataset_max_rows
    settings.dataset_max_rows = 3
    try:
        big = version_of(upload(analyst, entity, GL_CSV, name="big"))
        assert big["status"] == "failed" and "more than 3" in big["failure_message"]
    finally:
        settings.dataset_max_rows = old


def test_duplicate_file_and_new_version(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    first = upload(analyst, entity, GL_CSV)
    assert first.status_code == 201
    again = upload(analyst, entity, GL_CSV, name="other")
    assert again.status_code == 409
    assert again.json()["duplicate_dataset_id"] == first.json()["id"]
    assert upload(analyst, entity, GL_CSV, name="other", allow_duplicate="true").status_code == 201
    v2 = analyst.post(
        f"/api/datasets/{first.json()['id']}/versions",
        files={"file": ("gl.csv", GL_CSV + b"JE-3,2025-01-07,1100,x,1,\n", CSV)},
    )
    assert v2.status_code == 201
    assert [v["version_number"] for v in v2.json()["versions"]] == [1, 2]


def test_viewer_cannot_import_or_map(tenant_a: Tenant, db: Session) -> None:
    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    created = upload(analyst, entity, GL_CSV)
    v = created.json()["latest_version"]
    viewer = login(tenant_a.users[Role.VIEWER])
    assert upload(viewer, entity, GL_CSV, name="v").status_code == 403
    assert (
        viewer.post(
            f"/api/datasets/{created.json()['id']}/versions",
            files={"file": ("gl.csv", GL_CSV, CSV)},
        ).status_code
        == 403
    )
    assert (
        viewer.put(
            f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": GL_MAPPING}
        ).status_code
        == 403
    )
    assert viewer.get("/api/datasets").status_code == 200
    assert viewer.get(f"/api/dataset-versions/{v['id']}").status_code == 200
    assert viewer.get("/api/dataset-kinds").status_code == 200


def test_datasets_are_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    entity_a = make_entity(db, tenant_a)
    a = login(tenant_a.users[Role.ANALYST])
    created = upload(a, entity_a, GL_CSV).json()
    vid = created["latest_version"]["id"]
    a.put(f"/api/dataset-versions/{vid}/mapping", json={"mapping": GL_MAPPING})
    b = login(tenant_b.users[Role.ORG_ADMIN])
    # Another tenant's entity cannot be used.
    assert upload(b, entity_a, GL_CSV, name="steal").status_code == 404
    assert b.get("/api/datasets").json() == []
    assert b.get(f"/api/datasets/{created['id']}").status_code == 404
    assert (
        b.post(
            f"/api/datasets/{created['id']}/versions", files={"file": ("gl.csv", GL_CSV, CSV)}
        ).status_code
        == 404
    )
    assert b.get(f"/api/dataset-versions/{vid}").status_code == 404
    assert b.get(f"/api/dataset-versions/{vid}/rows").status_code == 404
    assert (
        b.put(f"/api/dataset-versions/{vid}/mapping", json={"mapping": GL_MAPPING}).status_code
        == 404
    )
    assert b.get(f"/api/dataset-versions/{uuid.uuid4()}").status_code == 404


def test_datasets_require_sign_in() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/api/datasets").status_code == 401


def test_100k_row_gl_import_under_60_seconds(tenant_a: Tenant, db: Session) -> None:
    """Acceptance: upload -> parse -> mapping -> Parquet through the API, eager worker."""
    import time

    from scripts.bench_gl_import import synthetic_gl

    entity = make_entity(db, tenant_a)
    analyst = login(tenant_a.users[Role.ANALYST])
    raw = synthetic_gl(100_000)
    started = time.perf_counter()
    v = version_of(upload(analyst, entity, raw, name="100k GL"))
    out = analyst.put(
        f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": v["column_mapping"]}
    ).json()
    elapsed = time.perf_counter() - started
    assert out["status"] == "ready", out
    assert out["row_count"] == 100_000
    assert out["totals"]["debit"] == out["totals"]["credit"]
    assert elapsed < 60, f"took {elapsed:.1f}s"
