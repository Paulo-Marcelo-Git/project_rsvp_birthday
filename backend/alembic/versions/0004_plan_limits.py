"""plan_limits — limites por plano (free/pro/business)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE plan_limits (
            plan         ENUM('free','pro','business') NOT NULL,
            max_events   INT UNSIGNED NULL,
            max_invitees INT UNSIGNED NULL,
            max_members  INT UNSIGNED NULL,
            PRIMARY KEY (plan)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    op.execute(text("""
        INSERT INTO plan_limits (plan, max_events, max_invitees, max_members) VALUES
            ('free',     2,    50,   1),
            ('pro',      10,   500,  5),
            ('business', NULL, NULL, NULL)
    """))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS plan_limits"))
