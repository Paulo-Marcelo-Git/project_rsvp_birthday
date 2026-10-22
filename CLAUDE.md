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
| **Fase 4** | ✅ Concluída | `plan_limits` + migration 0004, enforcement max_invitees/members, botão Usuários condicional, login bloqueado para tenant suspenso, painel `/superadmin` com set_plan/suspend/reactivate, `superadmin_required` por role (`super_admin`) |
| **Fase 5** | ✅ Concluída | Flask-Limiter (Redis/memory storage), rate limiting em 5 rotas (login/signup/forgot/invite), /termos + /privacidade (LGPD), aceite obrigatório no signup + `accepted_terms_at`, migration 0005, fix `datetime.utcnow()`, supressão warning RQ serializer, integration test fluxo completo |
| **Deploy** | ✅ Concluída | Live em produção na VPS Hostinger (`https://zapbyte.com.br`), HTTPS via Certbot, CI/CD GitHub Actions → SSH funcionando (deploy automático a cada push em `main`). Fix de bug real: cron do serviço `backup` não herdava env vars do container (`DB_NAME: unbound variable`), backups automáticos silenciosamente quebrados — corrigido gravando `VAR=valor` no topo do crontab |
| **Super-admin por role** | ✅ Concluída | migration 0006 (ENUM `super_admin` + tenant reservado `Comemore+ System`), `flask create-superadmin`, `superadmin_required` por role, super-admin restrito às rotas do painel (`restrict_super_admin_to_panel`) |
| **Trial** | ✅ Concluída | Free: 14 dias a partir do 1º login (`repo.TRIAL_DAYS`), aviso (modal) nos últimos 3 dias (`TRIAL_WARNING_DAYS`), suspensão automática ao expirar (`suspended_reason=trial_expired`); migrations 0007 (backfill) e 0008 (`tenants.suspended_reason`); lógica em `repo.start_tenant_trial` + `_check_tenant_access` (`app.py`) |
| **Imagem por evento + member** | ✅ Concluída | Imagem padrão obrigatória por evento (convidado pode ter a própria), signup sem evento + /admin/primeiro-evento, responsável por evento (member funcional), backup de uploads, validação de conteúdo + nosniff, limpeza de órfãos (CLI cleanup-orphan-uploads), fixes: textos no evento certo, respostas por evento, 413 |

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
- Flask-Limiter 3.8.0 — rate limiting com Redis storage + fallback memory://
- flasgger 0.9.7.1 — Swagger em `/apidocs` (só tenant_admin); openpyxl 3.1.2 — export xlsx; debugpy 1.8.21 — debug remoto (dev only)
- Docker Compose na VPS Hostinger, CI/CD GitHub Actions → SSH
- Serviços Docker: `rsvp_mysql`, `rsvp_backend`, `rsvp_worker`, `rsvp_redis`, `rsvp_backup`
- Volumes: `db_data`, `backup_data`, `uploads_data`, `redis_data`. O `backup` monta `uploads_data:/uploads:ro` e gera `comemore_uploads_*.tar.gz` com a mesma retenção do dump SQL; `restore-uploads.sh` restaura por default em `/tmp/uploads_restore_test`.
- pytest (453 unit tests + 50 integration tests deselected sem MySQL real)

---

## Estrutura

