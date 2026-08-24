"""tenant suspended_reason — distingue suspensão por trial expirado de manual

Sem essa coluna, promover um tenant suspenso pra Pro/Business reativava ele
automaticamente mesmo quando a suspensão foi manual (abuso/fraude/não
pagamento) — o código não tinha como diferenciar os dois casos. Achado no
code review de 2026-08-22 (docs/superpowers/specs/2026-08-22-code-review-fixes-design.md).

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column(
            "suspended_reason",
            sa.Enum("trial_expired", "manual", name="tenant_suspended_reason"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "suspended_reason")
