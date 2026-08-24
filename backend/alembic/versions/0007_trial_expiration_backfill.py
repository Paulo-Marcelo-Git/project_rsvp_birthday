"""trial expiration — backfill de trial_ends_at pra tenants trial legados

Não adiciona coluna (trial_ends_at já existe desde a migration 0001).
A partir desta versão, tenants novos nascem com trial_ends_at NULL e o
contador de 14 dias só começa no primeiro login (ver app.py:login e
repo.start_tenant_trial). Tenants trial que já existem hoje não têm como
saber quando foi seu "primeiro login" retroativamente, então ganham um
prazo de transição fixo (piso de alguns dias a partir do deploy) em vez
de um cálculo retroativo por created_at, que bloquearia contas reais
sem aviso prévio.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-22
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(text("""
        UPDATE tenants
        SET trial_ends_at = UTC_TIMESTAMP() + INTERVAL 3 DAY
        WHERE status = 'trial' AND trial_ends_at IS NULL
    """))


def downgrade() -> None:
    # Backfill de dados de transição — não há valor original a restaurar
    # (trial_ends_at já era NULL antes desta migration). No-op intencional.
    pass
