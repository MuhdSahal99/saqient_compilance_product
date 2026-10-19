"""Phase F3: FS draft, IFRS 16 lease and depreciation recalculation (engine 1.6.0).

Synthetic parameters (app/demo_tax.py): syn.audit amounts to 2 decimals half up,
FS note tolerance 1, depreciation tolerance 1.

Fixed asset register, period 2026-01-01 to 2026-03-31, hand-checked:
  A1 SL 12000/60m from 2025-01: 15 months → 3000; 12 months at Dec 2025 → 2400;
     charge 600. Recorded 3000 / 600 → no finding.
  A2 SL (10000 − 1000)/36m from 2026-02: 2 months → 500; charge 500. Recorded 450 / 450
     → both differ by −50.
  A3 RB 20% on 10000 from 2025-04: 12 months → 8000 NBV → 2000; 9 months at Dec 2025
     → 10000 × 0.2 × 9/12 = 1500; charge 500. Recorded 2000 / 500.50 → within 1.
  A4 SL without a life → missing life.   A5 method "units" → unknown method.
  A6 RB without a rate → missing rate.   A8 life "five" → unreadable.
  A7 SL 6000/60m from 2024-01, disposed 2025-12-15: 24 months both ends → 2400,
     charge 0. Recorded 2400 / 100 → charge differs by 100.

FS draft from the lead schedule trial balances (see tests/test_lead_schedules.py) with
expenses mapped to X: CY assets 200000, liabilities 120000, equity 50000, income
400000, expenses 370000 → profit 30000, balanced. PY 120000, 80000, 50000, 300000,
310000 → profit −10000, balanced. Note A 200000.40 agrees; note B 119000 differs by
−1000.00; note Z has no face line.

Lease: 1000 a period in arrears, 3 periods at 10%: PV = 1000 × 2.4868519… = 2486.85;
ROU 2486.85 + 100 − 50 = 2536.85; depreciation 845.62; first interest 248.69; total
interest 513.15.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.engine.fa_checks import accumulated, months_in_use
from app.models import Role
from tests.conftest import Tenant, login
from tests.test_datasets import make_entity
from tests.test_einvoices import checklist, findings, req, results
from tests.test_engagements import new_engagement
from tests.test_lead_schedules import CY_TB, MAPPINGS, PY_TB, SCHEDULES
from tests.test_vat_review import dataset
from tests.test_workpapers import ct_pack, lines, new_paper, put_in

REGISTER = (
    b"asset_id,description,method,cost,residual_value,useful_life_months,rate,"
    b"acquisition_date,disposal_date,recorded_accumulated,recorded_charge,currency\n"
    b"A1,Synthetic laptop,straight_line,12000,0,60,,2025-01-15,,3000,600,AED\n"
    b"A2,Synthetic van,Straight Line,10000,1000,36,,2026-02-10,,450,450,AED\n"
    b"A3,Synthetic press,reducing_balance,10000,0,,0.2,2025-04-01,,2000,500.50,AED\n"
    b"A4,Synthetic desk,straight_line,500,0,,,2025-06-01,,100,25,AED\n"
    b"A5,Synthetic drill,units,800,0,24,,2025-06-01,,100,25,AED\n"
    b"A6,Synthetic lathe,reducing_balance,900,0,,,2025-06-01,,100,25,AED\n"
    b"A7,Synthetic server,straight_line,6000,0,60,,2024-01-01,2025-12-15,2400,100,AED\n"
    b"A8,Synthetic chair,straight_line,300,0,five,,2025-06-01,,10,5,AED\n"
)


def test_depreciation_helpers_by_hand() -> None:
    assert months_in_use(date(2025, 1, 15), date(2026, 3, 31), None, 60) == 15
    assert months_in_use(date(2025, 1, 15), date(2026, 3, 31), None, 10) == 10
    assert months_in_use(date(2026, 5, 1), date(2026, 3, 31), None, None) == 0
    assert months_in_use(date(2024, 1, 1), date(2026, 3, 31), date(2025, 12, 15), 60) == 24
    sl = accumulated("straight_line", Decimal(12000), Decimal(0), 60, None, 15)
    assert sl == Decimal(3000)
    assert accumulated("straight_line", Decimal(100), Decimal(0), 2, None, 5) == 100
    rb = accumulated("reducing_balance", Decimal(10000), Decimal(0), None, Decimal("0.2"), 18)
    assert rb == Decimal(10000) - Decimal(8000) * Decimal("0.9")  # 8000 then half a year


def test_depreciation_through_a_review(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    v = dataset(reviewer, entity, "fixed_assets", REGISTER)
    cv = checklist(
        reviewer, [req("FA-1", {"type": "depreciation_recalc", "rules_prefix": "syn.audit"})]
    )
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "Synthetic depreciation",
            "checklist_version_id": cv,
            "dataset_version_ids": [v],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    rid = r.json()["id"]
    res = results(reviewer, rid)["FA-1"]
    assert res["outcome"] == "exceptions_found", res
    assert any("Unverified" in w for w in res["meta"]["warnings"])
    assert res["meta"]["period"] == ["2026-01-01", "2026-03-31"]
    fs = findings(reviewer, rid)

    def rows(key: str, col: str = "") -> list[Any]:
        got = [f for f in fs if f["finding_key"] == key]
        assert len(got) == 1, (key, [f["finding_key"] for f in fs])
        ev = got[0]["evidence"][0]
        dicts = [dict(zip(ev["columns"], row, strict=True)) for row in ev["rows"]]
        return [d[col] for d in dicts] if col else [d["row_id"] for d in dicts]

    assert {f["finding_key"] for f in fs} == {
        "accumulated_difference",
        "charge_difference",
        "missing_life",
        "missing_rate",
        "unknown_method",
        "unreadable",
    }
    assert rows("accumulated_difference") == [2]
    assert rows("accumulated_difference", "_expected") == ["500.00"]
    assert rows("accumulated_difference", "_difference") == ["-50.00"]
    assert rows("charge_difference") == [2, 7]
    assert rows("charge_difference", "_expected") == ["500.00", "0.00"]
    assert rows("missing_life") == [4]
    assert rows("unknown_method") == [5]
    assert rows("missing_rate") == [6]
    assert rows("unreadable") == [8]


def test_fs_draft_from_an_engagement(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    viewer = login(tenant_a.users[Role.VIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    cy = dataset(analyst, entity, "trial_balance", CY_TB)
    py = dataset(analyst, entity, "trial_balance", PY_TB)
    eid = new_engagement(reviewer, entity.id).json()["id"]
    setup = {
        "cy_tb_version_id": cy,
        "py_tb_version_id": py,
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.audit",
    }
    assert reviewer.put(f"/api/engagements/{eid}/setup", json=setup).status_code == 200
    schedules = [*SCHEDULES, {"code": "X", "name": "Expenses", "section": "expense"}]
    assert (
        analyst.put(f"/api/engagements/{eid}/lead-schedules", json={"schedules": schedules})
    ).status_code == 200
    mappings = [*MAPPINGS, {"account_code": "5000", "lead_code": "X"}]
    assert (
        analyst.put(f"/api/engagements/{eid}/account-mappings", json={"mappings": mappings})
    ).status_code == 200
    # FS drafts belong to an engagement, never to the tax endpoint.
    assert new_paper(analyst, entity.id, rpv, kind="fs_draft").status_code == 422
    assert (
        viewer.post(
            f"/api/engagements/{eid}/workpapers", json={"kind": "fs_draft", "title": "x"}
        ).status_code
        == 403
    )
    r = analyst.post(
        f"/api/engagements/{eid}/workpapers",
        json={"kind": "fs_draft", "title": "Synthetic FS draft"},
    )
    assert r.status_code == 201, r.text
    paper = r.json()
    wid = paper["id"]
    got = lines(paper)
    assert Decimal(got["fs_liability_b_cy"]["amount"]) == -120000  # the TB sign
    assert got["fs_asset_a_cy"]["evidence"][0]["dataset_version_id"] == cy
    assert Decimal(got["calc:face_b_cy"]["amount"]) == 120000  # presented
    assert Decimal(got["calc:total_assets_cy"]["amount"]) == 200000
    assert Decimal(got["calc:total_expenses_cy"]["amount"]) == 370000
    assert Decimal(got["calc:profit_cy"]["amount"]) == 30000
    assert Decimal(got["calc:profit_py"]["amount"]) == -10000
    assert got["calc:balance_check_cy"]["value"] == "balanced"
    assert got["calc:balance_check_py"]["value"] == "balanced"

    for key, amount in (("note_a", "200000.40"), ("note_b", "119000"), ("note_z", "5")):
        put = put_in(analyst, wid, key, category="note", amount=amount)
        assert put.status_code == 200, put.text
    assert put_in(analyst, wid, "note_c", category="current_year", amount="1").status_code == 200
    assert analyst.post(f"/api/workpapers/{wid}/compute").status_code == 422  # wrong category
    assert put_in(analyst, wid, "note_c", category="note", amount="50000").status_code == 200
    out = analyst.post(f"/api/workpapers/{wid}/compute")
    assert out.status_code == 200, out.text
    got = lines(out.json())
    assert got["calc:note_a_check"]["value"] == "agrees"
    assert got["calc:note_b_check"]["value"] == "differs by -1000.00"
    assert got["calc:note_z_check"]["value"] == "no face line"
    assert got["calc:note_c_check"]["value"] == "agrees"
    assert out.json()["warnings"]

    # Reloading replaces the face lines and keeps the notes.
    assert viewer.post(f"/api/workpapers/{wid}/reload-leads").status_code == 403
    reload = analyst.post(f"/api/workpapers/{wid}/reload-leads")
    assert reload.status_code == 200, reload.text
    got = lines(reload.json())
    assert "note_a" in got and got["calc:note_a_check"]["value"] == "agrees"


def test_lease_workpaper(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    r = new_paper(
        analyst,
        entity.id,
        rpv,
        kind="lease_ifrs16",
        title="Synthetic office lease",
        rules_prefix="syn.audit",
    )
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    assert analyst.post(f"/api/workpapers/{wid}/compute").status_code == 422  # no inputs
    for key, body in (
        ("payment", {"amount": "1000"}),
        ("periods", {"value": "3"}),
        ("rate_per_period", {"value": "0.1"}),
        ("timing", {"value": "arrears"}),
        ("initial_direct_costs", {"amount": "100"}),
        ("incentives", {"amount": "50"}),
    ):
        assert put_in(analyst, wid, key, **body).status_code == 200
    out = analyst.post(f"/api/workpapers/{wid}/compute")
    assert out.status_code == 200, out.text
    got = lines(out.json())
    assert Decimal(got["calc:lease_liability"]["amount"]) == Decimal("2486.85")
    assert Decimal(got["calc:rou_asset"]["amount"]) == Decimal("2536.85")
    assert Decimal(got["calc:depreciation_per_period"]["amount"]) == Decimal("845.62")
    assert Decimal(got["calc:first_period_interest"]["amount"]) == Decimal("248.69")
    assert Decimal(got["calc:total_interest"]["amount"]) == Decimal("513.15")
    assert put_in(analyst, wid, "timing", value="sometimes").status_code == 200
    assert analyst.post(f"/api/workpapers/{wid}/compute").status_code == 422
    other = login(tenant_b.users[Role.ORG_ADMIN])
    assert other.get(f"/api/workpapers/{wid}").status_code == 404
    assert other.post(f"/api/workpapers/{wid}/compute").status_code == 404
