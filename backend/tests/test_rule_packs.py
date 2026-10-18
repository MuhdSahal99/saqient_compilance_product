from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import Session

from app.models import Role, RuleVerification
from app.services import rule_packs as svc
from tests.conftest import ApiClient, Tenant, login

SOURCE = "https://example.org/synthetic-source"


def _rule(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "rule_key": "demo.standard_rate",
        "title": "Demonstration standard rate",
        "value_type": "decimal",
        "value": "0.07",
        "unit": "ratio",
        "effective_from": "2020-01-01",
        "effective_to": None,
        "source_url": SOURCE,
    }
    base.update(over)
    return base


def _pack(client: ApiClient, jurisdiction: str = "AE", name: str = "Test pack") -> dict:  # type: ignore[type-arg]
    resp = client.post("/api/rule-packs", json={"name": name, "jurisdiction": jurisdiction})
    assert resp.status_code == 201, resp.text
    return resp.json()  # type: ignore[no-any-return]


def test_lifecycle_draft_publish_immutable_new_draft(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(admin)
    assert pack["versions"][0]["state"] == "draft"
    vid = pack["versions"][0]["id"]
    rules = [
        _rule(effective_to="2023-12-31"),
        _rule(value="0.09", effective_from="2024-01-01"),
        _rule(rule_key="demo.registration_threshold", value="375000.00", unit="AED"),
    ]
    put = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": rules})
    assert put.status_code == 200, put.text
    assert put.json()["unverified_count"] == 3
    pub = admin.post(f"/api/rule-pack-versions/{vid}/publish")
    assert pub.status_code == 200 and pub.json()["state"] == "published"
    # Published versions are immutable.
    again = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": rules})
    assert again.status_code == 409
    draft = admin.post(f"/api/rule-packs/{pack['id']}/drafts")
    assert draft.status_code == 201
    assert draft.json()["version_number"] == 2 and len(draft.json()["rules"]) == 3
    assert admin.post(f"/api/rule-packs/{pack['id']}/drafts").status_code == 409
    pub2 = admin.post(f"/api/rule-pack-versions/{draft.json()['id']}/publish")
    assert pub2.status_code == 200
    states = {
        v["version_number"]: v["state"]
        for v in admin.get(f"/api/rule-packs/{pack['id']}").json()["versions"]
    }
    assert states == {1: "archived", 2: "published"}


def test_resolve_by_date_and_unverified_warning(tenant_a: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(admin)
    vid = pack["versions"][0]["id"]
    admin.put(
        f"/api/rule-pack-versions/{vid}/rules",
        json={
            "rules": [
                _rule(effective_to="2023-12-31"),
                _rule(value="0.09", effective_from="2024-01-01"),
            ]
        },
    )
    v = uuid.UUID(vid)
    old = svc.resolve(db, tenant_a.org.id, v, "demo.standard_rate", date(2023, 6, 30))
    new = svc.resolve(db, tenant_a.org.id, v, "demo.standard_rate", date(2024, 1, 1))
    assert old.value == Decimal("0.07") and isinstance(old.value, Decimal)
    assert new.value == Decimal("0.09")
    assert new.warning() is not None and "Unverified rule" in new.warning()  # type: ignore[operator]
    assert new.snapshot()["verification_status"] == "draft"
    with pytest.raises(svc.RuleNotFound):
        svc.resolve(db, tenant_a.org.id, v, "demo.standard_rate", date(2019, 12, 31))


def test_resolve_is_tenant_scoped(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    vid = _pack(admin)["versions"][0]["id"]
    admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [_rule()]})
    with pytest.raises(svc.RuleNotFound):
        svc.resolve(db, tenant_b.org.id, uuid.UUID(vid), "demo.standard_rate", date(2024, 1, 1))


def test_only_admin_verifies_and_rules_for_verification(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    vid = _pack(admin)["versions"][0]["id"]
    detail = admin.put(
        f"/api/rule-pack-versions/{vid}/rules",
        json={
            "rules": [
                _rule(),
                _rule(rule_key="demo.no_source", source_url=None),
                _rule(rule_key="demo.open_question", todo="Which period does this apply to?"),
            ]
        },
    ).json()
    ids = {r["rule_key"]: r["id"] for r in detail["rules"]}
    reviewer = login(tenant_a.users[Role.REVIEWER])
    assert reviewer.post(f"/api/rules/{ids['demo.standard_rate']}/verify").status_code == 403
    assert (
        login(tenant_a.users[Role.ANALYST])
        .post(f"/api/rules/{ids['demo.standard_rate']}/verify")
        .status_code
        == 403
    )
    ok = admin.post(f"/api/rules/{ids['demo.standard_rate']}/verify")
    assert ok.status_code == 200
    assert ok.json()["verification_status"] == "verified"
    assert ok.json()["verified_by_name"] == tenant_a.users[Role.ORG_ADMIN].full_name
    assert admin.post(f"/api/rules/{ids['demo.no_source']}/verify").status_code == 422
    assert admin.post(f"/api/rules/{ids['demo.open_question']}/verify").status_code == 422
    back = admin.post(f"/api/rules/{ids['demo.standard_rate']}/unverify")
    assert back.json()["verification_status"] == "draft"
    assert back.json()["verified_at"] is None


def test_verification_survives_only_unchanged_edits(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    vid = _pack(admin)["versions"][0]["id"]
    d = admin.put(
        f"/api/rule-pack-versions/{vid}/rules",
        json={"rules": [_rule(), _rule(rule_key="demo.other")]},
    ).json()
    for r in d["rules"]:
        assert admin.post(f"/api/rules/{r['id']}/verify").status_code == 200
    d2 = admin.put(
        f"/api/rule-pack-versions/{vid}/rules",
        json={"rules": [_rule(), _rule(rule_key="demo.other", value="0.08")]},
    ).json()
    status = {r["rule_key"]: r["verification_status"] for r in d2["rules"]}
    assert status == {"demo.standard_rate": "verified", "demo.other": "draft"}


def test_synthetic_rules_cannot_be_verified(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(admin, jurisdiction="SYNTHETIC")
    assert pack["is_synthetic"] is True
    d = admin.put(
        f"/api/rule-pack-versions/{pack['versions'][0]['id']}/rules", json={"rules": [_rule()]}
    ).json()
    resp = admin.post(f"/api/rules/{d['rules'][0]['id']}/verify")
    assert resp.status_code == 422 and "Synthetic" in resp.json()["detail"]


@pytest.mark.parametrize(
    "rules,detail",
    [
        ([_rule(value="0.07%")], "not a valid decimal"),
        ([_rule(value_type="integer", value="1.5")], "not an integer"),
        ([_rule(value_type="boolean", value="yes")], "true or false"),
        ([_rule(value_type="date", value="31/12/2024")], "not a valid date"),
        ([_rule(value="NaN")], "finite"),
        ([_rule(effective_to="2019-01-01")], "before"),
        ([_rule(), _rule(effective_from="2021-01-01")], "overlap"),
        (
            [
                _rule(effective_to="2021-12-31"),
                _rule(effective_from="2022-01-01", value_type="integer", value="1"),
            ],
            "same type",
        ),
        ([_rule(rule_key="Bad Key")], None),
        ([_rule(source_url="http://insecure.example")], None),
    ],
)
def test_rule_validation(
    tenant_a: Tenant, rules: list[dict[str, object]], detail: str | None
) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    vid = _pack(admin)["versions"][0]["id"]
    resp = admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": rules})
    assert resp.status_code == 422, resp.text
    if detail:
        assert detail in resp.json()["detail"]


def test_publish_needs_rules_and_names_are_unique(tenant_a: Tenant) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(admin)
    assert (
        admin.post(f"/api/rule-pack-versions/{pack['versions'][0]['id']}/publish").status_code
        == 422
    )
    assert (
        admin.post("/api/rule-packs", json={"name": "Test pack", "jurisdiction": "AE"}).status_code
        == 409
    )
    assert (
        admin.post("/api/rule-packs", json={"name": "X", "jurisdiction": "UAE"}).status_code == 422
    )


@pytest.mark.parametrize("role", [Role.ANALYST, Role.VIEWER])
def test_analyst_and_viewer_read_only(tenant_a: Tenant, role: Role) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(admin)
    vid = pack["versions"][0]["id"]
    user = login(tenant_a.users[role])
    assert user.get("/api/rule-packs").status_code == 200
    assert user.get(f"/api/rule-pack-versions/{vid}").status_code == 200
    assert user.post("/api/rule-packs", json={"name": "Y", "jurisdiction": "AE"}).status_code == 403
    assert (
        user.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [_rule()]}).status_code
        == 403
    )
    assert user.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 403
    assert user.post(f"/api/rule-packs/{pack['id']}/drafts").status_code == 403


def test_reviewer_can_author(tenant_a: Tenant) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    vid = _pack(reviewer)["versions"][0]["id"]
    assert (
        reviewer.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [_rule()]}).status_code
        == 200
    )
    assert reviewer.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 200


def test_rule_packs_are_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant) -> None:
    a = login(tenant_a.users[Role.ORG_ADMIN])
    pack = _pack(a)
    vid = pack["versions"][0]["id"]
    rid = a.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [_rule()]}).json()["rules"][
        0
    ]["id"]
    b = login(tenant_b.users[Role.ORG_ADMIN])
    assert b.get("/api/rule-packs").json() == []
    assert b.get(f"/api/rule-packs/{pack['id']}").status_code == 404
    assert b.get(f"/api/rule-pack-versions/{vid}").status_code == 404
    assert (
        b.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [_rule()]}).status_code == 404
    )
    assert b.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 404
    assert b.post(f"/api/rule-packs/{pack['id']}/drafts").status_code == 404
    assert b.post(f"/api/rules/{rid}/verify").status_code == 404
    assert b.post(f"/api/rules/{rid}/unverify").status_code == 404
    assert b.get(f"/api/rule-packs/{uuid.uuid4()}").status_code == 404


def test_rule_verification_enum_matches_api() -> None:
    assert {v.value for v in RuleVerification} == {"draft", "verified"}
