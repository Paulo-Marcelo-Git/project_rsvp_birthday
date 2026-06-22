"""initial saas schema

Revision ID: 0001
Revises:
Create Date: 2026-06-22

"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(text("SET NAMES utf8mb4"))
    op.execute(text("SET FOREIGN_KEY_CHECKS = 0"))

    op.execute(text("""
        CREATE TABLE tenants (
            id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            name          VARCHAR(120)    NOT NULL,
            plan          ENUM('free','pro','business') NOT NULL DEFAULT 'free',
            status        ENUM('trial','active','suspended','canceled') NOT NULL DEFAULT 'trial',
            trial_ends_at DATETIME        NULL,
            created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    op.execute(text("""
        CREATE TABLE users (
            id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            tenant_id            BIGINT UNSIGNED NOT NULL,
            username             VARCHAR(60)     NOT NULL,
            email                VARCHAR(180)    NOT NULL,
            password_hash        VARCHAR(255)    NOT NULL,
            role                 ENUM('tenant_admin','member') NOT NULL DEFAULT 'member',
            must_change_password TINYINT(1)      NOT NULL DEFAULT 0,
            whatsapp             VARCHAR(20)     NULL,
            is_active            TINYINT(1)      NOT NULL DEFAULT 1,
            created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_users_email (email),
            UNIQUE KEY uq_users_tenant_username (tenant_id, username),
            KEY idx_users_tenant (tenant_id),
            CONSTRAINT fk_users_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    op.execute(text("""
        CREATE TABLE events (
            id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            tenant_id      BIGINT UNSIGNED NOT NULL,
            owner_user_id  BIGINT UNSIGNED NULL,
            title          VARCHAR(150)    NOT NULL,
            event_type     VARCHAR(40)     NOT NULL DEFAULT 'aniversario',
            event_date     DATE            NULL,
            slug           CHAR(22)        NOT NULL,
            theme          VARCHAR(40)     NOT NULL DEFAULT 'default',
            media_url      VARCHAR(500)    NULL,
            question_text  VARCHAR(255)    NULL,
            yes_text       VARCHAR(80)     NULL,
            no_text        VARCHAR(80)     NULL,
            extra_texts    JSON            NULL,
            status         ENUM('draft','published','archived') NOT NULL DEFAULT 'draft',
            created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                           ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_events_slug (slug),
            KEY idx_events_tenant (tenant_id),
            KEY idx_events_tenant_owner (tenant_id, owner_user_id),
            KEY idx_events_tenant_status (tenant_id, status),
            CONSTRAINT fk_events_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE CASCADE,
            CONSTRAINT fk_events_owner
                FOREIGN KEY (owner_user_id) REFERENCES users (id)
                ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    # invitees tem DOIS caminhos de cascade até tenants:
    #   1. invitees.tenant_id  → tenants.id  (direto)
    #   2. invitees.event_id   → events.id   → tenants.id  (via events)
    # No MySQL/InnoDB isso é permitido e correto.
    # No SQL Server geraria "multiple cascade paths" — não "corrija" aqui.
    op.execute(text("""
        CREATE TABLE invitees (
            id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            event_id     BIGINT UNSIGNED NOT NULL,
            tenant_id    BIGINT UNSIGNED NOT NULL,
            name         VARCHAR(120)    NOT NULL,
            token        CHAR(22)        NOT NULL,
            response     ENUM('pending','yes','no') NOT NULL DEFAULT 'pending',
            observation  VARCHAR(500)    NULL,
            media_url    VARCHAR(500)    NULL,
            responded_at DATETIME        NULL,
            created_at   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_invitees_token (token),
            KEY idx_invitees_event (event_id),
            KEY idx_invitees_tenant (tenant_id),
            KEY idx_invitees_event_response (event_id, response),
            CONSTRAINT fk_invitees_event
                FOREIGN KEY (event_id) REFERENCES events (id)
                ON DELETE CASCADE,
            CONSTRAINT fk_invitees_tenant
                FOREIGN KEY (tenant_id) REFERENCES tenants (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    op.execute(text("""
        CREATE TABLE password_reset_tokens (
            id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
            user_id    BIGINT UNSIGNED NOT NULL,
            token      CHAR(43)        NOT NULL,
            expires_at DATETIME        NOT NULL,
            used       TINYINT(1)      NOT NULL DEFAULT 0,
            created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (id),
            UNIQUE KEY uq_prt_token (token),
            KEY idx_prt_user (user_id),
            CONSTRAINT fk_prt_user
                FOREIGN KEY (user_id) REFERENCES users (id)
                ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    """))

    op.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


def downgrade() -> None:
    # Ordem inversa da criação para respeitar FKs.
    # FOREIGN_KEY_CHECKS = 0 garante que o DROP não trave mesmo se houver
    # dados ou se a ordem de CASCADE não for reconhecida pelo parser.
    op.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    op.execute(text("DROP TABLE IF EXISTS password_reset_tokens"))
    op.execute(text("DROP TABLE IF EXISTS invitees"))
    op.execute(text("DROP TABLE IF EXISTS events"))
    op.execute(text("DROP TABLE IF EXISTS users"))
    op.execute(text("DROP TABLE IF EXISTS tenants"))
    op.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
