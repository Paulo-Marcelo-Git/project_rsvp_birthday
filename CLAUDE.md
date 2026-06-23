# CLAUDE.md — Comemore+

Sistema de RSVP para convites. Flask + MySQL + Docker.

**Objetivo:** SaaS multi-tenant onde N clientes se cadastram sozinhos, criam eventos/convites personalizados e enviam links para convidados.

---

## Estado atual

| Fase | Status | O que entregou |
|------|--------|----------------|
| Fase 1 | ✅ Concluída | Alembic + schema multi-tenant (migrations 0001–0003) |
| Fase 2A | ✅ Concluída | `repo.py` com `tenant_id` obrigatório, isolamento provado em MySQL real (8 testes), boot via Alembic |
| Fase 2B | ✅ Concluída | Login email-only, regime único, sem fallback de username |
| Fase 2C | ✅ Concluída | Signup self-service, verificação de email, transação atômica, reenvio de token |
| Fase 2D | ✅ Concluída | `AdminUser`/`ADMIN_EMAIL`/`DEFAULT_PASSWORD`/`super_admin_required` removidos. Grep limpo. 82/82 verdes |
| Fase 3A | ✅ Concluída | `mysqldump` diário via cron, volume `backup_data`, `restore.sh` documentado no README |
| Fase 3B | ✅ Concluída | Volume `uploads_data` em `/app/uploads`, rota `/uploads/<filename>` com isolamento de tenant, session-token para convidados (sem query string) |
| Fase 3C | ✅ Concluída | `tasks.py` + `queue_utils.py`, RQ em 6 call sites, `redis` + `worker` no Compose, fallback síncrono só quando `REDIS_URL` ausente |
| Fase 3D | ✅ Concluída | Guia Brevo × Resend, SPF/DKIM/DMARC, valores exatos no `.env.example` |
| **Fase 4** | ✅ Concluída | `plan_limits` + migration 0004, enforcement max_invitees/members, botão Usuários condicional, login bloqueado para tenant suspenso, painel `/superadmin` com set_plan/suspend/reactivate, `superadmin_required` com check de config inválida |
| **Fase 5** | 🔜 Próxima | LGPD (termos, exclusão real, rate limiting) + Sentry + monitoramento |

---

## ⚠️ Regras inegociáveis — leia antes de editar

1. **TODA query filtra `tenant_id`.** É o ponto onde vaza dado entre clientes. Centralize no `repo.py` — nenhuma rota monta SQL de `events`/`invitees`/`users` direto.
2. **Schema só via Alembic.** Nunca altere tabelas na mão. Toda mudança de schema = nova migration versionada.
3. **Nada com custo fixo.** Só free tier / open source. Não introduza dependência paga.
4. **Plano antes de código.** Apresente plano faseado, pare para aprovação, implemente sub-fase por sub-fase.
5. **App funcional a cada commit.** Nenhum commit deixa o sistema sem forma de login ou com rota quebrada.

---

## Stack

**Atual:**
- Python 3.12, Flask 3.0, SQLAlchemy 2.0 (`text()` com parâmetros nomeados — sem concatenação), Gunicorn (gthread)
- MySQL 8 (QueuePool), Alembic 1.13.3
- Flask-Login + Flask-WTF (CSRF)
- Redis 7-alpine + RQ 1.16.2 + redis-py 5.0.7 — fila de email assíncrono (`tasks.py` + `queue_utils.py`)
- Docker Compose na VPS Hostinger, CI/CD GitHub Actions → SSH
- Serviços Docker: `rsvp_mysql`, `rsvp_backend`, `rsvp_worker`, `rsvp_redis`, `rsvp_backup`
- pytest (102 testes: unit + repo + isolamento + migration + integração + uploads + queue)

---

## Estrutura

