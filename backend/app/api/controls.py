"""Internal controls (Phase E3): RCM, tests, deficiencies and management certification."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import select

from app.api.assurance_common import export, guard, name_of, sign_off_out, versions_out
from app.deps import DB, Ctx, Decider, Writer, get_owned_or_404
from app.models import (
    AssuranceObject,
    Control,
    ControlCertification,
    ControlDeficiency,
    ControlProcess,
    ControlRisk,
    ControlTest,
    ControlTestKind,
    DeficiencyStatus,
    LegalEntity,
)
from app.schemas import (
    CertificationIn,
    CertificationOut,
    ClassifyIn,
    ControlIn,
    ControlOut,
    ControlRiskIn,
    ControlRiskOut,
    ControlTestCompleteIn,
    ControlTestIn,
    ControlTestOut,
    DeficiencyIn,
    DeficiencyOut,
    DeficiencyRemediationIn,
    ProcessIn,
    ProcessOut,
    ReasonIn,
    RemediatedIn,
    StatementIn,
)
from app.services import assurance
from app.services import controls as svc

router = APIRouter(tags=["internal controls"])
CERT = AssuranceObject.CERTIFICATION


def test_out(db: DB, t: ControlTest) -> ControlTestOut:
    return ControlTestOut(
        id=t.id,
        control_id=t.control_id,
        kind=t.kind,
        period_start=t.period_start,
        period_end=t.period_end,
        procedure=t.procedure,
        sample_size=t.sample_size,
        exceptions=t.exceptions,
        evidence=t.evidence,
        status=t.status,
        conclusion=t.conclusion,
        rationale=t.rationale,
        tester_name=name_of(db, t.tester_id),
        completed_at=t.completed_at,
    )


def control_out(db: DB, c: Control, open_counts: dict[uuid.UUID, int]) -> ControlOut:
    return ControlOut(
        id=c.id,
        process_id=c.process_id,
        ref=c.ref,
        title=c.title,
        description=c.description,
        key=c.key,
        nature=c.nature,
        automation=c.automation,
        frequency=c.frequency,
        owner_id=c.owner_id,
        owner_name=name_of(db, c.owner_id),
        risk_ids=[uuid.UUID(x) for x in c.risk_ids],
        design=svc.latest(c, ControlTestKind.DESIGN),
        operating=svc.latest(c, ControlTestKind.OPERATING),
        tests=[test_out(db, t) for t in c.tests],
        open_deficiencies=open_counts.get(c.id, 0),
    )


def process_out(db: DB, p: ControlProcess) -> ProcessOut:
    counts: dict[uuid.UUID, int] = {}
    for d in svc.deficiencies(db, p.org_id, p.entity_id):
        if d.status is DeficiencyStatus.OPEN:
            counts[d.control_id] = counts.get(d.control_id, 0) + 1
    return ProcessOut(
        id=p.id,
        entity_id=p.entity_id,
        entity_name=p.entity.name,
        name=p.name,
        description=p.description,
        owner_id=p.owner_id,
        owner_name=name_of(db, p.owner_id),
        is_demo=p.is_demo,
        risks=[ControlRiskOut.model_validate(r) for r in p.risks],
        controls=[control_out(db, c, counts) for c in p.controls],
        unmitigated_risk_ids=svc.unmitigated(p),
    )


def deficiency_out(db: DB, d: ControlDeficiency) -> DeficiencyOut:
    return DeficiencyOut(
        id=d.id,
        control_id=d.control_id,
        control_ref=d.control.ref,
        control_title=d.control.title,
        test_id=d.test_id,
        title=d.title,
        description=d.description,
        classification=d.classification,
        rationale=d.rationale,
        classified_by_name=name_of(db, d.classified_by_id),
        classified_at=d.classified_at,
        status=d.status,
        remediation_task_id=d.remediation_task_id,
        remediation_note=d.remediation_note,
        created_at=d.created_at,
    )


def _process(db: DB, ctx: Ctx, pid: uuid.UUID) -> ControlProcess:
    return get_owned_or_404(db, ControlProcess, pid, ctx.org.id)


def _control(db: DB, ctx: Ctx, cid: uuid.UUID) -> Control:
    return get_owned_or_404(db, Control, cid, ctx.org.id)


# ---------------------------------------------------------------- processes, risks, controls


@router.get(
    "/control-processes",
    response_model=list[ProcessOut],
    summary="Risk-control matrix",
    description="Processes with their risks, controls, links, latest test results and gaps.",
)
def list_processes(db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None) -> list[ProcessOut]:
    stmt = select(ControlProcess).where(ControlProcess.org_id == ctx.org.id)
    if entity_id:
        stmt = stmt.where(ControlProcess.entity_id == entity_id)
    return [process_out(db, p) for p in db.scalars(stmt.order_by(ControlProcess.name)).unique()]


@router.post(
    "/control-processes",
    response_model=ProcessOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a process",
)
def create_process(body: ProcessIn, db: DB, ctx: Writer) -> ProcessOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    p = guard(lambda: svc.create_process(db, entity, body, ctx.user))
    db.commit()
    return process_out(db, p)


@router.get("/control-processes/{process_id}", response_model=ProcessOut, summary="Get a process")
def get_process(process_id: uuid.UUID, db: DB, ctx: Ctx) -> ProcessOut:
    return process_out(db, _process(db, ctx, process_id))


@router.post(
    "/control-processes/{process_id}/risks",
    response_model=ProcessOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a risk",
)
def add_risk(process_id: uuid.UUID, body: ControlRiskIn, db: DB, ctx: Writer) -> ProcessOut:
    p = _process(db, ctx, process_id)
    guard(lambda: svc.save_risk(db, p, body, ctx.user))
    db.commit()
    return process_out(db, p)


@router.put("/control-risks/{risk_id}", response_model=ProcessOut, summary="Update a risk")
def update_risk(risk_id: uuid.UUID, body: ControlRiskIn, db: DB, ctx: Writer) -> ProcessOut:
    r = get_owned_or_404(db, ControlRisk, risk_id, ctx.org.id)
    guard(lambda: svc.save_risk(db, r.process, body, ctx.user, r))
    db.commit()
    return process_out(db, r.process)


@router.delete("/control-risks/{risk_id}", response_model=ProcessOut, summary="Delete a risk")
def delete_risk(risk_id: uuid.UUID, db: DB, ctx: Writer) -> ProcessOut:
    r = get_owned_or_404(db, ControlRisk, risk_id, ctx.org.id)
    p = r.process
    guard(lambda: svc.delete_risk(db, p, r, ctx.user))
    db.commit()
    return process_out(db, p)


@router.post(
    "/control-processes/{process_id}/controls",
    response_model=ProcessOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add a control",
)
def add_control(process_id: uuid.UUID, body: ControlIn, db: DB, ctx: Writer) -> ProcessOut:
    p = _process(db, ctx, process_id)
    guard(lambda: svc.save_control(db, p, body, ctx.user))
    db.commit()
    return process_out(db, p)


@router.put("/controls/{control_id}", response_model=ProcessOut, summary="Update a control")
def update_control(control_id: uuid.UUID, body: ControlIn, db: DB, ctx: Writer) -> ProcessOut:
    c = _control(db, ctx, control_id)
    guard(lambda: svc.save_control(db, c.process, body, ctx.user, c))
    db.commit()
    return process_out(db, c.process)


# ---------------------------------------------------------------- tests


@router.post(
    "/controls/{control_id}/tests",
    response_model=ControlTestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Plan a design or operating effectiveness test",
    description="The tester sets the sample size; evidence is source blocks or dataset rows.",
)
def add_test(control_id: uuid.UUID, body: ControlTestIn, db: DB, ctx: Writer) -> ControlTestOut:
    c = _control(db, ctx, control_id)
    t = guard(lambda: svc.add_test(db, c, body, ctx.user))
    db.commit()
    return test_out(db, t)


@router.put("/control-tests/{test_id}", response_model=ControlTestOut, summary="Update a test")
def update_test(test_id: uuid.UUID, body: ControlTestIn, db: DB, ctx: Writer) -> ControlTestOut:
    t = get_owned_or_404(db, ControlTest, test_id, ctx.org.id)
    guard(lambda: svc.update_test(db, t, body, ctx.user))
    db.commit()
    return test_out(db, t)


@router.post(
    "/control-tests/{test_id}/complete",
    response_model=ControlTestOut,
    summary="Conclude a test",
    description="Needs evidence and a rationale. An ineffective conclusion opens a deficiency.",
)
def complete_test(
    test_id: uuid.UUID, body: ControlTestCompleteIn, db: DB, ctx: Writer
) -> ControlTestOut:
    t = get_owned_or_404(db, ControlTest, test_id, ctx.org.id)
    guard(lambda: svc.complete_test(db, t, body, ctx.user))
    db.commit()
    return test_out(db, t)


# ---------------------------------------------------------------- deficiencies


@router.get("/deficiencies", response_model=list[DeficiencyOut], summary="List deficiencies")
def list_deficiencies(db: DB, ctx: Ctx, entity_id: uuid.UUID | None = None) -> list[DeficiencyOut]:
    return [deficiency_out(db, d) for d in svc.deficiencies(db, ctx.org.id, entity_id)]


@router.post(
    "/deficiencies",
    response_model=DeficiencyOut,
    status_code=status.HTTP_201_CREATED,
    summary="Raise a deficiency",
)
def raise_deficiency(body: DeficiencyIn, db: DB, ctx: Writer) -> DeficiencyOut:
    c = _control(db, ctx, body.control_id)
    d = guard(lambda: svc.raise_deficiency(db, c, body, ctx.user))
    db.commit()
    return deficiency_out(db, d)


def _deficiency(db: DB, ctx: Ctx, did: uuid.UUID) -> ControlDeficiency:
    return get_owned_or_404(db, ControlDeficiency, did, ctx.org.id)


@router.post(
    "/deficiencies/{deficiency_id}/classify",
    response_model=DeficiencyOut,
    summary="Classify a deficiency",
    description="A reviewer or admin's judgement, with a rationale. The product never classifies.",
)
def classify(deficiency_id: uuid.UUID, body: ClassifyIn, db: DB, ctx: Decider) -> DeficiencyOut:
    d = _deficiency(db, ctx, deficiency_id)
    guard(lambda: svc.classify(db, d, body, ctx.user))
    db.commit()
    return deficiency_out(db, d)


@router.post(
    "/deficiencies/{deficiency_id}/remediation",
    response_model=DeficiencyOut,
    summary="Assign remediation",
    description="Creates a task with an owner and due date.",
)
def assign_remediation(
    deficiency_id: uuid.UUID, body: DeficiencyRemediationIn, db: DB, ctx: Decider
) -> DeficiencyOut:
    d = _deficiency(db, ctx, deficiency_id)
    guard(lambda: svc.remediation(db, d, body, ctx.user))
    db.commit()
    return deficiency_out(db, d)


@router.post(
    "/deficiencies/{deficiency_id}/remediated",
    response_model=DeficiencyOut,
    summary="Mark remediated",
)
def mark_remediated(
    deficiency_id: uuid.UUID, body: RemediatedIn, db: DB, ctx: Decider
) -> DeficiencyOut:
    d = _deficiency(db, ctx, deficiency_id)
    guard(lambda: svc.remediated(db, d, body.note, ctx.user))
    db.commit()
    return deficiency_out(db, d)


# ---------------------------------------------------------------- certification


def cert_out(db: DB, c: ControlCertification) -> CertificationOut:
    v = svc.cert_view(db, c)
    return CertificationOut(
        id=c.id,
        entity_id=c.entity_id,
        entity_name=c.entity.name,
        period_start=c.period_start,
        period_end=c.period_end,
        statement=c.statement,
        controls=v["controls"],
        key_controls=v["key_controls"],
        tested=v["tested"],
        ineffective=v["ineffective"],
        open_deficiencies=[deficiency_out(db, d) for d in v["open"]],
        unclassified=v["unclassified"],
        is_demo=c.is_demo,
        sign_off=sign_off_out(db, c),
        versions=versions_out(db, c.org_id, CERT, c.id),
    )


def _cert(db: DB, ctx: Ctx, cid: uuid.UUID) -> ControlCertification:
    return get_owned_or_404(db, ControlCertification, cid, ctx.org.id)


@router.get(
    "/control-certifications", response_model=list[CertificationOut], summary="List certifications"
)
def list_certs(db: DB, ctx: Ctx) -> list[CertificationOut]:
    rows = db.scalars(
        select(ControlCertification)
        .where(ControlCertification.org_id == ctx.org.id)
        .order_by(ControlCertification.period_end.desc())
    ).unique()
    return [cert_out(db, c) for c in rows]


@router.post(
    "/control-certifications",
    response_model=CertificationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Start a management certification",
)
def create_cert(body: CertificationIn, db: DB, ctx: Writer) -> CertificationOut:
    entity = get_owned_or_404(db, LegalEntity, body.entity_id, ctx.org.id)
    c = guard(lambda: svc.create_cert(db, entity, body, ctx.user))
    db.commit()
    return cert_out(db, c)


@router.get(
    "/control-certifications/{cert_id}",
    response_model=CertificationOut,
    summary="Get a certification",
)
def get_cert(cert_id: uuid.UUID, db: DB, ctx: Ctx) -> CertificationOut:
    return cert_out(db, _cert(db, ctx, cert_id))


@router.put(
    "/control-certifications/{cert_id}/statement",
    response_model=CertificationOut,
    summary="Set the statement",
)
def set_statement(cert_id: uuid.UUID, body: StatementIn, db: DB, ctx: Writer) -> CertificationOut:
    c = _cert(db, ctx, cert_id)
    guard(lambda: svc.set_statement(db, c, body.statement, ctx.user))
    db.commit()
    return cert_out(db, c)


@router.post(
    "/control-certifications/{cert_id}/prepare",
    response_model=CertificationOut,
    summary="Mark prepared",
)
def prepare_cert(cert_id: uuid.UUID, db: DB, ctx: Writer) -> CertificationOut:
    c = _cert(db, ctx, cert_id)
    guard(lambda: assurance.prepare(db, c, CERT, ctx.user))
    db.commit()
    return cert_out(db, c)


@router.post(
    "/control-certifications/{cert_id}/sign-off",
    response_model=CertificationOut,
    summary="Certify",
    description="Needs a statement and every open deficiency classified; freezes a snapshot.",
)
def sign_off_cert(cert_id: uuid.UUID, db: DB, ctx: Decider) -> CertificationOut:
    c = _cert(db, ctx, cert_id)
    guard(lambda: svc.sign_off_cert(db, c, ctx.user))
    db.commit()
    return cert_out(db, c)


@router.post(
    "/control-certifications/{cert_id}/reopen", response_model=CertificationOut, summary="Reopen"
)
def reopen_cert(cert_id: uuid.UUID, body: ReasonIn, db: DB, ctx: Decider) -> CertificationOut:
    c = _cert(db, ctx, cert_id)
    guard(lambda: assurance.reopen(db, c, CERT, body.reason, ctx.user))
    db.commit()
    return cert_out(db, c)


@router.get(
    "/control-certifications/{cert_id}/versions/{version}/export",
    summary="Export a signed certification",
    response_class=Response,
)
def export_cert(
    cert_id: uuid.UUID,
    version: int,
    db: DB,
    ctx: Ctx,
    fmt: str = Query(alias="format", pattern="^(html|pdf|csv)$"),
) -> Response:
    c = _cert(db, ctx, cert_id)
    return export(db, ctx, CERT, c.id, version, fmt)
