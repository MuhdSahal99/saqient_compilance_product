"""The synthetic finance demo seed builds, runs and produces the planted exceptions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.demo_finance import seed_finance
from app.models import CheckOutcome, CheckResult, Finding, Role, RulePack, RuleVerification
from tests.conftest import Tenant


def test_finance_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    review = seed_finance(
        db, get_sessionmaker(), tenant_a.org, u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    )
    assert review.is_demo and review.as_of_date is not None
    results = {
        r.requirement.code: r
        for r in db.scalars(select(CheckResult).where(CheckResult.run_id == review.runs[-1].id))
    }
    assert {k: v.outcome for k, v in results.items()} == {
        "GL-01": CheckOutcome.EXCEPTIONS_FOUND,
        "GL-02": CheckOutcome.EXCEPTIONS_FOUND,
        "GL-03": CheckOutcome.EXCEPTIONS_FOUND,
        "GL-04": CheckOutcome.EXCEPTIONS_FOUND,
    }
    # JE-1003 (rows 5, 6) is large; JE-1004 (rows 7, 8) is on a Saturday; rows 9 and 11 repeat.
    assert results["GL-01"].evidence[0]["row_ids"] == [5, 6]
    assert results["GL-02"].evidence[0]["row_ids"] == [7, 8]
    assert results["GL-03"].evidence[0]["row_ids"] == [9, 11]
    # The rule used is synthetic and stays unverified.
    pack = db.scalar(select(RulePack).where(RulePack.org_id == tenant_a.org.id))
    assert pack is not None and pack.is_synthetic
    assert all(
        r.verification_status is RuleVerification.DRAFT for v in pack.versions for r in v.rules
    )
    assert db.scalars(select(Finding).where(Finding.review_id == review.id)).all()
