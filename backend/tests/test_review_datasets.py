"""Reviews with dataset inputs (engine deterministic-1.1.0) through the API."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import ReportSnapshot, Role
from tests.conftest import ApiClient, Tenant, login, ready_version_id
from tests.test_datasets import GL_CSV, GL_MAPPING, make_entity, upload, version_of

SOURCE = "https://example.org/synthetic-source"

DATA_REQUIREMENTS: list[dict[str, Any]] = [
    {
        "code": "DATA-01",
        "title": "Large journal lines",
        "severity": "medium",
        "check_config": {
            "type": "threshold",
            "dataset": "general_ledger",
            "field": "amount",
            "use_absolute": True,
            "flag_if": "gte",
            "value": {"rule": "demo.large_entry"},
        },
    },
    {
        "code": "DATA-02",
        "title": "Weekend postings",
        "severity": "low",
        "check_config": {
            "type": "date_rule",
            "dataset": "general_ledger",
            "field": "posting_date",
            "rule": "not_weekend",
            "weekend_days": ["sat", "sun"],
        },
    },
    {
        "code": "DATA-03",
        "title": "Duplicate journal lines",
        "severity": "medium",
        "check_config": {
            "type": "duplicate",
            "dataset": "general_ledger",
            "keys": ["entry_id", "account_code"],
        },
    },
    {
        "code": "DATA-04",
        "title": "GL agrees to trial balance",
        "severity": "high",
        "check_config": {
            "type": "reconcile",
            "left": {"dataset": "general_ledger", "group_by": ["account_code"], "sum": "amount"},
            "right": {"dataset": "trial_balance", "group_by": ["account_code"], "sum": "balance"},
        },
    },
    {
        "code": "TXT-01",
        "title": "Retention clause",
        "severity": "low",
        "check_config": {"type": "required_text", "phrases": ["retention"]},
    },
]


def data_checklist(reviewer: ApiClient) -> str:
    r = reviewer.post(
        "/api/checklists",
        json={
            "name": "Synthetic GL checks",
            "kind": "internal_policy",
            "requirements": DATA_REQUIREMENTS,
        },
    )
    assert r.status_code == 201, r.text
    pub = reviewer.post(f"/api/checklist-versions/{r.json()['id']}/publish")
    assert pub.status_code == 200, pub.text
    return str(r.json()["id"])


def rule_pack(admin: ApiClient, publish: bool = True) -> str:
    pack = admin.post("/api/rule-packs", json={"name": "Synthetic GL rules", "jurisdiction": "AE"})
    assert pack.status_code == 201, pack.text
    vid = pack.json()["versions"][0]["id"]
    rule = {
        "rule_key": "demo.large_entry",
        "title": "Synthetic large entry threshold",
        "value_type": "decimal",
        "value": "1000.00",
        "unit": "AED",
        "effective_from": "2020-01-01",
        "effective_to": None,
        "source_url": SOURCE,
    }
    assert (
        admin.put(f"/api/rule-pack-versions/{vid}/rules", json={"rules": [rule]}).status_code == 200
    )
    if publish:
        assert admin.post(f"/api/rule-pack-versions/{vid}/publish").status_code == 200
    return str(vid)


def gl_version(tenant: Tenant, db: Session, confirm: bool = True) -> str:
    analyst = login(tenant.users[Role.ANALYST])
    entity = make_entity(db, tenant)
    v = version_of(
        upload(
            analyst,
            entity,
            GL_CSV,
            period_start="2025-01-01",
            period_end="2025-12-31",
            allow_duplicate="true",
        )
    )
    if confirm:
        r = analyst.put(f"/api/dataset-versions/{v['id']}/mapping", json={"mapping": GL_MAPPING})
        assert r.json()["status"] == "ready", r.text
    return str(v["id"])


def test_review_on_a_general_ledger(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    analyst = login(tenant_a.users[Role.ANALYST])
    cv = data_checklist(reviewer)
    rpv = rule_pack(login(tenant_a.users[Role.ORG_ADMIN]))
    dv = gl_version(tenant_a, db)

    r = analyst.post(
        "/api/reviews",
        json={
            "title": "FY25 GL",
            "checklist_version_id": cv,
            "dataset_version_ids": [dv],
            "rule_pack_version_id": rpv,
        },
    )
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["document_id"] is None and review["status"] == "in_review"
    assert [d["kind"] for d in review["datasets"]] == ["general_ledger"]
    assert review["datasets"][0]["row_count"] == 4
    assert review["rule_pack_name"] == "Synthetic GL rules"
    run = review["latest_run"]
    assert run["engine_version"] == "deterministic-1.4.0"
    snap = run["inputs_snapshot"]
    assert snap["as_of_date"] == "2025-12-31" and snap["as_of_source"] == "dataset_period_end"
    assert snap["datasets"][0]["dataset_version_id"] == dv
    assert len(snap["datasets"][0]["parquet_sha256"]) == 64
    assert any(w.startswith("DATA-01: Unverified rule") for w in run["warnings"])

    results = {
        x["requirement_code"]: x for x in analyst.get(f"/api/reviews/{review['id']}/results").json()
    }
    # GL amounts: -1250, 1250, -0.50, 0.50. |amount| >= 1000 on rows 1 and 2.
    assert results["DATA-01"]["outcome"] == "exceptions_found"
    assert results["DATA-01"]["evidence"][0]["row_ids"] == [1, 2]
    assert results["DATA-01"]["meta"]["rules"][0]["value"] == "1000.00"
    # 2025-01-05 (rows 1, 2) is a Sunday.
    assert results["DATA-02"]["outcome"] == "exceptions_found"
    assert results["DATA-02"]["evidence"][0]["row_ids"] == [1, 2]
    assert results["DATA-03"]["outcome"] == "no_exceptions"
    assert results["DATA-04"]["outcome"] == "not_applicable"
    assert not results["DATA-04"]["needs_attention"]
    assert "trial_balance" in results["DATA-04"]["message"]
    assert results["TXT-01"]["outcome"] == "not_applicable"
    assert all(len(x["result_hash"]) == 64 for x in results.values())

    findings = analyst.get("/api/findings", params={"review_id": review["id"]}).json()["items"]
    assert sorted(f["requirement_code"] for f in findings) == ["DATA-01", "DATA-02"]
    f1 = next(f for f in findings if f["requirement_code"] == "DATA-01")
    assert f1["automated_outcome"] == "exceptions_found"
    assert f1["evidence"][0]["type"] == "dataset_rows"
    assert f1["title"].startswith("Data exceptions found")

    # A rerun on the same inputs gives the same result hashes.
    rerun = reviewer.post(f"/api/reviews/{review['id']}/runs")
    assert rerun.status_code == 200, rerun.text
    again = {
        x["requirement_code"]: x["result_hash"]
        for x in analyst.get(f"/api/reviews/{review['id']}/results").json()
    }
    assert again == {k: v["result_hash"] for k, v in results.items()}

    # Sign-off: the report names the dataset version and the exception rows.
    for f in findings:
        d = reviewer.post(
            f"/api/findings/{f['id']}/decision",
            json={"decision": "confirmed", "rationale": "Checked with finance."},
        )
        assert d.status_code == 200, d.text
    report = reviewer.post(f"/api/reviews/{review['id']}/signoff")
    assert report.status_code == 200, report.text
    snapshot = db.get(ReportSnapshot, uuid.UUID(report.json()["id"]))
    assert snapshot is not None
    scope = snapshot.content["scope"]
    assert scope["document_title"] is None and scope["datasets"][0]["row_count"] == 4
    assert scope["rule_pack"]["name"] == "Synthetic GL rules"
    html = reviewer.get(f"/api/reports/{report.json()['id']}/export?format=html").text
    assert "General ledger: FY25 GL — version 1" in html
    assert "rows 1, 2" in html and "-1250.0000" in html
    csv_text = reviewer.get(f"/api/reports/{report.json()['id']}/export?format=csv").text
    assert "amount=-1250.0000" in csv_text
    pdf = reviewer.get(f"/api/reports/{report.json()['id']}/export?format=pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_document_and_dataset_review_and_rule_from_no_pack(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    cv = data_checklist(reviewer)
    dv = gl_version(tenant_a, db)
    doc = ready_version_id(reviewer)
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "Both",
            "checklist_version_id": cv,
            "document_version_id": doc,
            "dataset_version_ids": [dv],
            "as_of_date": "2025-06-30",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["latest_run"]["inputs_snapshot"]["as_of_source"] == "review"
    results = {
        x["requirement_code"]: x
        for x in reviewer.get(f"/api/reviews/{r.json()['id']}/results").json()
    }
    # The text check runs on the document; the rule-based check has no pack to read.
    assert results["TXT-01"]["outcome"] in ("match_found", "no_match_found")
    assert results["DATA-01"]["outcome"] == "not_applicable"
    assert "no rule pack" in results["DATA-01"]["message"]
    assert results["DATA-01"]["needs_attention"]


def test_review_input_validation(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    cv = data_checklist(reviewer)
    ready = gl_version(tenant_a, db)
    unmapped = gl_version(tenant_a, db, confirm=False)
    draft = rule_pack(login(tenant_a.users[Role.ORG_ADMIN]), publish=False)

    def create(**body: Any) -> Any:
        return reviewer.post(
            "/api/reviews", json={"title": "x", "checklist_version_id": cv, **body}
        )

    assert create().status_code == 422  # no document and no datasets
    assert create(dataset_version_ids=[ready, ready]).status_code == 422
    r = create(dataset_version_ids=[unmapped])
    assert r.status_code == 422 and "ready" in r.json()["detail"]
    r = create(dataset_version_ids=[ready], rule_pack_version_id=draft)
    assert r.status_code == 422 and "published rule pack" in r.json()["detail"]


def test_viewer_cannot_create_dataset_reviews(tenant_a: Tenant, db: Session) -> None:
    cv = data_checklist(login(tenant_a.users[Role.REVIEWER]))
    dv = gl_version(tenant_a, db)
    viewer = login(tenant_a.users[Role.VIEWER])
    r = viewer.post(
        "/api/reviews", json={"title": "x", "checklist_version_id": cv, "dataset_version_ids": [dv]}
    )
    assert r.status_code == 403


def test_dataset_reviews_are_tenant_isolated(
    tenant_a: Tenant, tenant_b: Tenant, db: Session
) -> None:
    dv_a = gl_version(tenant_a, db)
    rpv_a = rule_pack(login(tenant_a.users[Role.ORG_ADMIN]))
    reviewer_b = login(tenant_b.users[Role.REVIEWER])
    cv_b = data_checklist(reviewer_b)
    dv_b = gl_version(tenant_b, db)
    base = {"title": "x", "checklist_version_id": cv_b}
    r = reviewer_b.post("/api/reviews", json={**base, "dataset_version_ids": [dv_a]})
    assert r.status_code == 404
    r = reviewer_b.post(
        "/api/reviews", json={**base, "dataset_version_ids": [dv_b], "rule_pack_version_id": rpv_a}
    )
    assert r.status_code == 404
    own = reviewer_b.post("/api/reviews", json={**base, "dataset_version_ids": [dv_b]})
    assert own.status_code == 201
    a = login(tenant_a.users[Role.REVIEWER])
    assert a.get(f"/api/reviews/{own.json()['id']}").status_code == 404
    assert a.get(f"/api/reviews/{own.json()['id']}/results").status_code == 404
