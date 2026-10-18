"""Rule packs: versioned, data-driven tax and regulatory parameters."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import DB, Admin, Ctx, Decider, get_owned_or_404
from app.models import Rule, RulePack, RulePackVersion, RuleVerification
from app.schemas import (
    RuleOut,
    RulePackCreateIn,
    RulePackOut,
    RulePackVersionDetailOut,
    RulePackVersionOut,
    RulesReplaceIn,
)
from app.services import rule_packs as svc

router = APIRouter(tags=["rule packs"])


def _rule_out(r: Rule) -> RuleOut:
    out = RuleOut.model_validate(r)
    out.verified_by_name = r.verified_by.full_name if r.verified_by else None
    return out


def _version_out(v: RulePackVersion) -> RulePackVersionOut:
    out = RulePackVersionOut.model_validate(v)
    out.rule_count = len(v.rules)
    out.unverified_count = sum(
        1 for r in v.rules if r.verification_status is not RuleVerification.VERIFIED
    )
    return out


def _detail(db: Session, v: RulePackVersion) -> RulePackVersionDetailOut:
    db.refresh(v)
    base = _version_out(v)
    return RulePackVersionDetailOut(
        **base.model_dump(),
        pack_name=v.rule_pack.name,
        jurisdiction=v.rule_pack.jurisdiction,
        is_synthetic=v.rule_pack.is_synthetic,
        rules=[_rule_out(r) for r in v.rules],
    )


def _pack_out(p: RulePack) -> RulePackOut:
    return RulePackOut(
        id=p.id,
        name=p.name,
        jurisdiction=p.jurisdiction,
        description=p.description,
        is_synthetic=p.is_synthetic,
        created_at=p.created_at,
        versions=[_version_out(v) for v in p.versions],
    )


@router.get("/rule-packs", response_model=list[RulePackOut], summary="List rule packs")
def list_packs(ctx: Ctx, db: DB) -> list[RulePackOut]:
    rows = db.scalars(
        select(RulePack).where(RulePack.org_id == ctx.org_id).order_by(RulePack.name)
    ).all()
    return [_pack_out(p) for p in rows]


@router.post(
    "/rule-packs",
    response_model=RulePackOut,
    status_code=201,
    summary="Create a rule pack",
    description="Creates the pack with an empty draft version 1. Admins and reviewers.",
)
def create_pack(body: RulePackCreateIn, ctx: Decider, db: DB) -> RulePackOut:
    try:
        pack = svc.create_pack(
            db, ctx.org_id, body.name, body.jurisdiction, body.description, ctx.user
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "That name is already in use.") from exc
    db.refresh(pack)
    return _pack_out(pack)


@router.get("/rule-packs/{pack_id}", response_model=RulePackOut, summary="Get a rule pack")
def get_pack(pack_id: uuid.UUID, ctx: Ctx, db: DB) -> RulePackOut:
    return _pack_out(get_owned_or_404(db, RulePack, pack_id, ctx.org_id))


@router.post(
    "/rule-packs/{pack_id}/drafts",
    response_model=RulePackVersionDetailOut,
    status_code=201,
    summary="Start a new draft version",
    description="Copies the latest version's rules. Admins and reviewers.",
)
def new_draft(pack_id: uuid.UUID, ctx: Decider, db: DB) -> RulePackVersionDetailOut:
    pack = get_owned_or_404(db, RulePack, pack_id, ctx.org_id)
    v = svc.new_draft(db, pack, ctx.user)
    db.commit()
    return _detail(db, v)


@router.get(
    "/rule-pack-versions/{version_id}",
    response_model=RulePackVersionDetailOut,
    summary="Get a rule pack version with its rules",
)
def get_version(version_id: uuid.UUID, ctx: Ctx, db: DB) -> RulePackVersionDetailOut:
    return _detail(db, get_owned_or_404(db, RulePackVersion, version_id, ctx.org_id))


@router.put(
    "/rule-pack-versions/{version_id}/rules",
    response_model=RulePackVersionDetailOut,
    summary="Replace the rules of a draft version",
    description="Drafts only. An unchanged verified rule stays verified; a changed one "
    "returns to draft. Admins and reviewers.",
)
def replace_rules(
    version_id: uuid.UUID, body: RulesReplaceIn, ctx: Decider, db: DB
) -> RulePackVersionDetailOut:
    v = get_owned_or_404(db, RulePackVersion, version_id, ctx.org_id)
    svc.replace_rules(db, v, body.rules, ctx.user)
    db.commit()
    return _detail(db, v)


@router.post(
    "/rule-pack-versions/{version_id}/publish",
    response_model=RulePackVersionDetailOut,
    summary="Publish a draft version",
    description="Published versions are immutable; the previous published version is archived.",
)
def publish(version_id: uuid.UUID, ctx: Decider, db: DB) -> RulePackVersionDetailOut:
    v = get_owned_or_404(db, RulePackVersion, version_id, ctx.org_id)
    svc.publish(db, v, ctx.user)
    db.commit()
    return _detail(db, v)


@router.post(
    "/rules/{rule_id}/verify",
    response_model=RuleOut,
    summary="Mark a rule verified",
    description="Organisation admins only. Requires an official source URL and no open TODO. "
    "Synthetic rules cannot be verified.",
)
def verify_rule(rule_id: uuid.UUID, ctx: Admin, db: DB) -> RuleOut:
    rule = get_owned_or_404(db, Rule, rule_id, ctx.org_id)
    svc.set_verification(db, rule, True, ctx.user)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)


@router.post(
    "/rules/{rule_id}/unverify",
    response_model=RuleOut,
    summary="Return a rule to draft",
    description="Organisation admins only.",
)
def unverify_rule(rule_id: uuid.UUID, ctx: Admin, db: DB) -> RuleOut:
    rule = get_owned_or_404(db, Rule, rule_id, ctx.org_id)
    svc.set_verification(db, rule, False, ctx.user)
    db.commit()
    db.refresh(rule)
    return _rule_out(rule)
