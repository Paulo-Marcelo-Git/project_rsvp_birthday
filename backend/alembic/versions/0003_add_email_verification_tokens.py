"""add email_verification_tokens

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-23
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("""
        CREATE TABLE email_verification_tokens (
            id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id    BIGINT UNSIGNED NOT NULL,
            token      CHAR(43)        NOT NULL,
            expires_at DATETIME        NOT NULL,
            used       TINYINT(1)      NOT NULL DEFAULT 0,
            created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_evt_token (token),
            KEY idx_evt_user (user_id),
            CONSTRAINT fk_evt_user
                FOREIGN KEY (user_id) REFERENCES users (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))


def downgrade() -> None:
    op.execute(text("DROP TABLE IF EXISTS email_verification_tokens"))
