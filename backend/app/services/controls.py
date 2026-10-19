"""Internal controls (E3): risk-control matrix, tests, deficiencies, certification.

Testers record design and operating effectiveness tests with the sample size they chose
and evidence (document source blocks or dataset rows). An ineffective conclusion opens a
deficiency. Only a reviewer or admin classifies a deficiency (deficiency, significant
deficiency, material weakness), always with a rationale; the product never proposes a
class. Management's certification for a period lists the testing and every open
deficiency, and cannot be signed off while any open deficiency is unclassified.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AssuranceObject,
    Control,
    ControlCertification,
    ControlConclusion,
    ControlDeficiency,
    ControlProcess,
    ControlRisk,
    ControlTest,
    ControlTestKind,
    ControlTestStatus,
    DeficiencyStatus,
    LegalEntity,
    Task,
    TaskSource,
    User,
)
from app.schemas import (
    CertificationIn,
    ClassifyIn,
    ControlIn,
    ControlRiskIn,
    ControlTestCompleteIn,
    ControlTestIn,
    DeficiencyIn,
    DeficiencyRemediationIn,
    ProcessIn,
)
from app.services import assurance as sign
from app.services import audit
from app.services import tb as tbs
from app.services.assurance import AssuranceConflict, AssuranceError
from app.services.workpapers import WorkpaperError, resolve_evidence

CERT = AssuranceObject.CERTIFICATION


def _record(
    db: Session, org_id: uuid.UUID, actor: User, action: str, kind: str, oid: uuid.UUID, **m: Any
) -> None:
    audit.record(
        db, org_id=org_id, actor_id=actor.id, action=action, object_type=kind, object_id=oid, meta=m
    )


# ---------------------------------------------------------------- matrix


def create_process(
    db: Session, entity: LegalEntity, body: ProcessIn, actor: User
) -> ControlProcess:
    tbs.require_member(db, entity.org_id, body.owner_id)
    p = ControlProcess(
        org_id=entity.org_id,
        entity_id=entity.id,
        name=body.name.strip(),
        description=body.description.strip(),
        owner_id=body.owner_id,
    )
    db.add(p)
    db.flush()
    _record(db, p.org_id, actor, "control_process.created", "control_process", p.id)
    return p


def save_risk(
    db: Session,
    p: ControlProcess,
    body: ControlRiskIn,
    actor: User,
    risk: ControlRisk | None = None,
) -> ControlRisk:
    if any(r.ref == body.ref and r is not risk for r in p.risks):
        raise AssuranceError(f"Risk {body.ref} already exists in this process.")
    r = risk or ControlRisk(org_id=p.org_id)
    r.ref, r.description, r.rating = body.ref, body.description.strip(), body.rating
    r.assertions = [a.value for a in dict.fromkeys(body.assertions)]
    if risk is None:
        p.risks.append(r)
    db.flush()
    _record(db, p.org_id, actor, "control_risk.saved", "control_risk", r.id, ref=r.ref)
    return r


def delete_risk(db: Session, p: ControlProcess, r: ControlRisk, actor: User) -> None:
    for c in p.controls:
        c.risk_ids = [x for x in c.risk_ids if x != str(r.id)]
    p.risks.remove(r)
    db.flush()
    _record(db, p.org_id, actor, "control_risk.deleted", "control_risk", r.id, ref=r.ref)


def save_control(
    db: Session, p: ControlProcess, body: ControlIn, actor: User, control: Control | None = None
) -> Control:
    if any(c.ref == body.ref and c is not control for c in p.controls):
        raise AssuranceError(f"Control {body.ref} already exists in this process.")
    tbs.require_member(db, p.org_id, body.owner_id)
    risk_ids = {r.id for r in p.risks}
    if any(rid not in risk_ids for rid in body.risk_ids):
        raise AssuranceError("Link only risks of this process.")
    c = control or Control(org_id=p.org_id)
    c.ref, c.title, c.description = body.ref, body.title.strip(), body.description.strip()
    c.key, c.nature, c.automation, c.frequency = (
        body.key,
        body.nature,
        body.automation,
        body.frequency,
    )
    c.owner_id = body.owner_id
    c.risk_ids = [str(x) for x in dict.fromkeys(body.risk_ids)]
    if control is None:
        p.controls.append(c)
    db.flush()
    _record(db, p.org_id, actor, "control.saved", "control", c.id, ref=c.ref)
    return c


def latest(c: Control, kind: ControlTestKind) -> ControlConclusion | None:
    done = [t for t in c.tests if t.kind is kind and t.status is ControlTestStatus.COMPLETED]
    return done[-1].conclusion if done else None


def _concl(c: Control, kind: ControlTestKind) -> str | None:
    v = latest(c, kind)
    return v.value if v else None


def unmitigated(p: ControlProcess) -> list[uuid.UUID]:
    covered = {rid for c in p.controls for rid in c.risk_ids}
    return [r.id for r in p.risks if str(r.id) not in covered]


# ---------------------------------------------------------------- tests


def _evidence(db: Session, org_id: uuid.UUID, body: ControlTestIn) -> list[dict[str, Any]]:
    try:
        return resolve_evidence(db, org_id, body.evidence)
    except WorkpaperError as exc:
        raise AssuranceError(str(exc)) from exc


def add_test(db: Session, c: Control, body: ControlTestIn, actor: User) -> ControlTest:
    t = ControlTest(
        org_id=c.org_id,
        kind=body.kind,
        period_start=body.period_start,
        period_end=body.period_end,
        procedure=body.procedure.strip(),
        sample_size=body.sample_size,
        evidence=_evidence(db, c.org_id, body),
        tester_id=actor.id,
    )
    c.tests.append(t)
    db.flush()
    _record(
        db, c.org_id, actor, "control_test.created", "control_test", t.id, test_kind=t.kind.value
    )
    return t


def update_test(db: Session, t: ControlTest, body: ControlTestIn, actor: User) -> None:
    if t.status is ControlTestStatus.COMPLETED:
        raise AssuranceConflict("A completed test cannot be changed.")
    t.kind, t.period_start, t.period_end = body.kind, body.period_start, body.period_end
    t.procedure, t.sample_size = body.procedure.strip(), body.sample_size
    t.evidence = _evidence(db, t.org_id, body)
    db.flush()
    _record(db, t.org_id, actor, "control_test.updated", "control_test", t.id)


def complete_test(
    db: Session, t: ControlTest, body: ControlTestCompleteIn, actor: User
) -> ControlDeficiency | None:
    if t.status is ControlTestStatus.COMPLETED:
        raise AssuranceConflict("The test is already completed.")
    if not t.evidence:
        raise AssuranceError("Attach evidence before concluding.")
    if body.exceptions > t.sample_size and t.kind is ControlTestKind.OPERATING:
        raise AssuranceError("There cannot be more exceptions than items tested.")
    t.status, t.conclusion, t.exceptions = (
        ControlTestStatus.COMPLETED,
        body.conclusion,
        body.exceptions,
    )
    t.rationale, t.completed_at = body.rationale.strip(), now()
    if t.tester_id is None:
        t.tester_id = actor.id
    db.flush()
    _record(
        db,
        t.org_id,
        actor,
        "control_test.completed",
        "control_test",
        t.id,
        conclusion=body.conclusion.value,
        exceptions=body.exceptions,
    )
    if body.conclusion is not ControlConclusion.INEFFECTIVE:
        return None
    c = t.control
    return raise_deficiency(
        db,
        c,
        DeficiencyIn(
            control_id=c.id,
            test_id=t.id,
            title=f"{c.ref}: {t.kind.value} test concluded ineffective"[:300],
            description=t.rationale,
        ),
        actor,
    )


# ---------------------------------------------------------------- deficiencies


def raise_deficiency(db: Session, c: Control, body: DeficiencyIn, actor: User) -> ControlDeficiency:
    if body.test_id is not None and body.test_id not in {t.id for t in c.tests}:
        raise AssuranceError("That test belongs to another control.")
    d = ControlDeficiency(
        org_id=c.org_id,
        control_id=c.id,
        test_id=body.test_id,
        title=body.title.strip(),
        description=body.description.strip(),
        created_by_id=actor.id,
    )
    d.control = c
    db.add(d)
    db.flush()
    _record(db, c.org_id, actor, "deficiency.raised", "control_deficiency", d.id)
    return d


def classify(db: Session, d: ControlDeficiency, body: ClassifyIn, actor: User) -> None:
    if d.status is not DeficiencyStatus.OPEN:
        raise AssuranceConflict("Only an open deficiency can be classified.")
    previous = d.classification.value if d.classification else None
    d.classification, d.rationale = body.classification, body.rationale.strip()
    d.classified_by_id, d.classified_at = actor.id, now()
    db.flush()
    _record(
        db,
        d.org_id,
        actor,
        "deficiency.classified",
        "control_deficiency",
        d.id,
        **{"from": previous, "to": body.classification.value},
    )


def remediation(
    db: Session, d: ControlDeficiency, body: DeficiencyRemediationIn, actor: User
) -> Task:
    if d.status is not DeficiencyStatus.OPEN:
        raise AssuranceConflict("The deficiency is already remediated.")
    if d.remediation_task_id is not None:
        raise AssuranceConflict("A remediation task already exists.")
    tbs.require_member(db, d.org_id, body.owner_id)
    task = Task(
        org_id=d.org_id,
        source_kind=TaskSource.CONTROL_REMEDIATION,
        source_id=d.id,
        entity_id=d.control.process.entity_id,
        title=(body.title.strip() or f"Remediate {d.control.ref}: {d.title}")[:300],
        owner_id=body.owner_id,
        due_date=body.due_date,
        created_by_id=actor.id,
    )
    db.add(task)
    db.flush()
    d.remediation_task_id = task.id
    db.flush()
    _record(db, d.org_id, actor, "deficiency.remediation_assigned", "control_deficiency", d.id)
    return task


def remediated(db: Session, d: ControlDeficiency, note: str, actor: User) -> None:
    if d.status is not DeficiencyStatus.OPEN:
        raise AssuranceConflict("The deficiency is already remediated.")
    d.status, d.remediation_note = DeficiencyStatus.REMEDIATED, note.strip()
    db.flush()
    _record(db, d.org_id, actor, "deficiency.remediated", "control_deficiency", d.id)


def deficiencies(
    db: Session, org_id: uuid.UUID, entity_id: uuid.UUID | None = None
) -> list[ControlDeficiency]:
    stmt = select(ControlDeficiency).where(ControlDeficiency.org_id == org_id)
    if entity_id is not None:
        stmt = (
            stmt.join(Control, Control.id == ControlDeficiency.control_id)
            .join(ControlProcess, ControlProcess.id == Control.process_id)
            .where(ControlProcess.entity_id == entity_id)
        )
    return list(db.scalars(stmt.order_by(ControlDeficiency.created_at)).unique())


# ---------------------------------------------------------------- certification


def create_cert(
    db: Session, entity: LegalEntity, body: CertificationIn, actor: User
) -> ControlCertification:
    if body.period_end < body.period_start:
        raise AssuranceError("The period ends before it starts.")
    c = ControlCertification(
        org_id=entity.org_id,
        entity_id=entity.id,
        period_start=body.period_start,
        period_end=body.period_end,
        statement=body.statement.strip(),
        created_by_id=actor.id,
    )
    db.add(c)
    db.flush()
    _record(db, c.org_id, actor, "certification.created", CERT.value, c.id)
    return c


def set_statement(db: Session, c: ControlCertification, text: str, actor: User) -> None:
    sign.changed(c)
    c.statement = text.strip()
    db.flush()
    _record(db, c.org_id, actor, "certification.statement_set", CERT.value, c.id)


def cert_view(db: Session, c: ControlCertification) -> dict[str, Any]:
    procs = list(
        db.scalars(
            select(ControlProcess).where(
                ControlProcess.org_id == c.org_id, ControlProcess.entity_id == c.entity_id
            )
        ).unique()
    )
    controls = [k for p in procs for k in p.controls]

    def in_period(t: ControlTest) -> bool:
        return (
            t.status is ControlTestStatus.COMPLETED
            and t.period_end >= c.period_start
            and t.period_start <= c.period_end
        )

    tested = [k for k in controls if any(in_period(t) for t in k.tests)]
    ineffective = [
        k
        for k in controls
        if any(in_period(t) and t.conclusion is ControlConclusion.INEFFECTIVE for t in k.tests)
    ]
    open_defs = [
        d for d in deficiencies(db, c.org_id, c.entity_id) if d.status is DeficiencyStatus.OPEN
    ]
    return {
        "controls": len(controls),
        "key_controls": sum(1 for k in controls if k.key),
        "tested": len(tested),
        "ineffective": len(ineffective),
        "open": open_defs,
        "unclassified": sum(1 for d in open_defs if d.classification is None),
        "rows": [
            [p.name, k.ref, k.title, "yes" if k.key else ""]
            + [_concl(k, ControlTestKind.DESIGN), _concl(k, ControlTestKind.OPERATING)]
            for p in procs
            for k in p.controls
        ],
    }


def sign_off_cert(db: Session, c: ControlCertification, actor: User) -> Any:
    v = cert_view(db, c)
    if not c.statement:
        raise AssuranceError("Write management's statement before signing off.")
    if v["unclassified"]:
        raise AssuranceError(f"Classify the {v['unclassified']} open deficiency(ies) first.")
    content = {
        "title": "Management certification on internal controls",
        "subtitle": f"{c.entity.name} · {c.period_start} to {c.period_end}",
        "is_demo": c.is_demo,
        "warnings": [],
        "meta": [
            ["Controls", v["controls"]],
            ["Key controls", v["key_controls"]],
            ["Controls tested in the period", v["tested"]],
            ["Controls with an ineffective test", v["ineffective"]],
            ["Open deficiencies", len(v["open"])],
            ["Statement", c.statement],
        ],
        "sections": [
            {
                "title": "Controls",
                "columns": ["Process", "Control", "Title", "Key", "Design", "Operating"],
                "rows": v["rows"],
            },
            {
                "title": "Open deficiencies",
                "columns": ["Control", "Title", "Classification", "Rationale"],
                "rows": [
                    [d.control.ref, d.title, d.classification.value if d.classification else None]
                    + [d.rationale]
                    for d in v["open"]
                ],
            },
        ],
        "notes": [
            "Classifications are the judgement of the people named in the audit log; the "
            "product does not classify deficiencies."
        ],
    }
    return sign.sign_off(db, c, CERT, content, actor)
