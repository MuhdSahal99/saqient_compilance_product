"""Synthetic Phase C demo: direct-tax workpapers, a loss register, a tax group, a
transfer pricing register, a Pillar Two paper and a zakat paper.

Every value is invented. The rule pack uses the SYNTHETIC jurisdiction, so its rules
stay unverified; workpapers and exports flag them.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app import demo_tax
from app.demo_einvoice import SYNTHETIC_NOTE
from app.models import (
    LegalEntity,
    Organization,
    RelatedPartyRelation,
    RPTransactionType,
    RulePackVersion,
    TaxWorkpaper,
    TPMethod,
    User,
    WorkpaperKind,
)
from app.schemas import (
    LegalEntityIn,
    LossEntryIn,
    MembershipIn,
    RelatedPartyIn,
    RPTransactionIn,
    RuleIn,
    TaxGroupIn,
    WorkpaperIn,
    WorkpaperInputIn,
)
from app.services import entities, rule_packs, tax_losses, transfer_pricing, workpapers

PACK_NAME = "Synthetic direct-tax pack (demo)"
HOLDING = "Synthetic Holding LLC"
TRADING = "Synthetic Trading LLC"
KSA = "Synthetic KSA Trading Co"


def _pack(db: Session, org: Organization, reviewer: User) -> RulePackVersion:
    pack = rule_packs.create_pack(
        db,
        org.id,
        PACK_NAME,
        "SYNTHETIC",
        "Invented rates and thresholds for the direct-tax demo. Not legal or tax guidance.",
        reviewer,
    )
    db.flush()
    v: RulePackVersion = pack.versions[0]
    rule_packs.replace_rules(db, v, [RuleIn.model_validate(r) for r in demo_tax.rules()], reviewer)
    db.flush()
    db.refresh(v)
    rule_packs.publish(db, v, reviewer)
    return v


def _entity(db: Session, org: Organization, admin: User, name: str, country: str) -> LegalEntity:
    return entities.create_entity(
        db,
        org.id,
        LegalEntityIn(
            name=name,
            country=country,
            fiscal_year_end_month=12,
            fiscal_year_end_day=31,
            functional_currency="SAR" if country == "SA" else "AED",
            timezone="Asia/Riyadh" if country == "SA" else "Asia/Dubai",
        ),
        admin,
    )


def _paper(
    db: Session,
    entity: LegalEntity,
    rpv: RulePackVersion,
    kind: WorkpaperKind,
    title: str,
    prefix: str,
    inputs: list[tuple[str, str, str]],
    actor: User,
) -> TaxWorkpaper:
    wp = workpapers.create(
        db,
        entity,
        WorkpaperIn(
            entity_id=entity.id,
            kind=kind,
            title=title,
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            rule_pack_version_id=rpv.id,
            rules_prefix=prefix,
        ),
        actor,
    )
    wp.is_demo = True
    for key, category, raw in inputs:
        is_flag = raw in ("true", "false")
        workpapers.put_input(
            db,
            wp,
            key,
            WorkpaperInputIn(
                category=category,
                label=key.replace("_", " ").capitalize(),
                amount=None if is_flag else Decimal(raw),
                value=raw if is_flag else None,
                note=SYNTHETIC_NOTE,
            ),
            actor,
        )
    workpapers.compute(db, wp, actor)
    return wp


def seed_direct_tax(
    db: Session, org: Organization, admin: User, reviewer: User, analyst: User
) -> list[TaxWorkpaper]:
    rpv = _pack(db, org, reviewer)
    holding = _entity(db, org, admin, HOLDING, "AE")
    trading = _entity(db, org, admin, TRADING, "AE")
    ksa = _entity(db, org, admin, KSA, "SA")
    db.commit()

    tax_losses.add_entry(
        db,
        holding,
        LossEntryIn(
            kind="incurred",
            period_start=date(2024, 1, 1),
            period_end=date(2024, 12, 31),
            amount=Decimal(300000),
            note="Synthetic loss carried into the demo.",
        ),
        analyst,
    )
    ct = workpapers.create(
        db,
        holding,
        WorkpaperIn(
            entity_id=holding.id,
            kind=WorkpaperKind.CORPORATE_TAX,
            title="FY2025 corporate tax (synthetic)",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            rule_pack_version_id=rpv.id,
            rules_prefix="syn.ct",
        ),
        analyst,
    )
    ct.is_demo = True
    tax_losses.prefill_workpaper(db, ct, analyst)
    for key, cat, amt in [
        ("accounting_profit", "input", "1000000"),
        ("fines", "non_deductible", "20000"),
        ("client_entertainment", "entertainment", "30000"),
        ("dividends", "exempt_income", "50000"),
        ("tp_adjustment", "related_party", "12000"),
        ("net_interest_expense", "input", "400000"),
        ("depreciation_amortisation", "input", "100000"),
    ]:
        workpapers.put_input(
            db,
            ct,
            key,
            WorkpaperInputIn(
                category=cat,
                label=key.replace("_", " ").capitalize(),
                amount=Decimal(amt),
                note=SYNTHETIC_NOTE,
            ),
            analyst,
        )
    workpapers.compute(db, ct, analyst)
    workpapers.sign_off(db, ct, reviewer)
    tax_losses.post_workpaper(db, ct, reviewer)

    sbr = _paper(
        db,
        trading,
        rpv,
        WorkpaperKind.SBR_TEST,
        "FY2025 Small Business Relief test (synthetic)",
        "syn.ct",
        [
            ("revenue", "input", "1800000"),
            ("revenue_prior_1", "input", "1700000"),
            ("is_qfzp", "input", "false"),
            ("is_mne_group_member", "input", "false"),
        ],
        analyst,
    )
    p2 = _paper(
        db,
        holding,
        rpv,
        WorkpaperKind.PILLAR_TWO,
        "FY2025 Pillar Two readiness (synthetic)",
        "syn.p2",
        [
            ("revenue_year_1", "input", "700000000"),
            ("revenue_year_2", "input", "650000000"),
            ("income_ae", "globe_income", "10000000"),
            ("taxes_ae", "covered_taxes", "900000"),
            ("payroll_ae", "payroll", "5000000"),
            ("assets_ae", "tangible_assets", "20000000"),
            ("ready_entity_list", "readiness", "true"),
            ("ready_cbcr_data", "readiness", "false"),
        ],
        analyst,
    )
    zakat = _paper(
        db,
        ksa,
        rpv,
        WorkpaperKind.ZAKAT,
        "FY2025 zakat base (synthetic)",
        "syn.zakat",
        [
            ("adjusted_net_profit", "input", "5000000"),
            ("equity", "zakat_addition", "10000000"),
            ("long_term_loans", "zakat_addition", "4000000"),
            ("fixed_assets", "zakat_deduction", "9000000"),
        ],
        analyst,
    )

    group = entities.create_tax_group(
        db, org.id, TaxGroupIn(name="Synthetic tax group", country="AE"), admin
    )
    db.flush()
    for e, share, parent in ((holding, "1", True), (trading, "0.95", False)):
        tax_losses.add_membership(
            db,
            group,
            e,
            MembershipIn(
                entity_id=e.id,
                is_parent=parent,
                ownership_share=Decimal(share),
                joined_on=date(2025, 1, 1),
                note=SYNTHETIC_NOTE,
            ),
            admin,
        )

    party = transfer_pricing.add_party(
        db,
        holding,
        RelatedPartyIn(
            name="Synthetic Parent Holdings Ltd",
            relation=RelatedPartyRelation.PARENT,
            jurisdiction="GB",
            note=SYNTHETIC_NOTE,
        ),
        analyst,
    )
    party.is_demo = True
    for ttype, amount, method, rng in (
        (RPTransactionType.SERVICES, "12000000", TPMethod.TNMM, ("0.05", "0.08", "0.065")),
        (RPTransactionType.FINANCING, "4000000", TPMethod.CUP, None),
    ):
        t = transfer_pricing.add_transaction(
            db,
            holding,
            party,
            RPTransactionIn(
                related_party_id=party.id,
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                transaction_type=ttype,
                direction="payment",
                description="Synthetic intra-group transaction",
                amount=Decimal(amount),
                method=method,
                range_low=Decimal(rng[0]) if rng else None,
                range_high=Decimal(rng[1]) if rng else None,
                tested_value=Decimal(rng[2]) if rng else None,
                range_metric="Net cost plus mark-up" if rng else "",
            ),
            analyst,
        )
        t.is_demo = True
    db.commit()
    return [ct, sbr, p2, zakat]
