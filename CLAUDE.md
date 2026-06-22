# CLAUDE.md — Comemore+

Sistema de RSVP para convites. Flask + MySQL + Docker.

**Objetivo:** evoluir de **single-tenant** (um aniversário, hoje) para **SaaS multi-tenant**, onde N clientes se cadastram sozinhos, criam vários eventos/convites e enviam links personalizados aos convidados.

---

## ⚠️ Estado atual vs. Alvo — LEIA ANTES DE EDITAR

O `app.py` ainda é **single-tenant** (Fase 1 concluída; Fase 2 adapta a lógica).

| Tema | Hoje (no código) | Alvo (SaaS) |
|------|------------------|-------------|
| Conta de cliente | Não existe | Tabela `tenants` — **schema criado (Fase 1 ✅)** |
| Textos do convite | Tabela **global** `settings` | Por evento, dentro de `events` — **schema criado (Fase 1 ✅)** |
| Evento/convite | Não existe entidade própria | Tabela `events` — **schema criado (Fase 1 ✅)** |
| Convidado | `invitees` com FK direta p/ `users` | `invitees` com FK p/ `events` + `tenant_id` — **schema criado (Fase 1 ✅)** |
| Admin | `AdminUser` via env var + `DbUser` (sub-usuários) | Signup self-service cria `tenant` + `tenant_admin` — Fase 2 |
| Senha nova | `DEFAULT_PASSWORD=102030@` hardcoded | Convite por email + link de definição — Fase 2 |
| Migrações | `init_db()` manual (`_col_exists`/`_index_exists`) | **Alembic — operacional (Fase 1 ✅)** |

---

## Stack

**Atual:** Python 3.12, Flask 3.0, SQLAlchemy 2.0 (SQL via `text()`), Gunicorn (gthread), MySQL 8 (QueuePool), Flask-Login + Flask-WTF (CSRF), Docker Compose na VPS Hostinger, CI/CD GitHub Actions → SSH.

**Adições planejadas (todas grátis / open source — sem custo fixo):**
- **Alembic** — migrações versionadas (substitui `init_db()` manual).
- **Redis + RQ** — fila para envio de email/convites em massa (hoje é síncrono no request → trava o worker).
- **Flask-Limiter** — rate limit em login, signup, reset e `/invite/<token>`.
- **Email transacional:** Brevo (300/dia grátis) ou Resend (3.000/mês grátis), com domínio próprio + SPF/DKIM. Sair do Gmail App Password.
- **Uploads:** mover de `static/uploads` (disco) para **volume Docker nomeado**; depois Cloudflare R2 (free tier).
- **Sentry** (free tier) + `mysqldump` por cron (backup).

> **Billing fica adiado.** Lançamento em beta grátis. Stripe/Mercado Pago entram quando for cobrar — não têm custo fixo, só % por venda.

---

## Estrutura

```
project_rsvp_birthday/
├── backend/
│   ├── app.py                    # Toda a app Flask (rotas, modelos, auth) — monolito
│   ├── alembic.ini               # Config do Alembic (URL vem de env vars)
│   ├── alembic/
│   │   ├── env.py                # Lê DB_* do ambiente; suporta TEST_DB_* p/ testes
│   │   └── versions/
│   │       └── 0001_initial_saas_schema.py  # Migration inicial multi-tenant ✅
│   ├── Dockerfile
│   ├── init.sql                  # Schema single-tenant legado (ainda usado em dev)
│   ├── requirements.txt          # Inclui alembic==1.13.3
│   ├── static/
│   ├── templates/
│   ├── tests/
│   │   └── test_migration.py     # Testes de integração (pytest -m integration)
│   └── logs/
├── docs/
├── schema_comemore_saas.sql      # DDL-alvo (fonte de verdade do schema SaaS)
├── .github/workflows/deploy.yml
├── .superpowers/
├── docker-compose.yml            # inclui service backend-test (profile=test)
├── pytest.ini                    # Raiz: addopts exclui integration por default
├── backend/pytest.ini            # Registra marker integration no container
├── requirements-dev.txt
├── VERSION                       # Lido em runtime como APP_VERSION
├── .env.example
└── .env                          # Nunca versionado
```

---

## Schema-alvo (multi-tenant)

Fonte de verdade do DDL: **`schema_comemore_saas.sql`** (raiz do projeto). Tabelas:

