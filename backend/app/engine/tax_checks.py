"""Engine 1.2.0 checks: e-invoicing, master data, readiness and VAT return review.

Same contract as the 1.1.0 data checks (engine/data_checks.py): declarative,
validated configurations; no user code or regex; Decimal arithmetic; inputs,
rule pack values and formula ids recorded in ``meta``; evidence points to
dataset rows or XML paths. Regulatory values (formats, boxes, deadlines,
blocked categories, rounding) always come from the rule pack.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.engine.data_checks import DataContext, DataEvaluation
from app.models import DatasetKind


@dataclass(frozen=True)
class EntityInfo:
    id: str
    name: str
    country: str
    size_basis_amount: Decimal | None = None
    size_basis_currency: str | None = None
    size_basis_year: int | None = None
    go_live_override: date | None = None
    go_live_note: str = ""
    # (register, ERP tax code) -> (treatment, recoverable)
    tax_codes: dict[tuple[str, str], tuple[str, bool]] = field(default_factory=dict)
    # role -> account codes
    tax_accounts: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "entity_id": self.id,
            "country": self.country,
            "size_basis_amount": str(self.size_basis_amount)
            if self.size_basis_amount is not None
            else None,
            "size_basis_currency": self.size_basis_currency,
            "size_basis_year": self.size_basis_year,
            "go_live_override": self.go_live_override.isoformat()
            if self.go_live_override
            else None,
            "tax_codes": sorted(f"{r}:{c}={t}" for (r, c), (t, _) in self.tax_codes.items()),
            "tax_accounts": {k: list(v) for k, v in sorted(self.tax_accounts.items())},
        }


def datasets_used(config: Any) -> set[DatasetKind]:
    return set(getattr(config, "datasets_needed", lambda: set())())


def evaluate(config: Any, ctx: DataContext, meta: dict[str, Any]) -> DataEvaluation:
    result: DataEvaluation = config.run(ctx, meta)
    return result


# Imported last: the check modules import EntityInfo from here.
from app.engine.einvoice_checks import EINVOICE_CHECK_TYPES  # noqa: E402
from app.engine.je_checks import JE_CHECK_TYPES  # noqa: E402
from app.engine.master_data_checks import MASTER_CHECK_TYPES  # noqa: E402
from app.engine.sod_checks import SOD_CHECK_TYPES  # noqa: E402
from app.engine.vat_checks import VAT_CHECK_TYPES  # noqa: E402
from app.engine.wht_checks import WHT_CHECK_TYPES  # noqa: E402

TAX_CHECK_TYPES: tuple[type, ...] = (
    *EINVOICE_CHECK_TYPES,
    *MASTER_CHECK_TYPES,
    *VAT_CHECK_TYPES,
    *WHT_CHECK_TYPES,
    *JE_CHECK_TYPES,
    *SOD_CHECK_TYPES,
)