```
project_rsvp_birthday/
├── backend/
│   ├── app.py               # Rotas Flask — usa repo.py para todo acesso a dados
│   ├── repo.py              # TODA query com tenant_id obrigatório
│   ├── tasks.py             # Funções de email (send_*) — sem Flask/SQLAlchemy, pickle-safe para RQ
│   ├── queue_utils.py       # enqueue_email(): fallback síncrono se REDIS_URL ausente
│   ├── alembic/             # Migrations versionadas (fonte de verdade do schema)
│   │   └── versions/
│   │       ├── 0001_initial_saas_schema.py
│   │       ├── 0002_seed_default_tenant.py
│   │       └── 0003_email_verification_tokens.py
│   ├── Dockerfile
│   ├── entrypoint.sh        # Roda `alembic upgrade head` antes do gunicorn (*.sh text eol=lf via .gitattributes)
│   ├── requirements.txt
│   ├── static/
│   ├── templates/
│   └── tests/               # pytest — 102 testes
├── backup/                  # Dockerfile + backup.sh + restore.sh (mysqldump diário via cron)
├── schema_comemore_saas.sql # DDL de referência (fonte de verdade APLICÁVEL é o Alembic)
├── docs/superpowers/plans/  # Histórico de planos por sub-fase
├── .github/workflows/deploy.yml
├── .gitattributes           # *.sh text eol=lf — LF forçado em scripts de boot
├── docker-compose.yml       # Serviços: db, redis, backend, worker, backup, backend-test
├── pytest.ini
├── VERSION
├── .env.example
└── .env                     # Nunca versionado
```

---

## Schema (fonte de verdade: Alembic)

- **`tenants`** — conta do cliente. Raiz da árvore (apagar cascateia tudo = LGPD).
- **`users`** — `tenant_id` + `role` (`tenant_admin`/`member`). `email` UNIQUE global; `username` UNIQUE por tenant.
- **`events`** — núcleo do produto. N eventos por tenant. Textos do convite por evento. `slug` aleatório.
- **`invitees`** — FK para `events` + `tenant_id` desnormalizado (isolamento barato sem JOIN). `token` UNIQUE global.
- **`password_reset_tokens`** — TTL 1h, flag `used`.
- **`email_verification_tokens`** — TTL 24h, flag `used`. Usuário nasce `is_active=0`, ativa via link.

---

## Auth

- Login por **email-only** (UNIQUE global resolve o tenant). Sem fallback de username.
- Roles: `tenant_admin` (gerencia o tenant) e `member` (vê só os eventos que criou).
- Signup cria `tenant` + `tenant_admin` + evento default numa **transação atômica** (rollback total se falhar).
- Novos membros: senha temporária aleatória (`secrets.token_urlsafe(12)`) + email de convite (TTL 72h).
- `SKIP_EMAIL_VERIFICATION=true` (dev only, default OFF) — ausência da var = verificação obrigatória.
- Sem `AdminUser` por env var, sem `DEFAULT_PASSWORD` hardcoded.

---

## Variáveis de ambiente (.env)

```env
# Banco
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=senha_mysql
DB_HOST=db

# Flask
SECRET_KEY=chave_flask_aleatoria

# Email SMTP — use Brevo (300/dia grátis) ou Resend (3000/mês grátis); ver README
EMAIL_SMTP=smtp-relay.brevo.com
EMAIL_PORTA=587
EMAIL_USER=seu-login@brevo.com
EMAIL_PASS=xSMTP-KEY-BREVO

# URL base nos links de email
APP_BASE_URL=https://seudominio.com.br

# Dev only — jamais em produção
SKIP_EMAIL_VERIFICATION=          # true ativa bypass (default OFF = verificação obrigatória)

# Fila de email assíncrono (RQ)
REDIS_URL=redis://redis:6379/0    # ausente → executa síncrono (dev); presente → só via fila

# Backup
BACKUP_RETENTION_DAYS=7

# Super-admin do SaaS — email NÃO deve existir como tenant no banco
# SUPERADMIN_EMAIL=admin@seudominio.com
```

---

## Convenções

- SQL via `text()` com parâmetros nomeados — sem concatenação.
- **Todo acesso a `events`/`invitees`/`users` passa pelo `repo.py` com `tenant_id` obrigatório.**
- Uploads: UUID (`uuid4().hex`) + `secure_filename`; extensões `jpg/jpeg/png/mp4` (máx 50MB).
- `slug`/`token` públicos via `secrets.token_urlsafe()`; PKs internas sequenciais.
- Charset `utf8mb4` (acentos PT-BR e emojis).
- Versão lida de `VERSION` e injetada via `context_processor`.
- `*.sh text eol=lf` no `.gitattributes` — LF forçado, CRLF quebra container Linux.

---

## Roadmap

| Fase | Escopo | Status |
|------|--------|--------|
| 1 | Alembic + schema multi-tenant | ✅ |
| 2A–2D | App multi-tenant: isolamento, login, signup, limpeza de legado | ✅ |
| 3A–3D | Backup + uploads em volume + fila Redis/RQ + guia email transacional | ✅ |
| **4** | **Enforcement de limites por plano + painel super-admin do SaaS** | ✅ |
| **5** | **LGPD (termos, exclusão real, rate limiting) + Sentry + monitoramento** | 🔜 |
