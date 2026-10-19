"""user roles dataset kind

Revision ID: 0029
Revises: 0028
Create Date: 2026-10-19 05:10:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '0029'
down_revision: Union[str, Sequence[str], None] = '0028'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = (
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
)
_NEW = (*_OLD, "user_roles")
_KIND_CHECKS = (
    ("datasets", "ck_datasets_dataset_kind", "kind"),
    ("review_datasets", "ck_review_datasets_review_dataset_kind", "kind"),
    ("entity_tax_codes", "ck_entity_tax_codes_tax_code_register", "register"),
)


def _kinds(values: Sequence[str]) -> None:
    listed = ", ".join(f"'{v}'" for v in values)
    for table, name, column in _KIND_CHECKS:
        op.drop_constraint(op.f(name), table, type_="check")
        op.create_check_constraint(op.f(name), table, f"{column} IN ({listed})")


def upgrade() -> None:
    _kinds(_NEW)


def downgrade() -> None:
    _kinds(_OLD)
