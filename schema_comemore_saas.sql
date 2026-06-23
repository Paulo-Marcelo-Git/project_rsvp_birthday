-- ============================================================
-- Comemore+ — Schema SaaS multi-tenant (MySQL 8)
-- Substitui o init.sql single-tenant e a tabela global `settings`.
-- Charset utf8mb4: acentos PT-BR e emojis.
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ------------------------------------------------------------
-- tenants — a conta do cliente que assina o SaaS.
-- (raiz da árvore: apagar um tenant apaga TUDO dele = LGPD)
-- ------------------------------------------------------------
CREATE TABLE tenants (
    id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,   -- equiv. IDENTITY no SQL Server
    name          VARCHAR(120)    NOT NULL,
    plan          ENUM('free','pro','business') NOT NULL DEFAULT 'free',
    status        ENUM('trial','active','suspended','canceled') NOT NULL DEFAULT 'trial',
    trial_ends_at DATETIME        NULL,
    created_at    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- users — agora pertence a um tenant.
-- email: UNIQUE GLOBAL (login por email já resolve o tenant).
-- username: UNIQUE POR tenant (dois tenants podem ter "admin").
-- role substitui o antigo is_super_admin.
-- ------------------------------------------------------------
CREATE TABLE users (
    id                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id            BIGINT UNSIGNED NOT NULL,
    username             VARCHAR(60)     NOT NULL,
    email                VARCHAR(180)    NOT NULL,
    password_hash        VARCHAR(255)    NOT NULL,           -- bcrypt do Werkzeug
    role                 ENUM('tenant_admin','member') NOT NULL DEFAULT 'member',
    must_change_password TINYINT(1)      NOT NULL DEFAULT 0, -- TINYINT(1) = bool (BIT no SQL Server)
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- events — o NOVO núcleo do produto.
-- Cada cliente cria N eventos (aniversário, casamento...).
-- Os textos configuráveis que estavam na tabela GLOBAL `settings`
-- agora vivem aqui, por evento.
-- slug = id público não-sequencial p/ URL (não vaza contagem).
-- ------------------------------------------------------------
CREATE TABLE events (
    id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    tenant_id      BIGINT UNSIGNED NOT NULL,
    owner_user_id  BIGINT UNSIGNED NULL,               -- quem criou; member vê só os seus
    title          VARCHAR(150)    NOT NULL,
    event_type     VARCHAR(40)     NOT NULL DEFAULT 'aniversario',
    event_date     DATE            NULL,
    slug           CHAR(22)        NOT NULL,            -- secrets.token_urlsafe(16) => 22 chars
    theme          VARCHAR(40)     NOT NULL DEFAULT 'default',
    media_url      VARCHAR(500)    NULL,
    -- textos do convite (migrados de settings):
    question_text  VARCHAR(255)    NULL,
    yes_text       VARCHAR(80)     NULL,
    no_text        VARCHAR(80)     NULL,
    extra_texts    JSON            NULL,                -- textos extras flexíveis (MySQL 8 nativo)
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
        ON DELETE SET NULL                              -- some o membro, evento fica com o tenant
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- invitees — convidados de um evento.
-- tenant_id é DESNORMALIZADO de propósito: permite isolamento
-- barato (WHERE tenant_id = ?) sem JOIN em toda query.
-- token é UNIQUE GLOBAL (vai na URL pública /invite/<token>).
-- ------------------------------------------------------------
CREATE TABLE invitees (
    id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    event_id     BIGINT UNSIGNED NOT NULL,
    tenant_id    BIGINT UNSIGNED NOT NULL,             -- desnormalizado p/ isolamento
    name         VARCHAR(120)    NOT NULL,
    token        CHAR(22)        NOT NULL,             -- secrets.token_urlsafe(16)
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- password_reset_tokens — inalterado no conceito.
-- user_id já carrega o tenant via users.
-- ------------------------------------------------------------
CREATE TABLE password_reset_tokens (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id    BIGINT UNSIGNED NOT NULL,
    token      CHAR(43)        NOT NULL,               -- secrets.token_urlsafe(32) => 43 chars
    expires_at DATETIME        NOT NULL,               -- TTL de 1h
    used       TINYINT(1)      NOT NULL DEFAULT 0,
    created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_prt_token (token),
    KEY idx_prt_user (user_id),
    CONSTRAINT fk_prt_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ------------------------------------------------------------
-- email_verification_tokens — confirma posse do email no signup.
-- Criada pela migration 0003.
-- ------------------------------------------------------------
CREATE TABLE email_verification_tokens (
    id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id    BIGINT UNSIGNED NOT NULL,
    token      CHAR(43)        NOT NULL,               -- secrets.token_urlsafe(32) => 43 chars
    expires_at DATETIME        NOT NULL,               -- TTL de 24h
    used       TINYINT(1)      NOT NULL DEFAULT 0,
    created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_evt_token (token),
    KEY idx_evt_user (user_id),
    CONSTRAINT fk_evt_user
        FOREIGN KEY (user_id) REFERENCES users (id)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SET FOREIGN_KEY_CHECKS = 1;
