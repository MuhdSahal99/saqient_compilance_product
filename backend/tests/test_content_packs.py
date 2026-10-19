"""Phase F1/F2: content packs are synthetic drafts and install as draft content."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.orm import Session

from app.models import Role
from app.packs import DATA, SYNTHETIC_DISCLAIMER, PackError, catalog, load
from tests.conftest import Tenant, login

# Words that would make a synthetic pack look like real regulation.
FORBIDDEN = ("article ", "art. ", "federal decree", "cabinet resolution", "circular no", "law no")


def test_shipped_packs_are_synthetic_drafts() -> None:
    packs = catalog()
    assert set(packs) == {
        "aml-cft",
        "banking-ifrs9",
        "ifrs17",
        "listed-disclosures",
        "esg-s1-s2",
        "esr-ubo",
    }
    for p in packs.values():
        m = p.manifest
        assert m.status == "draft" and m.synthetic and m.disclaimer == SYNTHETIC_DISCLAIMER
        assert m.open_questions
        if m.rules:
            assert all(r.todo and r.source_url is None for r in m.rules.rules)
    for path in DATA.glob("*.json"):
        text = path.read_text().casefold()
        assert not any(f in text for f in FORBIDDEN), path.name


def test_manifest_validation() -> None:
    good = json.loads((DATA / "esr-ubo.json").read_bytes())
    load(json.dumps(good).encode())
    for change in (
        {"disclaimer": "Real guidance"},
        {"status": "published"},
        {"synthetic": False},
        {"open_questions": []},
    ):
        with pytest.raises(PackError):
            load(json.dumps({**good, **change}).encode())
    bad_check = json.loads(json.dumps(good))
    bad_check["checklists"][0]["requirements"][0]["check_config"] = {"type": "regex", "p": ".*"}
    with pytest.raises(PackError):
        load(json.dumps(bad_check).encode())
    dup = json.loads(json.dumps(good))
    reqs = dup["checklists"][0]["requirements"]
    reqs.append(reqs[0])
    with pytest.raises(PackError):
        load(json.dumps(dup).encode())
    aml = json.loads((DATA / "aml-cft.json").read_bytes())
    aml["rules"]["rules"][0]["todo"] = ""
    with pytest.raises(PackError):
        load(json.dumps(aml).encode())


def test_install_as_drafts(tenant_a: Tenant, tenant_b: Tenant, db: Session) -> None:
    admin = login(tenant_a.users[Role.ORG_ADMIN])
    reviewer = login(tenant_a.users[Role.REVIEWER])
    viewer = login(tenant_a.users[Role.VIEWER])
    other = login(tenant_b.users[Role.ORG_ADMIN])
    listed = viewer.get("/api/content-packs")
    assert listed.status_code == 200 and len(listed.json()) == 6
    assert viewer.get("/api/content-packs/nope").status_code == 404
    assert reviewer.post("/api/content-packs/aml-cft/install").status_code == 403
    r = admin.post("/api/content-packs/aml-cft/install")
    assert r.status_code == 201, r.text
    inst = r.json()["installs"][0]
    assert inst["pack_version"] == "0.1.0" and len(inst["manifest_sha256"]) == 64
    assert admin.post("/api/content-packs/aml-cft/install").status_code == 409
    v = admin.get(f"/api/checklist-versions/{inst['checklist_version_ids'][0]}").json()
    assert v["state"] == "draft" and v["disclaimer"] == SYNTHETIC_DISCLAIMER
    assert len(v["requirements"]) == 10
    rp = admin.get(f"/api/rule-pack-versions/{inst['rule_pack_version_id']}").json()
    assert rp["state"] == "draft"
    assert all(rule["verification_status"] == "draft" for rule in rp["rules"])
    # Installs are per organisation.
    assert other.get("/api/content-packs/aml-cft").json()["installs"] == []
    assert (
        other.get(f"/api/checklist-versions/{inst['checklist_version_ids'][0]}").status_code == 404
    )
    assert other.post("/api/content-packs/aml-cft/install").status_code == 201
    log = admin.get("/api/audit-events", params={"action": "content_pack.installed"})
    assert log.status_code == 200