```
project_rsvp_birthday/
├── backend/
│   ├── app.py               # Rotas Flask — usa repo.py para todo acesso a dados
│   ├── repo.py              # TODA query com tenant_id obrigatório
│   ├── tasks.py             # Funções de email (send_*) — sem Flask/SQLAlchemy, pickle-safe para RQ
│   ├── queue_utils.py       # enqueue_email(): fallback síncrono se REDIS_URL ausente
│   ├── log_utils.py         # Máscaras (e-mail/URL/token), RedactingFormatter, DailyFileHandler (logs/app-AAAA-MM-DD.log)
│   ├── gunicorn.conf.py     # Args do gunicorn + logger_class que mascara tokens no access log
│   ├── alembic/             # Migrations versionadas (fonte de verdade do schema)
│   │   └── versions/
│   │       ├── 0001_initial_saas_schema.py
│   │       ├── 0002_seed_default_tenant.py
│   │       ├── 0003_add_email_verification_tokens.py
│   │       ├── 0004_plan_limits.py
│   │       ├── 0005_accepted_terms_at.py
│   │       ├── 0006_super_admin_role.py
│   │       ├── 0007_trial_expiration_backfill.py
│   │       └── 0008_tenant_suspended_reason.py
│   ├── Dockerfile
│   ├── entrypoint.sh        # Roda `alembic upgrade head` antes do gunicorn (*.sh text eol=lf via .gitattributes)
│   ├── requirements.txt
│   ├── static/
│   ├── templates/
│   └── tests/               # pytest — 453 unit tests + 50 integration (marcados @pytest.mark.integration)
├── backup/                  # Dockerfile + backup.sh + restore.sh + restore-uploads.sh + purge-logs.sh (mysqldump + tar.gz dos uploads + limpeza dos logs, diário via cron)
├── docs/
│   ├── superpowers/         # plans/ (histórico por sub-fase) e specs/ — gitignored, só local
│   ├── smoke-tests/         # roteiros de smoke test e2e
│   └── design-system/       # design.md, design-guidelines.md, design-components.md
├── DEPLOY_CHECKLIST.md      # Checklist de deploy na VPS
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

- **`tenants`** — conta do cliente. Raiz da árvore (apagar cascateia tudo = LGPD). Tem `plan` (free/pro/business), `status` (trial/active/suspended/canceled), `trial_ends_at` (NULL até o 1º login) e `suspended_reason` (trial_expired/manual, migration 0008).
- **`users`** — `tenant_id` + `role` (`tenant_admin`/`member`/`super_admin`). `email` UNIQUE global; `username` UNIQUE por tenant. Conta `super_admin` mora no tenant reservado `Comemore+ System` (migration 0006), nunca num tenant de cliente real.
- **`events`** — núcleo do produto. N eventos por tenant. Textos do convite por evento. `slug` aleatório. `media_url` = imagem padrão do convite (obrigatória na criação); `owner_user_id` = responsável (member gerencia só os seus).
- **`invitees`** — FK para `events` + `tenant_id` desnormalizado (isolamento barato sem JOIN). `token` UNIQUE global.
- **`password_reset_tokens`** — TTL 1h, flag `used`.
- **`email_verification_tokens`** — TTL 24h, flag `used`. Usuário nasce `is_active=0`, ativa via link.
- **`plan_limits`** — PK `plan` ENUM(free/pro/business); limites `max_events`, `max_invitees` (**por evento**), `max_members` (NULL = ilimitado). Seed: free(2, 50, 1), pro(10, 500, 5), business(NULL).
- **`users.accepted_terms_at`** — nullable DateTime; gravado no signup com timestamp UTC do aceite dos termos (migration 0005).

---

## Auth

- Login por **email-only** (UNIQUE global resolve o tenant). Sem fallback de username.
- Login checa o tenant (`_check_tenant_access`): bloqueia `suspended`/`canceled`; no Free inicia o trial no 1º login, suspende ao expirar e avisa nos últimos 3 dias.
- `/uploads/<filename>`: usuário logado vê só mídia do próprio tenant; convidado (sessão) vê a própria imagem **ou** a imagem do seu evento.
- Roles: `tenant_admin` (gerencia o tenant) e `member` (gerencia os eventos dos quais é responsável: convidados, imagem, textos, tema; só o tenant_admin cria eventos e define o responsável).
- Signup cria `tenant` + `tenant_admin` (sem evento) numa **transação atômica** (rollback total se falhar); o primeiro evento é criado em `/admin/primeiro-evento`.
- Novos membros: senha temporária aleatória (`secrets.token_urlsafe(12)`) + email de convite (TTL 72h).
- `SKIP_EMAIL_VERIFICATION=true` (dev only, default OFF) — ausência da var = verificação obrigatória.
- Sem `AdminUser` por env var, sem `DEFAULT_PASSWORD` hardcoded.
- Super-admin: `role='super_admin'`, provisionado via `flask create-superadmin` (lê `SUPERADMIN_EMAIL`, cria a conta no tenant reservado com senha temporária + email de convite). Loga direto em `/superadmin` e fica restrito a essas rotas — não acessa o painel de tenant normal.

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
SKIP_EMAIL_VERIFICATION=          # 1/true/yes ativa bypass (default OFF = verificação obrigatória)

# Fila de email assíncrono (RQ)
REDIS_URL=redis://redis:6379/0    # ausente → executa síncrono (dev); presente → só via fila

# Backup
BACKUP_RETENTION_DAYS=7

# Super-admin do SaaS — acessa /superadmin para gerenciar tenants
# ⚠ ATENÇÃO: este email NÃO pode já existir como usuário comum no banco.
# `flask create-superadmin` recusa (não promove automaticamente um usuário existente).
# SUPERADMIN_EMAIL=admin@seudominio.com

# Opcionais
# EMAIL_FROM=noreply@seudominio.com  # remetente validado no provedor; fallback = EMAIL_USER
# TZ_OFFSET_HOURS=-3                 # default -3 (BRT)
# LOG_FILE=logs/app.log              # default; nome-base → logs/app-AAAA-MM-DD.log (1 arquivo/dia, UTC); não altere — o purge só apaga app-*.log em ./logs
# LOG_RETENTION_DAYS=5               # default; dias de log mantidos (purge-logs.sh no container backup)
# UPLOAD_FOLDER=/app/uploads         # default (volume uploads_data)
# DEBUGPY_ENABLED=true               # dev only — entrypoint troca gunicorn por flask run + debugpy (porta 5678)
```

