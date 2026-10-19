"""fs draft and lease workpaper kinds, fixed assets dataset kind

Revision ID: 0033
Revises: 0032
Create Date: 2026-10-19 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0033'
down_revision: Union[str, Sequence[str], None] = '0032'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD_WP = (
    "corporate_tax",
    "sbr_test",
    "qfzp_test",
    "pillar_two",
    "zakat",
    "lead_schedule",
    "materiality",
)
_NEW_WP = (*_OLD_WP, "fs_draft", "lease_ifrs16")
_OLD_DS = (
    "trial_balance",
    "general_ledger",
    "sales_register",
    "purchase_register",
    "bank_statement",
    "customer_master",
    "supplier_master",
    "vat_return",
    "einvoice_rejections",
    "wht_payments",
    "user_roles",
    "ap_payments",
    "employee_master",
    "three_way_match",
    "expense_claims",
)
_NEW_DS = (*_OLD_DS, "fixed_assets")
_KIND_CHECKS = (
    ("datasets", "ck_datasets_dataset_kind", "kind"),
    ("review_datasets", "ck_review_datasets_review_dataset_kind", "kind"),
    ("entity_tax_codes", "ck_entity_tax_codes_tax_code_register", "register"),
    ("tax_workpapers", "ck_tax_workpapers_workpaper_kind", "kind"),
)


def _apply(ds: Sequence[str], wp: Sequence[str]) -> None:
    for table, name, column in _KIND_CHECKS:
        values = wp if table == "tax_workpapers" else ds
        listed = ", ".join(f"'{v}'" for v in values)
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    _apply(_NEW_DS, _NEW_WP)


def downgrade() -> None:
    _apply(_OLD_DS, _OLD_WP)
