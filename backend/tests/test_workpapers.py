"""Phase C: tax workpapers through the API (inputs, evidence, compute, sign-off, isolation).

The figures repeat golden case 1 of tests/golden/ct_bridge.json, imported from a
synthetic trial balance, so the API path and the pure formula agree.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import demo_tax
from app.models import AuditEvent, Role, WorkpaperSnapshot
from tests.conftest import ApiClient, Tenant, login, ready_version_id
from tests.test_datasets import make_entity, upload, version_of

TB_CSV = (
    b"Account,Description,Debit,Credit\n"
    b"4000,Synthetic sales,,3000000\n"
    b"5000,Synthetic costs,2000000,\n"
    b"6100,Synthetic fines,20000,\n"
    b"6200,Synthetic entertainment,30000,\n"
    b"7000,Synthetic dividends received,,50000\n"
    b"8000,Synthetic interest,400000,\n"
    b"1000,Synthetic bank,1600000,\n"
)
TB_MAPPING = {
    "account_code": "Account",
    "account_name": "Description",
    "debit": "Debit",
    "credit": "Credit",
}
# Accounting profit = 3000000 + 50000 - 2000000 - 20000 - 30000 - 400000 = 600000;
# the bridge below adds net interest back via its own input.


def ct_pack(admin: ApiClient, rows: list[dict[str, Any]] | None = None) -> str:
    r = admin.post(
        "/api/rule-packs",
        json={"name": f"Synthetic CT pack {uuid.uuid4().hex[:6]}", "jurisdiction": "AE"},
    )
    assert r.status_code == 201, r.text
    vid = r.json()["versions"][0]["id"]
    put = admin.put(
        f"/api/rule-pack-versions/{vid}/rules", json={"rules": rows or demo_tax.rules()}
    )
    assert put.status_code == 200, put.text
    assert admin.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 200
    return str(vid)


def new_paper(client: ApiClient, entity_id: Any, rpv: str, **over: Any):  # type: ignore[no-untyped-def]
    body = {
        "entity_id": str(entity_id),
        "kind": "corporate_tax",
        "title": "Synthetic FY2025 corporate tax",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.ct",
        **over,
    }
    return client.post("/api/workpapers", json=body)


def put_in(client: ApiClient, wp: str, key: str, **body: Any):  # type: ignore[no-untyped-def]
    body.setdefault("label", key.replace("_", " "))
    return client.put(f"/api/workpapers/{wp}/inputs/{key}", json=body)


def lines(out: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {ln["line_key"]: ln for ln in out["lines"]}


def test_ct_workpaper_from_trial_balance_with_evidence(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    v = version_of(upload(analyst, entity, TB_CSV, filename="tb.csv", kind="trial_balance"))
    mapped = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": TB_MAPPING})
    assert mapped.json()["status"] == "ready", mapped.text

    r = new_paper(analyst, entity.id, rpv)
    assert r.status_code == 201, r.text
    wp = r.json()
    assert wp["status"] == "draft" and wp["currency"] == "AED" and wp["lines"] == []

    imp = analyst.post(
        f"/api/workpapers/{wp['id']}/import-trial-balance",
        json={
            "dataset_version_id": v["id"],
            "lines": [
                {
                    "line_key": "accounting_profit",
                    "label": "Accounting profit (P&L accounts)",
                    "account_codes": ["4000", "5000", "6100", "6200", "7000", "8000"],
                    "sign": "credit",
                },
                {
                    "line_key": "fines",
                    "category": "non_deductible",
                    "label": "Fines",
                    "account_codes": ["6100"],
                    "sign": "debit",
                },
            ],
        },
    )
    # The same account cannot feed two lines.
    assert imp.status_code == 422 and "more than one line" in imp.json()["detail"]
    imp = analyst.post(
        f"/api/workpapers/{wp['id']}/import-trial-balance",
        json={
            "dataset_version_id": v["id"],
            "lines": [
                {
                    "line_key": "accounting_profit",
                    "label": "Accounting profit (P&L accounts)",
                    "account_codes": ["4000", "5000", "6100", "6200", "7000", "8000"],
                    "sign": "credit",
                }
            ],
        },
    )
    assert imp.status_code == 200, imp.text
    ap = lines(imp.json())["accounting_profit"]
    assert Decimal(ap["amount"]) == Decimal("600000")
    ev = ap["evidence"][0]
    assert ev["kind"] == "dataset_rows" and ev["row_ids"] == [1, 2, 3, 4, 5, 6]
    assert ev["dataset_version_id"] == v["id"] and ev["sign"] == "credit"

    # Adjust to golden case 1: profit 1000000 (manual override, with a document cited).
    doc_version = ready_version_id(analyst)
    blocks = analyst.get(f"/api/document-versions/{doc_version}/blocks").json()["items"]
    cite = [{"kind": "source_block", "source_block_id": blocks[0]["id"]}]
    assert (
        put_in(analyst, wp["id"], "accounting_profit", amount="1000000", evidence=cite).status_code
        == 200
    )
    rows_ev = [{"kind": "dataset_rows", "dataset_version_id": v["id"], "row_ids": [3]}]
    for key, cat, amt, evid in [
        ("fines", "non_deductible", "20000", rows_ev),
        ("client_entertainment", "entertainment", "30000", []),
        ("dividends", "exempt_income", "50000", []),
        ("tp_adjustment", "related_party", "12000", []),
        ("net_interest_expense", "input", "400000", []),
        ("depreciation_amortisation", "input", "100000", []),
        ("losses_brought_forward", "input", "300000", []),
    ]:
        r = put_in(analyst, wp["id"], key, category=cat, amount=amt, evidence=evid)
        assert r.status_code == 200, r.text
    got = lines(r.json())
    assert got["accounting_profit"]["evidence"][0]["ref"] == blocks[0]["ref"]
    assert got["accounting_profit"]["evidence"][0]["quote"]
    assert got["fines"]["evidence"][0]["row_ids"] == [3]

    # Reviewer cannot sign off before compute.
    assert reviewer.post(f"/api/workpapers/{wp['id']}/sign-off").status_code == 422
    c = analyst.post(f"/api/workpapers/{wp['id']}/compute")
    assert c.status_code == 200, c.text
    out = c.json()
    got = lines(out)
    assert Decimal(got["calc:tax"]["amount"]) == Decimal("39000")
    assert Decimal(got["calc:taxable_income"]["amount"]) == Decimal("725000")
    assert Decimal(got["calc:interest_disallowed"]["amount"]) == Decimal("25000")
    assert got["calc:tax"]["formula_id"] == "ct.tax"
    assert got["calc:tax"]["explanation"][-1]["value"] == "39000.00"
    snap_keys = {s["rule_key"] for s in got["calc:tax"]["rule_snapshots"]}
    assert snap_keys == {"syn.ct.rate_bands", "syn.ct.amount_decimals", "syn.ct.rounding_mode"}
    assert all(s["verification_status"] == "draft" for s in got["calc:tax"]["rule_snapshots"])
    assert out["calc_version"] == "calc-1.0.0" and len(out["result_hash"]) == 64
    assert out["warnings"] and all("Unverified" in w for w in out["warnings"])

    # Recompute is deterministic.
    again = analyst.post(f"/api/workpapers/{wp['id']}/compute").json()
    assert again["result_hash"] == out["result_hash"]

    # Changing an input clears computed lines.
    changed = put_in(
        analyst, wp["id"], "dividends", category="exempt_income", amount="60000"
    ).json()
    assert changed["result_hash"] is None
    assert not [k for k in lines(changed) if k.startswith("calc:")]
    put_in(analyst, wp["id"], "dividends", category="exempt_income", amount="50000")
    analyst.post(f"/api/workpapers/{wp['id']}/compute")

    # Analyst cannot sign off; reviewer can; signed-off papers are locked.
    assert analyst.post(f"/api/workpapers/{wp['id']}/sign-off").status_code == 403
    s = reviewer.post(f"/api/workpapers/{wp['id']}/sign-off")
    assert s.status_code == 200, s.text
    assert s.json()["status"] == "signed_off" and s.json()["snapshots"][0]["version"] == 1
    assert put_in(analyst, wp["id"], "dividends", amount="1").status_code == 409
    assert analyst.post(f"/api/workpapers/{wp['id']}/compute").status_code == 409
    snap = reviewer.get(f"/api/workpapers/{wp['id']}/snapshots/1").json()
    assert snap["result_hash"] == out["result_hash"] and snap["version"] == 1

    assert (
        reviewer.post(f"/api/workpapers/{wp['id']}/reopen", json={"reason": ""}).status_code == 422
    )
    ro = reviewer.post(
        f"/api/workpapers/{wp['id']}/reopen", json={"reason": "Synthetic late adjustment"}
    )
    assert ro.status_code == 200 and ro.json()["status"] == "draft"
    analyst.post(f"/api/workpapers/{wp['id']}/compute")
    s2 = reviewer.post(f"/api/workpapers/{wp['id']}/sign-off").json()
    assert [x["version"] for x in s2["snapshots"]] == [1, 2]

    actions = set(
        db.scalars(select(AuditEvent.action).where(AuditEvent.object_id == uuid.UUID(wp["id"])))
    )
    assert {
        "workpaper.created",
        "workpaper.input_saved",
        "workpaper.computed",
        "workpaper.signed_off",
        "workpaper.reopened",
    } <= actions
    # Snapshots are immutable in the database.
    snap_row = db.scalar(select(WorkpaperSnapshot).where(WorkpaperSnapshot.version == 1))
    assert snap_row is not None
    try:
        snap_row.content = {"tampered": True}
        db.commit()
        raise AssertionError("snapshot update was allowed")
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        assert "immutable" in str(exc).lower() or "not allowed" in str(exc).lower()


def test_sbr_and_qfzp_papers_and_validation(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    sbr = new_paper(admin, entity.id, rpv, kind="sbr_test", title="Synthetic SBR test").json()
    put_in(admin, sbr["id"], "revenue", amount="2000000")
    put_in(admin, sbr["id"], "revenue_prior_1", amount="2000000.01")
    put_in(admin, sbr["id"], "is_qfzp", value="false")
    out = admin.post(f"/api/workpapers/{sbr['id']}/compute").json()
    got = lines(out)
    assert got["calc:test:revenue"]["value"] == "met"
    assert got["calc:test:revenue_prior_1"]["value"] == "not_met"
    assert got["calc:conditions"]["value"] == "not_met"

    q = new_paper(admin, entity.id, rpv, kind="qfzp_test", title="Synthetic QFZP test").json()
    # Missing required input is a clear 422.
    put_in(admin, q["id"], "qualifying_income", amount="1000")
    r = admin.post(f"/api/workpapers/{q['id']}/compute")
    assert r.status_code == 422 and "non_qualifying_income" in r.json()["detail"]

    # Validation.
    assert new_paper(admin, entity.id, rpv, period_end="2024-01-01").status_code == 422
    assert new_paper(admin, entity.id, rpv, period_end="2028-01-01").status_code == 422
    assert new_paper(admin, entity.id, rpv, rules_prefix="Bad Prefix").status_code == 422
    ct = new_paper(admin, entity.id, rpv).json()
    assert put_in(admin, ct["id"], "x", category="made_up", amount="1").status_code == 422
    assert put_in(admin, ct["id"], "x", amount="1", value="true").status_code == 422
    assert put_in(admin, ct["id"], "Bad-Key", amount="1").status_code == 422
    bad_block = [{"kind": "source_block", "source_block_id": str(uuid.uuid4())}]
    assert put_in(admin, ct["id"], "x", amount="1", evidence=bad_block).status_code == 422
    assert put_in(admin, ct["id"], "x", amount="1.12345").status_code == 422
    # A pack without the rule the formula needs explains which rule is missing.
    thin = ct_pack(admin, [r for r in demo_tax.rules() if not r["rule_key"].endswith("rate_bands")])
    p = new_paper(admin, entity.id, thin).json()
    put_in(admin, p["id"], "accounting_profit", amount="1")
    r = admin.post(f"/api/workpapers/{p['id']}/compute")
    assert r.status_code == 422 and "syn.ct.rate_bands" in r.json()["detail"]
    assert admin.delete(f"/api/workpapers/{p['id']}/inputs/accounting_profit").status_code == 200
    assert admin.delete(f"/api/workpapers/{p['id']}/inputs/accounting_profit").status_code == 404


def test_workpaper_roles_and_tenant_isolation(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    assert new_paper(viewer, entity.id, rpv).status_code == 403
    wp = new_paper(admin, entity.id, rpv).json()
    assert put_in(viewer, wp["id"], "accounting_profit", amount="1").status_code == 403
    assert viewer.post(f"/api/workpapers/{wp['id']}/compute").status_code == 403
    assert viewer.get(f"/api/workpapers/{wp['id']}").status_code == 200
    assert len(viewer.get("/api/workpapers").json()) == 1

    other = login(tenant_b.users[Role.ORG_ADMIN])
    other_entity = make_entity(db, tenant_b)
    other_rpv = ct_pack(other)
    # Foreign entity, foreign pack, foreign workpaper and a guessed id are all 404.
    assert new_paper(other, entity.id, other_rpv).status_code == 404
    assert new_paper(other, other_entity.id, rpv).status_code == 404
    for path in ("", "/compute", "/sign-off", "/snapshots/1"):
        method = other.get if path in ("", "/snapshots/1") else other.post
        assert method(f"/api/workpapers/{wp['id']}{path}").status_code == 404
    assert put_in(other, wp["id"], "accounting_profit", amount="1").status_code == 404
    assert other.delete(f"/api/workpapers/{wp['id']}/inputs/accounting_profit").status_code == 404
    assert (
        other.post(f"/api/workpapers/{wp['id']}/reopen", json={"reason": "Synthetic"}).status_code
        == 404
    )
    assert other.get(f"/api/workpapers/{uuid.uuid4()}").status_code == 404
    assert other.get("/api/workpapers").json() == []
    # Evidence from another tenant cannot be cited.
    analyst_b = login(tenant_b.users[Role.ANALYST])
    foreign_doc = ready_version_id(analyst_b)
    fb = analyst_b.get(f"/api/document-versions/{foreign_doc}/blocks").json()["items"][0]
    cite = [{"kind": "source_block", "source_block_id": fb["id"]}]
    assert (
        put_in(admin, wp["id"], "accounting_profit", amount="1", evidence=cite).status_code == 422
    )
    v = version_of(upload(analyst_b, other_entity, TB_CSV, filename="tb.csv", kind="trial_balance"))
    analyst_b.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": TB_MAPPING})
    imp = admin.post(
        f"/api/workpapers/{wp['id']}/import-trial-balance",
        json={
            "dataset_version_id": v["id"],
            "lines": [
                {
                    "line_key": "accounting_profit",
                    "label": "x",
                    "account_codes": ["4000"],
                    "sign": "credit",
                }
            ],
        },
    )
    assert imp.status_code == 422


def test_pillar_two_paper_through_the_api(tenant_a: Tenant, db: Session) -> None:
    """Golden case 1 of tests/golden/pillar_two.json, entered through the API."""
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    wp = new_paper(
        admin, entity.id, rpv, kind="pillar_two", title="Synthetic P2", rules_prefix="syn.p2"
    ).json()
    for key, cat, amt in [
        ("revenue_year_1", "input", "700000000"),
        ("revenue_year_2", "input", "650000000"),
        ("income_ae", "globe_income", "10000000"),
        ("taxes_ae", "covered_taxes", "900000"),
        ("payroll_ae", "payroll", "5000000"),
        ("assets_ae", "tangible_assets", "20000000"),
    ]:
        assert put_in(admin, wp["id"], key, category=cat, amount=amt).status_code == 200
    put_in(admin, wp["id"], "ready_entity_list", category="readiness", value="true")
    out = admin.post(f"/api/workpapers/{wp['id']}/compute")
    assert out.status_code == 200, out.text
    got = lines(out.json())
    assert got["calc:scope"]["value"] == "in_scope"
    assert Decimal(got["calc:AE:top_up"]["amount"]) == Decimal("435000")
    assert got["calc:readiness"]["value"] == "1/4"
    bad = put_in(admin, wp["id"], "income", category="globe_income", amount="1")
    assert bad.status_code == 200
    r = admin.post(f"/api/workpapers/{wp['id']}/compute")
    assert r.status_code == 422 and "country code" in r.json()["detail"]