---

## Convenções

- SQL via `text()` com parâmetros nomeados — sem concatenação.
- **Todo acesso a `events`/`invitees`/`users` passa pelo `repo.py` com `tenant_id` obrigatório.**
- Uploads: UUID (`uuid4().hex`) + `secure_filename`; extensões `jpg/jpeg/png/mp4` com validação de magic bytes (`validate_media_content`), máx 50MB (413 tratado com flash + redirect seguro; guarda no navegador em `base.html`). `X-Content-Type-Options: nosniff` em todas as respostas. Órfãos via `flask cleanup-orphan-uploads [--apply] [--min-age-minutes N]` (dry-run por default; ignora arquivos mais novos que 60 min por default).
- `slug`/`token` públicos via `secrets.token_urlsafe()`; PKs internas sequenciais.
- Charset `utf8mb4` (acentos PT-BR e emojis).
- Versão lida de `VERSION` e injetada via `context_processor`.
- `*.sh text eol=lf` no `.gitattributes` — LF forçado, CRLF quebra container Linux.
- **Testes: sempre `bash scripts/test.sh [args do pytest]`** (ou `bash scripts/test.sh --scratch <dir> [args]` para cópia scratch com `<dir>/repo` e `<dir>/uploads`). O script já está liberado nas permissões; nunca monte comando composto (`S=...; cd ... && UPLOAD_FOLDER=... timeout ... pytest | tail`), que exige aprovação manual. Vale também para subagentes. Caminhos de teste relativos à raiz (`backend/tests/test_x.py`) no Python do host; no fallback Docker o cwd é `backend/` (`tests/test_x.py`).
- **Logs sem dado pessoal (LGPD):** log identifica por ID (`user_id`, `tenant_id`, `event_id`, `invitee_id`); e-mail só via `mask_email()`, exceção só via `exc_label(e)`/`type(e).__name__` — nunca `{e}` cru, `logger.exception` ou `exc_info` em `app.py`/`tasks.py`/`queue_utils.py`. Rede de segurança: `RedactingFormatter` nos handlers do app e do gunicorn, `hide_parameters=True` no engine. Jobs RQ com `description=func.__name__`. `tests/test_log_sem_pii.py` (fluxos + varredura AST) garante.

---

## Roadmap

| Fase | Escopo | Status |
|------|--------|--------|
| 1 | Alembic + schema multi-tenant | ✅ |
| 2A–2D | App multi-tenant: isolamento, login, signup, limpeza de legado | ✅ |
| 3A–3D | Backup + uploads em volume + fila Redis/RQ + guia email transacional | ✅ |
| **4** | **Enforcement de limites por plano + painel super-admin do SaaS** | ✅ |
| **5** | **Rate limiting (Flask-Limiter), LGPD (/termos + /privacidade + aceite), migration 0005, fixes técnicos** | ✅ |
| **Deploy** | **Deploy na VPS Hostinger** (ver `DEPLOY_CHECKLIST.md`) | ✅ |
| **Imagem por evento + member** | **Imagem padrão por evento, member responsável, signup sem evento, uploads seguros** (v1.4.0) | ✅ (deploy 2026-10-13) |
| **Beta** | **Beta fechado** — app já está live, falta só convidar usuários reais | 🔜 |