- **`tenants`** — conta do cliente. Raiz da árvore: apagar tenant cascateia e remove tudo dele (LGPD).
- **`users`** — agora com `tenant_id` e `role` (`tenant_admin`/`member`). `email` UNIQUE **global** (login resolve o tenant); `username` UNIQUE **por tenant**.
- **`events`** — **núcleo do produto**. Cada cliente cria N eventos. Os textos que estavam em `settings` migram para cá. `slug` público não-sequencial.
- **`invitees`** — FK para `events`. Carrega **`tenant_id` desnormalizado** de propósito (isolamento barato sem JOIN). `token` UNIQUE global (vai na URL pública).
- **`password_reset_tokens`** — inalterado; `user_id` já carrega o tenant.

**IDs:** PKs `BIGINT AUTO_INCREMENT` (rápidas p/ FK). `slug`/`token` públicos são aleatórios via `secrets.token_urlsafe()` — nada de URL enumerável.

> **Nota p/ quem vem do SQL Server:** `invitees` tem dois caminhos de cascade até `tenants` (direto e via `events`). No SQL Server isso dá erro (*multiple cascade paths*); no **MySQL/InnoDB é permitido e correto** — não "conserte".

---

## 🔒 Regra de ouro — isolamento por tenant

**TODA query filtra por `tenant_id`. Sem exceção.** É o ponto onde vaza dado de um cliente para outro — o pior bug possível num SaaS. Centralize isso (helper/escopo de sessão) e cubra com teste que prove que tenant A nunca enxerga dado de B.

---

## Auth e Níveis (alvo)

- Signup público cria `tenant` + primeiro usuário `tenant_admin` (sai `ADMIN_USER`/`ADMIN_PASS` por env).
- `role`: `tenant_admin` (gerencia o tenant, vê tudo do tenant) e `member` (vê só os eventos que criou — `events.owner_user_id`).
- Novos membros: convite por email + link de senha (sem senha padrão hardcoded).
- Mantém: bcrypt (Werkzeug), CSRF (Flask-WTF), `must_change_password`.
- **`ADMIN_EMAIL`** (env var, **TRANSITÓRIA — sai na Fase 2D**): email do `AdminUser` para login enquanto o signup (2C) não existir. Após o signup criar um `DbUser` com `role=tenant_admin`, este bloco e as vars `ADMIN_USER`/`ADMIN_PASS`/`ADMIN_EMAIL` são removidos. Login é **exclusivamente por email** (UNIQUE global) — username não autentica.

---

## Roadmap faseado

1. **✅ Fase 1 — Fundação de schema (concluída):** Alembic 1.13.3 instalado; migration `0001` cria `tenants`, `users` (com `tenant_id`+`role`), `events`, `invitees` (com `tenant_id` desnormalizado e dois caminhos de FK cascade), `password_reset_tokens`. Testes de integração (9) validam schema, índices de isolamento e FKs. `app.py` intacto.
2. **🔜 Fase 2 — App multi-tenant (próxima):**
   - Remover `init_db()`, `_col_exists()`, `_index_exists()` e `init.sql` do compose.
   - Startup do container roda `alembic upgrade head` antes do gunicorn.
   - Adaptar `AdminUser`/`DbUser` → `TenantAdmin`/`Member` com `tenant_id`.
   - Reescrever queries para filtrar `tenant_id` em toda leitura/escrita.
   - Rota `/signup`: cria `tenant` + primeiro usuário `role=tenant_admin`.
   - Testes de isolamento: prova que tenant A nunca vê dados de tenant B.
3. **Fase 3 — Escala:** email transacional (Brevo/Resend) + fila (Redis/RQ) + uploads em volume nomeado.
4. **Fase 4 — Produto:** enforcement de limites por plano + painel super-admin do SaaS (dono).
5. **Fase 5 — Conformidade:** LGPD (termos, exclusão real, rate limiting) + Sentry + backup automático testado.

---

## Restrições do projeto

- **Nada com custo fixo agora.** Só free tier / open source.
- Manter **Docker Compose**. Toda mudança de schema via **Alembic** (nunca alterar schema na mão com cliente em produção).
- Não quebrar o que já roda sem avisar e propor plano antes.

---

## Convenções

- SQL via `text()` do SQLAlchemy com parâmetros nomeados — sem concatenação (mantém).
- **Todo acesso a dados filtra `tenant_id`.**
- Uploads: UUID (`uuid4().hex`) + `secure_filename`; extensões `jpg/jpeg/png/mp4` (máx 50MB). Mover p/ volume nomeado → object storage.
- `slug`/`token` públicos via `secrets.token_urlsafe()`; PKs internas sequenciais.
- Charset `utf8mb4` (acentos PT-BR e emojis).
- Versão lida de `VERSION` e injetada nos templates via `context_processor`.
