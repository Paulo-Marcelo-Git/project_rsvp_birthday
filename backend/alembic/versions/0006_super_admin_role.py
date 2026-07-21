"""add super_admin role and reserved system tenant

Adiciona 'super_admin' ao ENUM users.role e cria o tenant reservado
"Comemore+ System" onde a conta do super-admin mora, sem misturar com
tenants de clientes reais. A conta em si (com senha) é criada pelo
comando `flask create-superadmin` — não por esta migration, que deve
ser determinística e não manusear segredo.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-21
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYSTEM_TENANT_NAME = "Comemore+ System"


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(text(
        "ALTER TABLE users MODIFY COLUMN role "
        "ENUM('tenant_admin','member','super_admin') NOT NULL DEFAULT 'member'"
    ))

    conn.execute(
        text("""
            INSERT INTO tenants (name, plan, status)
            SELECT :name, 'business', 'active'
            WHERE NOT EXISTS (SELECT 1 FROM tenants WHERE name = :name)
        """),
        {"name": SYSTEM_TENANT_NAME},
    )


def downgrade() -> None:
    conn = op.get_bind()

    row = conn.execute(
        text("SELECT COUNT(*) AS c FROM users WHERE role = 'super_admin'")
    ).mappings().fetchone()
    if row["c"] > 0:
        raise RuntimeError(
            "Não é possível reverter a migration 0006: existem usuários com "
            "role='super_admin'. Remova-os antes de rodar o downgrade."
        )

    conn.execute(
        text("DELETE FROM tenants WHERE name = :name"),
        {"name": SYSTEM_TENANT_NAME},
    )
    conn.execute(text(
        "ALTER TABLE users MODIFY COLUMN role "
        "ENUM('tenant_admin','member') NOT NULL DEFAULT 'member'"
    ))
