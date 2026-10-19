"""Phase C3: tax loss register, workpaper postings, transfers and tax group history.

Expected amounts are worked by hand from the synthetic rules in app/demo_tax.py
(loss cap 0.70, bands 0-400000 at 0 and above at 0.12, transfer ownership 0.80,
group ownership 0.90).
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.models import Role
from tests.conftest import ApiClient, Tenant, login
from tests.test_datasets import make_entity
from tests.test_workpapers import ct_pack, lines, new_paper, put_in


def signed_paper(
    client: ApiClient, reviewer: ApiClient, entity_id: Any, rpv: str, year: int, profit: str
) -> dict[str, Any]:
    wp = new_paper(
        client,
        entity_id,
        rpv,
        title=f"Synthetic FY{year}",
        period_start=f"{year}-01-01",
        period_end=f"{year}-12-31",
    ).json()
    assert client.post(f"/api/workpapers/{wp['id']}/prefill-losses").status_code == 200
    assert put_in(client, wp["id"], "accounting_profit", amount=profit).status_code == 200
    assert client.post(f"/api/workpapers/{wp['id']}/compute").status_code == 200
    out = reviewer.post(f"/api/workpapers/{wp['id']}/sign-off")
    assert out.status_code == 200, out.text
    return out.json()  # type: ignore[no-any-return]


def test_register_from_workpapers_and_manual_entries(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    entity = make_entity(db, tenant_a)
    rpv = ct_pack(admin)

    fy24 = signed_paper(analyst, reviewer, entity.id, rpv, 2024, "-200000")
    assert analyst.post(f"/api/workpapers/{fy24['id']}/post-losses").status_code == 403
    posted = reviewer.post(f"/api/workpapers/{fy24['id']}/post-losses")
    assert posted.status_code == 200, posted.text
    created = posted.json()["created"]
    assert [(e["kind"], Decimal(e["amount"])) for e in created] == [("incurred", Decimal(200000))]
    assert created[0]["evidence"][0]["kind"] == "workpaper_line"
    assert posted.json()["warnings"] == []
    assert reviewer.post(f"/api/workpapers/{fy24['id']}/post-losses").json()["created"] == []

    # FY2025: brought forward 200000 from the register; cap 0.70 x 1000000 = 700000, so
    # all 200000 is used; taxable income 800000; tax (800000 - 400000) x 0.12 = 48000.
    fy25 = signed_paper(analyst, reviewer, entity.id, rpv, 2025, "1000000")
    got = lines(fy25)
    assert Decimal(got["losses_brought_forward"]["amount"]) == Decimal(200000)
    assert got["losses_brought_forward"]["evidence"][0]["kind"] == "loss_register"
    assert Decimal(got["calc:losses_used"]["amount"]) == Decimal(200000)
    assert Decimal(got["calc:tax"]["amount"]) == Decimal(48000)
    reviewer.post(f"/api/workpapers/{fy25['id']}/post-losses")
    reg = analyst.get(f"/api/entities/{entity.id}/tax-losses").json()
    assert Decimal(reg["balance"]) == 0
    assert [e["kind"] for e in reg["entries"]] == ["incurred", "used"]
    assert Decimal(reg["entries"][1]["signed_amount"]) == Decimal(-200000)

    body = {
        "kind": "incurred",
        "period_start": "2023-01-01",
        "period_end": "2023-12-31",
        "amount": "50000",
        "note": "Synthetic opening balance",
    }
    assert analyst.post(f"/api/entities/{entity.id}/tax-losses", json=body).status_code == 201
    too_much = {**body, "kind": "used", "amount": "50000.01"}
    assert analyst.post(f"/api/entities/{entity.id}/tax-losses", json=too_much).status_code == 422
    assert (
        analyst.post(
            f"/api/entities/{entity.id}/tax-losses", json={**body, "amount": "0"}
        ).status_code
        == 422
    )
    assert (
        analyst.post(
            f"/api/entities/{entity.id}/tax-losses", json={**body, "kind": "transferred_in"}
        ).status_code
        == 422
    )
    viewer = login(tenant_a.users[Role.VIEWER])
    assert viewer.post(f"/api/entities/{entity.id}/tax-losses", json=body).status_code == 403
    # A draft workpaper cannot be posted.
    draft = new_paper(analyst, entity.id, rpv).json()
    assert reviewer.post(f"/api/workpapers/{draft['id']}/post-losses").status_code == 422


def test_loss_transfer_conditions(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    src, dst = make_entity(db, tenant_a), make_entity(db, tenant_a)
    rpv = ct_pack(admin)
    reviewer.post(
        f"/api/entities/{src.id}/tax-losses",
        json={
            "kind": "incurred",
            "period_start": "2024-01-01",
            "period_end": "2024-12-31",
            "amount": "500000",
            "note": "Synthetic",
        },
    )
    body = {
        "from_entity_id": str(src.id),
        "to_entity_id": str(dst.id),
        "amount": "150000",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "common_ownership": "0.80",
        "same_business_continuity": True,
        "both_resident": True,
        "rule_pack_version_id": rpv,
        "rules_prefix": "syn.ct",
        "note": "Synthetic transfer",
    }
    r = reviewer.post("/api/tax-losses/transfers", json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert [e["kind"] for e in out["entries"]] == ["transferred_out", "transferred_in"]
    assert out["entries"][0]["transfer_id"] == out["entries"][1]["transfer_id"]
    assert {x["key"]: x["value"] for x in out["lines"]}["conditions"] == "met"
    assert (
        out["entries"][0]["rule_snapshots"][0]["rule_key"] == "syn.ct.loss_transfer_min_ownership"
    )
    assert out["warnings"]
    bal = lambda e: Decimal(reviewer.get(f"/api/entities/{e.id}/tax-losses").json()["balance"])  # noqa: E731
    assert (bal(src), bal(dst)) == (Decimal(350000), Decimal(150000))

    low = reviewer.post("/api/tax-losses/transfers", json={**body, "common_ownership": "0.5"})
    assert low.status_code == 422 and "ownership" in low.json()["detail"].lower()
    over = reviewer.post("/api/tax-losses/transfers", json={**body, "amount": "350000.01"})
    assert over.status_code == 422 and "available" in over.json()["detail"].lower()
    no_cont = reviewer.post(
        "/api/tax-losses/transfers", json={**body, "same_business_continuity": False}
    )
    assert no_cont.status_code == 422
    same = reviewer.post("/api/tax-losses/transfers", json={**body, "to_entity_id": str(src.id)})
    assert same.status_code == 422
    usd = make_entity(db, tenant_a, currency="USD")
    assert (
        reviewer.post(
            "/api/tax-losses/transfers", json={**body, "to_entity_id": str(usd.id)}
        ).status_code
        == 422
    )
    analyst = login(tenant_a.users[Role.ANALYST])
    assert analyst.post("/api/tax-losses/transfers", json=body).status_code == 403


def _group(admin: ApiClient) -> str:
    r = admin.post(
        "/api/tax-groups", json={"name": f"Synthetic group {uuid.uuid4().hex[:6]}", "country": "AE"}
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


def test_tax_group_history_and_test(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    analyst = login(tenant_a.users[Role.ANALYST])
    rpv = ct_pack(admin)
    parent, a, b = make_entity(db, tenant_a), make_entity(db, tenant_a), make_entity(db, tenant_a)
    b.fiscal_year_end_month = 3
    db.commit()
    gid = _group(admin)

    def add(e: Any, share: str, is_parent: bool = False, **over: Any):  # type: ignore[no-untyped-def]
        body = {
            "entity_id": str(e.id),
            "ownership_share": share,
            "is_parent": is_parent,
            "joined_on": "2025-01-01",
            **over,
        }
        return admin.post(f"/api/tax-groups/{gid}/memberships", json=body)

    assert add(parent, "1", is_parent=True).status_code == 201
    assert add(a, "0.95").status_code == 201
    mb = add(b, "0.85")
    assert mb.status_code == 201
    assert add(a, "0.95", joined_on="2025-06-01").status_code == 422  # overlaps
    assert add(make_entity(db, tenant_a), "1", is_parent=True).status_code == 422  # 2nd parent
    assert analyst.post(f"/api/tax-groups/{gid}/memberships", json={}).status_code == 403

    test = {"rule_pack_version_id": rpv, "rules_prefix": "syn.ct", "on": "2025-06-30"}
    r = analyst.post(f"/api/tax-groups/{gid}/ct-test", json=test)
    assert r.status_code == 200, r.text
    vals = {x["key"]: x["value"] for x in r.json()["lines"]}
    assert vals["test:member_1:ownership"] == "met"
    assert vals["test:member_1:year_end"] == "met"
    assert vals["test:member_2:ownership"] == "not_met"  # 0.85 < 0.90
    assert vals["test:member_2:year_end"] == "not_met"  # March year end
    assert vals["conditions"] == "not_met" and len(r.json()["result_hash"]) == 64

    end = admin.post(
        f"/api/tax-group-memberships/{mb.json()['id']}/end",
        json={"left_on": "2025-03-31", "note": "Synthetic disposal"},
    )
    assert end.status_code == 200 and end.json()["left_on"] == "2025-03-31"
    r = analyst.post(f"/api/tax-groups/{gid}/ct-test", json=test)
    assert {x["key"]: x["value"] for x in r.json()["lines"]}["conditions"] == "met"
    hist = analyst.get(f"/api/tax-groups/{gid}/memberships").json()
    assert len(hist) == 3
    early = analyst.post(f"/api/tax-groups/{gid}/ct-test", json={**test, "on": "2024-06-30"})
    assert early.status_code == 422


def test_losses_and_groups_tenant_isolation(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    rpv = ct_pack(admin)
    entity, other = make_entity(db, tenant_a), make_entity(db, tenant_a)
    gid = _group(admin)
    m = admin.post(
        f"/api/tax-groups/{gid}/memberships",
        json={
            "entity_id": str(entity.id),
            "ownership_share": "1",
            "is_parent": True,
            "joined_on": "2025-01-01",
        },
    ).json()
    wp = new_paper(admin, entity.id, rpv).json()

    b = login(tenant_b.users[Role.ORG_ADMIN])
    b_entity = make_entity(db, tenant_b)
    b_rpv = ct_pack(b)
    b_gid = _group(b)
    assert b.get(f"/api/entities/{entity.id}/tax-losses").status_code == 404
    assert (
        b.post(
            f"/api/entities/{entity.id}/tax-losses",
            json={
                "kind": "incurred",
                "period_start": "2024-01-01",
                "period_end": "2024-12-31",
                "amount": "1",
                "note": "x",
            },
        ).status_code
        == 404
    )
    assert b.post(f"/api/workpapers/{wp['id']}/post-losses").status_code == 404
    assert b.post(f"/api/workpapers/{wp['id']}/prefill-losses").status_code == 404
    transfer = {
        "from_entity_id": str(entity.id),
        "to_entity_id": str(b_entity.id),
        "amount": "1",
        "period_start": "2025-01-01",
        "period_end": "2025-12-31",
        "common_ownership": "1",
        "same_business_continuity": True,
        "both_resident": True,
        "rule_pack_version_id": b_rpv,
        "rules_prefix": "syn.ct",
        "note": "x",
    }
    assert b.post("/api/tax-losses/transfers", json=transfer).status_code == 404
    # Own entities but a foreign pack: also not found.
    own = {
        **transfer,
        "from_entity_id": str(entity.id),
        "to_entity_id": str(other.id),
        "rule_pack_version_id": b_rpv,
    }
    assert admin.post("/api/tax-losses/transfers", json=own).status_code == 404
    assert b.get(f"/api/tax-groups/{gid}/memberships").status_code == 404
    assert (
        b.post(
            f"/api/tax-groups/{gid}/memberships",
            json={"entity_id": str(b_entity.id), "ownership_share": "1", "joined_on": "2025-01-01"},
        ).status_code
        == 404
    )
    assert (
        b.post(
            f"/api/tax-groups/{b_gid}/memberships",
            json={"entity_id": str(entity.id), "ownership_share": "1", "joined_on": "2025-01-01"},
        ).status_code
        == 404
    )
    assert (
        b.post(
            f"/api/tax-group-memberships/{m['id']}/end", json={"left_on": "2025-02-01", "note": "x"}
        ).status_code
        == 404
    )
    test = {"rule_pack_version_id": rpv, "rules_prefix": "syn.ct", "on": "2025-06-30"}
    assert b.post(f"/api/tax-groups/{gid}/ct-test", json=test).status_code == 404
    assert b.get(f"/api/entities/{uuid.uuid4()}/tax-losses").status_code == 404
