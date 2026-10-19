"""Phase E1: bank reconciliation over a statement and ledger version.

Period 2025-11-01..2026-01-31, GL account 1010, opening book balance 10000.
  reference:       bank 1 INV-100 5000 ↔ JE1;  bank 2 PAY-7 −1200 ↔ JE2
  amount_date:     bank 3 800 (01-10) ↔ JE3 800 (01-08), 2 days inside the 3-day window
  reference_group: bank 4 BATCH9 3000 ↔ JE4 1000 + JE5 2000
  unmatched:       bank 5 charges −25; JE6 cheque −400 (1 day), JE0 deposit +300 (72 days)
  book movement 7500 → closing 17500; statement closing 17575
  adjusted bank 17575 + (−100) = 17475 = adjusted book 17500 + (−25); difference 0
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_datasets import make_entity
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack

BANK = (
    b"transaction_date,description,reference,amount,balance\n"
    b"2026-01-03,Customer receipt,INV-100,5000.00,15000.00\n"
    b"2026-01-05,Supplier payment,PAY-7,-1200.00,13800.00\n"
    b"2026-01-10,Card settlement,,800.00,14600.00\n"
    b"2026-01-15,Receipt batch,BATCH9,3000.00,17600.00\n"
    b"2026-01-31,Bank charges,,-25.00,17575.00\n"
)
GL = (
    b"entry_id,posting_date,account_code,description,reference,debit,credit\n"
    b"JE0,2025-11-20,1010,Deposit,DEP1,300.00,0\n"
    b"JE1,2026-01-02,1010,Receipt,INV-100,5000.00,0\n"
    b"JE2,2026-01-05,1010,Payment,PAY-7,0,1200.00\n"
    b"JE3,2026-01-08,1010,Card,CARD,800.00,0\n"
    b"JE4,2026-01-14,1010,Batch a,BATCH9,1000.00,0\n"
    b"JE5,2026-01-14,1010,Batch b,BATCH9,2000.00,0\n"
    b"JE6,2026-01-30,1010,Cheque 55,CHQ55,0,400.00\n"
    b"JE7,2026-01-02,4000,Revenue,INV-100,0,5000.00\n"
)


def setup_rec(db: Session, tenant: Tenant) -> tuple[dict[Role, ApiClient], dict[str, Any], Any]:
    c = {
        r: login(tenant.users[r])
        for r in (Role.ORG_ADMIN, Role.REVIEWER, Role.ANALYST, Role.VIEWER)
    }
    entity = make_entity(db, tenant)
    body = {
        "entity_id": str(entity.id),
        "name": "January bank reconciliation (synthetic)",
        "account_label": "Operating account",
        "period_start": "2025-11-01",
        "period_end": "2026-01-31",
        "statement_version_id": dataset(c[Role.ANALYST], entity, "bank_statement", BANK),
        "ledger_version_id": dataset(c[Role.ANALYST], entity, "general_ledger", GL),
        "gl_accounts": ["1010"],
        "rule_pack_version_id": ct_pack(c[Role.ORG_ADMIN]),
        "rules_prefix": "syn.recon",
        "book_opening_balance": "10000",
    }
    return c, body, entity


def test_reconcile_match_sign_off_and_export(tenant_a: Tenant, db: Session) -> None:
    c, body, _ = setup_rec(db, tenant_a)
    analyst, reviewer, viewer = c[Role.ANALYST], c[Role.REVIEWER], c[Role.VIEWER]
    assert viewer.post("/api/bank-reconciliations", json=body).status_code == 403
    bad = analyst.post(
        "/api/bank-reconciliations", json={**body, "account_label": "AE070331234567890123456"}
    )
    assert bad.status_code == 422
    swapped = analyst.post(
        "/api/bank-reconciliations",
        json={**body, "statement_version_id": body["ledger_version_id"]},
    )
    assert swapped.status_code == 422
    r = analyst.post("/api/bank-reconciliations", json=body)
    assert r.status_code == 201, r.text
    rec = r.json()
    rid = rec["id"]
    methods = sorted((m["method"], m["bank_row_ids"], m["book_row_ids"]) for m in rec["matches"])
    assert methods == [
        ("amount_date", [3], [4]),
        ("reference", [1], [2]),
        ("reference", [2], [3]),
        ("reference_group", [4], [5, 6]),
    ]
    s = rec["summary"]
    assert (s["bank_closing_balance"], s["bank_closing_source"]) == ("17575.0000", "statement")
    assert Decimal(s["book_closing_balance"]) == 17500 and Decimal(s["book_movement"]) == 7500
    assert Decimal(s["adjusted_bank"]) == Decimal(s["adjusted_book"]) == 17475
    assert Decimal(s["difference"]) == 0
    unmatched = sorted(
        (i["side"], i["row_id"], i["age_days"], i["bucket"])
        for i in rec["items"]
        if i["match_id"] is None
    )
    assert unmatched == [("bank", 5, 0, "0-30"), ("book", 1, 72, "61-90"), ("book", 7, 1, "0-30")]
    assert rec["warnings"] and rec["parameters"]["date_window_days"] == 3
    assert viewer.get(f"/api/bank-reconciliations/{rid}").status_code == 200

    # A manual match must agree within the tolerance; a reason is required.
    off = {"bank_row_ids": [5], "book_row_ids": [7], "reason": "Synthetic attempt"}
    assert analyst.post(f"/api/bank-reconciliations/{rid}/matches", json=off).status_code == 422
    ref = next(m for m in rec["matches"] if m["bank_row_ids"] == [1])
    url = f"/api/bank-reconciliations/{rid}/matches/{ref['id']}"
    assert analyst.delete(url).status_code == 422  # reason missing
    after = analyst.delete(url, params={"reason": "Synthetic re-check"}).json()
    assert len(after["matches"]) == 3 and Decimal(after["summary"]["difference"]) == 0
    redo = {"bank_row_ids": [1], "book_row_ids": [2], "reason": "Synthetic manual match"}
    m = analyst.post(f"/api/bank-reconciliations/{rid}/matches", json=redo)
    assert m.status_code == 201, m.text
    again = analyst.post(f"/api/bank-reconciliations/{rid}/auto-match").json()
    assert sorted(x["method"] for x in again["matches"]) == [
        "amount_date",
        "manual",
        "reference",
        "reference_group",
    ]

    # Sign-off: prepared first, by someone other than the preparer, with a zero difference.
    assert reviewer.post(f"/api/bank-reconciliations/{rid}/sign-off").status_code == 409
    assert analyst.post(f"/api/bank-reconciliations/{rid}/prepare").status_code == 200
    assert analyst.post(f"/api/bank-reconciliations/{rid}/sign-off").status_code == 403
    signed = reviewer.post(f"/api/bank-reconciliations/{rid}/sign-off")
    assert signed.status_code == 200, signed.text
    out = signed.json()
    assert out["status"] == "signed_off" and out["versions"][0]["version"] == 1
    assert out["sign_off"]["prepared_by_name"] == tenant_a.users[Role.ANALYST].full_name
    upd = {k: body[k] for k in ("name", "account_label", "gl_accounts", "book_opening_balance")}
    assert analyst.put(f"/api/bank-reconciliations/{rid}", json=upd).status_code == 409
    base = f"/api/bank-reconciliations/{rid}/versions/1/export"
    html = viewer.get(base, params={"format": "html"})
    assert html.status_code == 200 and "Bank reconciliation" in html.text and "61-90" in html.text
    csv = viewer.get(base, params={"format": "csv"})
    assert csv.status_code == 200 and "Unmatched items" in csv.text
    pdf = viewer.get(base, params={"format": "pdf"})
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    with pytest.raises(DBAPIError):
        db.execute(text("UPDATE assurance_snapshots SET version = 9"))
        db.flush()
    db.rollback()

    # Reopen needs a reason; changing accounts clears matches and re-runs the auto-match.
    assert (
        reviewer.post(f"/api/bank-reconciliations/{rid}/reopen", json={"reason": ""}).status_code
        == 422
    )
    assert (
        reviewer.post(
            f"/api/bank-reconciliations/{rid}/reopen", json={"reason": "Synthetic"}
        ).status_code
        == 200
    )
    moved = analyst.put(
        f"/api/bank-reconciliations/{rid}",
        json={**upd, "gl_accounts": ["1010", "4000"], "book_opening_balance": "9000"},
    )
    assert moved.status_code == 200
    assert "manual" not in [x["method"] for x in moved.json()["matches"]]
    # The extra account's line stays unmatched on both sides of the proof; the opening
    # balance no longer agrees, so the difference is 1000 and sign-off is refused.
    assert Decimal(moved.json()["summary"]["difference"]) == 1000
    assert analyst.post(f"/api/bank-reconciliations/{rid}/prepare").status_code == 200
    assert reviewer.post(f"/api/bank-reconciliations/{rid}/sign-off").status_code == 422


def test_bank_rec_tenant_isolation(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    c, body, _ = setup_rec(db, tenant_a)
    rid = c[Role.ANALYST].post("/api/bank-reconciliations", json=body).json()["id"]
    other = login(tenant_b.users[Role.ORG_ADMIN])
    for path in (
        f"/api/bank-reconciliations/{rid}",
        f"/api/bank-reconciliations/{uuid.uuid4()}",
        f"/api/bank-reconciliations/{rid}/versions/1/export?format=html",
    ):
        assert other.get(path).status_code == 404
    assert other.post(f"/api/bank-reconciliations/{rid}/auto-match").status_code == 404
    assert other.post(f"/api/bank-reconciliations/{rid}/prepare").status_code == 404
    assert other.get("/api/bank-reconciliations").json() == []
    # Another tenant's dataset versions and pack are not usable.
    entity_b = make_entity(db, tenant_b)
    stolen = other.post("/api/bank-reconciliations", json={**body, "entity_id": str(entity_b.id)})
    assert stolen.status_code in (404, 422)
