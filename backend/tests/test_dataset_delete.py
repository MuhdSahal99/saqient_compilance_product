"""Deleting a wrongly uploaded dataset or version, and refusing when the data is in use."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, DatasetVersion, Job, JobKind, JobStatus, ReviewDataset, Role
from app.services import datasets as svc
from app.storage import get_storage
from tests.conftest import Tenant, login
from tests.test_datasets import CSV, GL_CSV, GL_MAPPING, make_entity, upload, version_of
from tests.test_review_datasets import data_checklist, rule_pack

OTHER_CSV = GL_CSV + b"JE-3,2025-01-07,1100,Synthetic extra,1.00,\n"


def _ready(tenant: Tenant, db: Session, data: bytes = GL_CSV) -> tuple[str, str]:
    analyst = login(tenant.users[Role.ANALYST])
    created = upload(analyst, make_entity(db, tenant), data, allow_duplicate="true")
    vid = version_of(created)["id"]
    r = analyst.put(f"/api/dataset-versions/{vid}/mapping", json={"mapping": GL_MAPPING})
    assert r.json()["status"] == "ready", r.text
    return str(created.json()["id"]), str(vid)


def test_analyst_deletes_a_wrong_upload(tenant_a: Tenant, db: Session) -> None:
    ds_id, vid = _ready(tenant_a, db)
    row = db.get(DatasetVersion, uuid.UUID(vid))
    assert row is not None
    keys = [row.raw_storage_key, row.parquet_storage_key]
    db.expire_all()

    analyst = login(tenant_a.users[Role.ANALYST])
    assert analyst.delete(f"/api/datasets/{ds_id}").status_code == 204
    assert analyst.get(f"/api/datasets/{ds_id}").status_code == 404
    assert analyst.get(f"/api/dataset-versions/{vid}").status_code == 404
    assert all(d["id"] != ds_id for d in analyst.get("/api/datasets").json())
    storage = get_storage()
    for key in keys:
        assert key is not None and not storage.exists(key)

    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.action == "dataset.deleted", AuditEvent.object_id == uuid.UUID(ds_id)
        )
    )
    assert event is not None
    assert event.meta["kind"] == "general_ledger"
    assert event.meta["versions"][0]["version"] == 1

    # The same file can be uploaded again without the duplicate warning.
    again = upload(analyst, make_entity(db, tenant_a), GL_CSV, name="Corrected")
    assert again.status_code == 201, again.text


def test_delete_one_version_and_the_last_version(tenant_a: Tenant, db: Session) -> None:
    ds_id, v1 = _ready(tenant_a, db)
    analyst = login(tenant_a.users[Role.ANALYST])
    r = analyst.post(f"/api/datasets/{ds_id}/versions", files={"file": ("gl.csv", OTHER_CSV, CSV)})
    assert r.status_code == 201, r.text
    v2 = r.json()["versions"][-1]["id"]

    assert analyst.delete(f"/api/dataset-versions/{v2}").status_code == 204
    detail = analyst.get(f"/api/datasets/{ds_id}").json()
    assert [v["id"] for v in detail["versions"]] == [v1]
    assert detail["latest_version"]["id"] == v1

    # Deleting the only remaining version removes the dataset.
    assert analyst.delete(f"/api/dataset-versions/{v1}").status_code == 204
    assert analyst.get(f"/api/datasets/{ds_id}").status_code == 404


def test_data_used_by_a_review_cannot_be_deleted(tenant_a: Tenant, db: Session) -> None:
    reviewer = login(tenant_a.users[Role.REVIEWER])
    ds_id, vid = _ready(tenant_a, db)
    r = reviewer.post(
        "/api/reviews",
        json={
            "title": "FY25 GL",
            "checklist_version_id": data_checklist(reviewer),
            "dataset_version_ids": [vid],
            "rule_pack_version_id": rule_pack(login(tenant_a.users[Role.ORG_ADMIN])),
        },
    )
    assert r.status_code == 201, r.text
    for url in (f"/api/datasets/{ds_id}", f"/api/dataset-versions/{vid}"):
        resp = reviewer.delete(url)
        assert resp.status_code == 409
        assert "Upload a corrected version" in resp.json()["detail"]
    assert reviewer.get(f"/api/dataset-versions/{vid}").status_code == 200

    # Finding evidence that names the version counts as use on its own.
    db.execute(delete(ReviewDataset).where(ReviewDataset.dataset_version_id == uuid.UUID(vid)))
    db.commit()
    assert svc.usage_count(db, tenant_a.org.id, [uuid.UUID(vid)]) > 0


def test_queued_processing_is_cancelled_and_running_refused(tenant_a: Tenant, db: Session) -> None:
    analyst = login(tenant_a.users[Role.ANALYST])
    ds_id, vid = _ready(tenant_a, db)
    job = Job(
        org_id=tenant_a.org.id,
        kind=JobKind.DATASET_BUILD,
        target_id=uuid.UUID(vid),
        status=JobStatus.RUNNING,
    )
    db.add(job)
    db.commit()
    resp = analyst.delete(f"/api/datasets/{ds_id}")
    assert resp.status_code == 409
    assert "processed right now" in resp.json()["detail"]

    job.status = JobStatus.QUEUED
    db.commit()
    assert analyst.delete(f"/api/datasets/{ds_id}").status_code == 204
    db.expire_all()
    assert db.get(Job, job.id).status is JobStatus.CANCELLED  # type: ignore[union-attr]


def test_delete_roles(tenant_a: Tenant, db: Session) -> None:
    viewer = login(tenant_a.users[Role.VIEWER])
    ds_id, vid = _ready(tenant_a, db)
    assert viewer.delete(f"/api/datasets/{ds_id}").status_code == 403
    assert viewer.delete(f"/api/dataset-versions/{vid}").status_code == 403
    for role in (Role.REVIEWER, Role.ORG_ADMIN):
        ds_id, vid = _ready(tenant_a, db)
        client = login(tenant_a.users[role])
        assert client.delete(f"/api/dataset-versions/{vid}").status_code == 204
        assert client.get(f"/api/datasets/{ds_id}").status_code == 404


def test_delete_is_tenant_isolated(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    ds_id, vid = _ready(tenant_a, db)
    b = login(tenant_b.users[Role.ORG_ADMIN])
    assert b.delete(f"/api/datasets/{ds_id}").status_code == 404
    assert b.delete(f"/api/dataset-versions/{vid}").status_code == 404
    assert b.delete(f"/api/datasets/{uuid.uuid4()}").status_code == 404
    assert b.delete(f"/api/dataset-versions/{uuid.uuid4()}").status_code == 404
    a = login(tenant_a.users[Role.ANALYST])
    assert a.get(f"/api/datasets/{ds_id}").status_code == 200
