"""accepted_terms_at — timestamp de aceite dos termos de uso (LGPD)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("accepted_terms_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "accepted_terms_at")
