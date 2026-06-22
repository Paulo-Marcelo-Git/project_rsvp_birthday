"""seed default tenant, event and invitees compat columns

Adiciona colunas de compatibilidade (phone, email) em invitees e
insere o tenant/evento padrão necessário para o app single-tenant
funcionar no schema multi-tenant antes do signup self-service (2C).

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Slug fixo (22 chars, URL-safe base64) — reprodutível em dev/test
_DEFAULT_SLUG = "default000000000000000"

# Extra texts JSON com textos pós-resposta
_EXTRA_TEXTS = (
    '{"post_yes_text": "Que bom! Te esperamos!", '
    '"post_no_text": "Sentiremos sua falta."}'
)


def upgrade() -> None:
    conn = op.get_bind()

    # Adiciona phone e email em invitees (ausentes no schema canônico mas
    # necessários durante a transição para manter o WhatsApp URL e a UI).
    # Removidos na Fase 3 quando gestão de contatos for própria.
    # Alembic garante que esta migration só roda uma vez (rastreia em
    # alembic_version), então ADD COLUMN nunca é executado duas vezes.
    conn.execute(text(
        "ALTER TABLE invitees "
        "ADD COLUMN phone  VARCHAR(20)  NULL, "
        "ADD COLUMN email  VARCHAR(120) NULL"
    ))

    # Seed: tenant padrão
    conn.execute(text("""
        INSERT INTO tenants (id, name, plan, status)
        VALUES (1, 'Comemore+ Default', 'free', 'active')
        ON DUPLICATE KEY UPDATE name = name
    """))

    # Seed: evento padrão (textos do convite migrados de settings)
    conn.execute(text(f"""
        INSERT INTO events (
            id, tenant_id, owner_user_id,
            title, event_type, slug, status,
            question_text, yes_text, no_text, extra_texts
        ) VALUES (
            1, 1, NULL,
            'Evento Padrão', 'aniversario', '{_DEFAULT_SLUG}', 'published',
            'Você vai comparecer?', 'Sim ✅', 'Não ❌', '{_EXTRA_TEXTS}'
        )
        ON DUPLICATE KEY UPDATE title = title
    """))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    conn.execute(text("DELETE FROM events  WHERE id = 1"))
    conn.execute(text("DELETE FROM tenants WHERE id = 1"))
    conn.execute(text("SET FOREIGN_KEY_CHECKS = 1"))

    conn.execute(text(
        "ALTER TABLE invitees "
        "DROP COLUMN phone, "
        "DROP COLUMN email"
    ))
