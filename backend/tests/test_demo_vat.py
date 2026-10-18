"""The synthetic Phase B demo seed builds and produces the planted exceptions."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.demo_vat import seed_vat
from app.models import (
    CheckOutcome,
    CheckResult,
    EInvoiceMonitor,
    Finding,
    Role,
    RulePackFile,
    RuleVerification,
    TaxObligation,
)
from tests.conftest import Tenant


def test_vat_seed(tenant_a: Tenant, db: Session) -> None:
    u = tenant_a.users
    ev, vat = seed_vat(
        db, get_sessionmaker(), tenant_a.org, u[Role.ORG_ADMIN], u[Role.REVIEWER], u[Role.ANALYST]
    )
    assert ev.is_demo and vat.is_demo

    def outcomes(review):  # type: ignore[no-untyped-def]
        rows = db.scalars(select(CheckResult).where(CheckResult.run_id == review.runs[-1].id))
        return {r.requirement.code: r.outcome for r in rows}

    assert outcomes(ev) == {
        "EINV-01": CheckOutcome.EXCEPTIONS_FOUND,
        "READY-01": CheckOutcome.EXCEPTIONS_FOUND,
    }
    got = outcomes(vat)
    for code in ("MD-01", "MD-02", "VAT-03", "VAT-04", "VAT-05", "VAT-06"):
        assert got[code] is CheckOutcome.EXCEPTIONS_FOUND, (code, got)
    # The demo return agrees with the registers and the GL; only the planted items show.
    assert got["VAT-01"] is CheckOutcome.NO_EXCEPTIONS, got
    assert got["VAT-02"] is CheckOutcome.NO_EXCEPTIONS, got
    keys = {f.finding_key for f in db.scalars(select(Finding).where(Finding.review_id == ev.id))}
    assert {"mandatory:SYN-02", "arithmetic:line_net"} <= keys
    assert any(k.startswith("tax_id:") for k in keys)
    assert db.scalars(select(TaxObligation)).all()
    assert db.scalar(select(EInvoiceMonitor)) is not None
    f = db.scalar(select(RulePackFile))
    assert f is not None and f.verification_status is RuleVerification.DRAFT
