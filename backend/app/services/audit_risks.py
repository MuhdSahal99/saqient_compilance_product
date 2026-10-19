"""Risk register per assertion, audit procedures and audit programmes (D4).

An audit programme is an ordinary versioned checklist of kind ``audit_programme``;
applying a published version to an engagement creates one procedure per
requirement. Reviews run on that checklist (and journal entry tests) can be linked
to the engagement, so their findings flow through the normal decision process.
A procedure is only done with a written conclusion.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.deps import now
from app.models import (
    AuditEngagement,
    AuditProcedure,
    AuditRisk,
    ChecklistKind,
    ChecklistState,
    ChecklistVersion,
    Membership,
    ProcedureStatus,
    Requirement,
    Review,
    RiskProcedure,
    User,
)
from app.schemas import ProcedureIn, ProcedureStatusIn, RiskIn
from app.services import audit
from app.services.engagements import EngagementError, require_open
from app.services.lead_schedules import schedules


def _record(
    db: Session, e: AuditEngagement, actor: User, action: str, obj: str, oid: uuid.UUID, **meta: Any
) -> None:
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action=action,
        object_type=obj,
        object_id=oid,
        meta={"engagement_id": str(e.id), **meta},
    )


def risks(db: Session, e: AuditEngagement) -> list[AuditRisk]:
    return list(
        db.scalars(
            select(AuditRisk)
            .where(AuditRisk.org_id == e.org_id, AuditRisk.engagement_id == e.id)
            .order_by(AuditRisk.ref)
        )
    )


def procedures(db: Session, e: AuditEngagement) -> list[AuditProcedure]:
    return list(
        db.scalars(
            select(AuditProcedure)
            .where(AuditProcedure.org_id == e.org_id, AuditProcedure.engagement_id == e.id)
            .order_by(AuditProcedure.created_at, AuditProcedure.title)
        ).unique()
    )


def links(db: Session, e: AuditEngagement) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """(risk_id, procedure_id) pairs of this engagement."""
    rows = db.execute(
        select(RiskProcedure.risk_id, RiskProcedure.procedure_id)
        .join(AuditRisk, AuditRisk.id == RiskProcedure.risk_id)
        .where(RiskProcedure.org_id == e.org_id, AuditRisk.engagement_id == e.id)
    )
    return [(r, p) for r, p in rows]


def _check_lead(db: Session, e: AuditEngagement, code: str | None) -> str | None:
    if code is None:
        return None
    if code.upper() not in {s.code for s in schedules(db, e)}:
        raise EngagementError(f"There is no lead schedule {code.upper()}.")
    return code.upper()


def save_risk(
    db: Session, e: AuditEngagement, body: RiskIn, actor: User, risk: AuditRisk | None = None
) -> AuditRisk:
    require_open(e)
    lead = _check_lead(db, e, body.lead_code)
    clash = db.scalar(
        select(AuditRisk.id).where(
            AuditRisk.engagement_id == e.id,
            AuditRisk.ref == body.ref,
            AuditRisk.id != (risk.id if risk else uuid.uuid4()),
        )
    )
    if clash:
        raise EngagementError(f"Risk {body.ref} already exists on this engagement.")
    created = risk is None
    r = risk or AuditRisk(org_id=e.org_id, engagement_id=e.id, created_by_id=actor.id)
    r.ref, r.title, r.description = body.ref, body.title.strip(), body.description
    r.lead_code, r.assertions = lead, [a.value for a in body.assertions]
    r.inherent_risk, r.significant, r.fraud = body.inherent_risk, body.significant, body.fraud
    r.response = body.response
    db.add(r)
    db.flush()
    _record(
        db,
        e,
        actor,
        "risk.created" if created else "risk.updated",
        "audit_risk",
        r.id,
        significant=r.significant,
        fraud=r.fraud,
        inherent_risk=r.inherent_risk.value,
    )
    return r


def delete_risk(db: Session, e: AuditEngagement, r: AuditRisk, actor: User) -> None:
    require_open(e)
    _record(db, e, actor, "risk.deleted", "audit_risk", r.id, ref=r.ref)
    db.delete(r)
    db.flush()


def _owned(db: Session, model: type[Any], oid: uuid.UUID | None, org_id: uuid.UUID) -> Any:
    if oid is None:
        return None
    obj = db.scalar(select(model).where(model.id == oid, model.org_id == org_id))
    if obj is None:
        raise LookupError(model.__tablename__)
    return obj


def _set_links(
    db: Session, e: AuditEngagement, p: AuditProcedure, risk_ids: list[uuid.UUID]
) -> None:
    mine = {r.id for r in risks(db, e)}
    unknown = set(risk_ids) - mine
    if unknown:
        raise LookupError("risk")
    for link in db.scalars(select(RiskProcedure).where(RiskProcedure.procedure_id == p.id)):
        db.delete(link)
    db.flush()
    for rid in dict.fromkeys(risk_ids):
        db.add(RiskProcedure(org_id=e.org_id, risk_id=rid, procedure_id=p.id))


def save_procedure(
    db: Session,
    e: AuditEngagement,
    body: ProcedureIn,
    actor: User,
    proc: AuditProcedure | None = None,
) -> AuditProcedure:
    require_open(e)
    if body.requirement_id is not None:
        req: Requirement = _owned(db, Requirement, body.requirement_id, e.org_id)
        if req.checklist_version.state is not ChecklistState.PUBLISHED:
            raise EngagementError("Use a requirement of a published checklist version.")
    if body.assignee_id is not None:
        m = db.scalar(
            select(Membership).where(
                Membership.org_id == e.org_id, Membership.user_id == body.assignee_id
            )
        )
        if m is None:
            raise LookupError("user")
    if body.review_id is not None:
        rv: Review = _owned(db, Review, body.review_id, e.org_id)
        if rv.engagement_id != e.id:
            raise EngagementError("Link the review to this engagement first.")
    created = proc is None
    p = proc or AuditProcedure(org_id=e.org_id, engagement_id=e.id)
    p.title, p.description = body.title.strip(), body.description
    p.requirement_id, p.assignee_id, p.review_id = (
        body.requirement_id,
        body.assignee_id,
        body.review_id,
    )
    db.add(p)
    db.flush()
    _set_links(db, e, p, body.risk_ids)
    db.flush()
    db.refresh(p)
    _record(
        db,
        e,
        actor,
        "procedure.created" if created else "procedure.updated",
        "audit_procedure",
        p.id,
        risks=len(body.risk_ids),
    )
    return p


def set_procedure_status(
    db: Session, e: AuditEngagement, p: AuditProcedure, body: ProcedureStatusIn, actor: User
) -> None:
    require_open(e)
    conclusion = body.conclusion.strip()
    if body.status is ProcedureStatus.DONE and not conclusion:
        raise EngagementError("Record the conclusion before marking the procedure done.")
    previous = p.status
    p.status = body.status
    if conclusion:
        p.conclusion = conclusion
    if body.status is ProcedureStatus.DONE:
        p.completed_by_id, p.completed_at = actor.id, now()
    else:
        p.completed_by_id, p.completed_at = None, None
    db.flush()
    _record(
        db,
        e,
        actor,
        "procedure.status_changed",
        "audit_procedure",
        p.id,
        **{"from": previous.value, "to": body.status.value},
    )


def apply_programme(
    db: Session, e: AuditEngagement, version_id: uuid.UUID, actor: User
) -> list[AuditProcedure]:
    """One procedure per requirement of a published audit programme version."""
    require_open(e)
    v: ChecklistVersion = _owned(db, ChecklistVersion, version_id, e.org_id)
    if v.checklist.kind is not ChecklistKind.AUDIT_PROGRAMME:
        raise EngagementError("Choose a checklist of kind audit programme.")
    if v.state is not ChecklistState.PUBLISHED:
        raise EngagementError("Use a published audit programme version.")
    have = {p.requirement_id for p in procedures(db, e)}
    made = []
    for req in v.requirements:
        if req.id in have:
            continue
        p = AuditProcedure(
            org_id=e.org_id,
            engagement_id=e.id,
            title=f"{req.code} {req.title}"[:300],
            description=req.human_instructions or req.description,
            requirement_id=req.id,
        )
        db.add(p)
        made.append(p)
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="engagement.programme_applied",
        object_type="audit_engagement",
        object_id=e.id,
        meta={"checklist_version_id": str(v.id), "procedures": len(made)},
    )
    return made


def link_review(db: Session, e: AuditEngagement, review: Review, actor: User) -> None:
    require_open(e)
    if review.engagement_id not in (None, e.id):
        raise EngagementError("The review is linked to another engagement.")
    if review.entity_id not in (None, e.entity_id):
        raise EngagementError("The review is for another entity.")
    review.engagement_id = e.id
    db.flush()
    audit.record(
        db,
        org_id=e.org_id,
        actor_id=actor.id,
        action="engagement.review_linked",
        object_type="audit_engagement",
        object_id=e.id,
        meta={"review_id": str(review.id)},
    )


def coverage(db: Session, e: AuditEngagement) -> dict[str, Any]:
    procs = {p.id: p for p in procedures(db, e)}
    pairs = links(db, e)
    rows, uncovered, open_sig = [], [], []
    for r in risks(db, e):
        mine = [procs[p] for rid, p in pairs if rid == r.id and p in procs]
        done = sum(1 for p in mine if p.status is ProcedureStatus.DONE)
        rows.append(
            {
                "risk_id": r.id,
                "ref": r.ref,
                "title": r.title,
                "significant": r.significant,
                "fraud": r.fraud,
                "procedures": len(mine),
                "done": done,
            }
        )
        if not mine:
            uncovered.append(r.ref)
        if (r.significant or r.fraud) and done == 0:
            open_sig.append(r.ref)
    linked = {p for _, p in pairs}
    return {
        "risks": rows,
        "uncovered": uncovered,
        "significant_open": open_sig,
        "unlinked_procedures": [pid for pid in procs if pid not in linked],
    }
