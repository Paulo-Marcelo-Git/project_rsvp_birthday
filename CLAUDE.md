# CLAUDE.md — Comemore+

Sistema de RSVP para convites de aniversário. Flask + MySQL + Docker.

## Stack

- **Backend:** Python 3.12, Flask 3.0, SQLAlchemy 2.0, Gunicorn (gthread)
- **Banco:** MySQL 8, pool de conexões via QueuePool
- **Auth:** Flask-Login + Flask-WTF (CSRF), dois níveis de usuário
- **Deploy:** Docker Compose na VPS (Hostinger), CI/CD via GitHub Actions → SSH

## Estrutura

```
project_rsvp_birthday/
├── backend/
│   ├── app.py               # Toda a aplicação Flask (rotas, modelos, auth)
│   ├── Dockerfile           # Python 3.12-slim, instala requirements.txt
│   ├── init.sql             # Criação das tabelas e dados iniciais de settings
│   ├── requirements.txt
│   ├── static/
│   │   ├── admin.css
│   │   └── imagen.jpg
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── invite.html
│       ├── admin_responses.html
│       ├── admin_users.html
│       └── change_password.html
├── .github/workflows/deploy.yml   # Push em main → deploy SSH na VPS
├── docker-compose.yml
├── VERSION                        # Lido em runtime como APP_VERSION
└── .env                           # Nunca versionado
```

## Variáveis de Ambiente (.env)

```env
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=senha_mysql
DB_HOST=db

ADMIN_USER=admin
ADMIN_PASS=hash_bcrypt_da_senha   # gerado com generate_password_hash()

SECRET_KEY=chave_flask_aleatoria

# Opcionais
TZ_OFFSET_HOURS=-3                # Ajuste de fuso nas datas (padrão: -3)
LOG_FILE=logs/app.log
UPLOAD_FOLDER=static/uploads
DEFAULT_PASSWORD=102030@          # Senha padrão para novos sub-usuários
```

`ADMIN_PASS` deve ser o hash bcrypt gerado por `generate_password_hash()` do Werkzeug.

## Como rodar localmente

```bash
cp .env.example .env   # editar variáveis
docker compose up --build
```

Painel admin: `http://localhost:3000/login`
Convite: `http://localhost:3000/invite/<token>`

## Banco de Dados

Três tabelas criadas pelo `init.sql` (e garantidas em runtime por `init_db()`):

- **users** — sub-usuários com `must_change_password` flag
- **invitees** — convidados, token único, resposta, FK para users
- **settings** — textos configuráveis do convite (`question_text`, `yes_text`, etc.)

`init_db()` também aplica migrações incrementais via `_col_exists()` para colunas adicionadas depois do primeiro deploy.

## Auth e Níveis de Acesso

Dois tipos de usuário:
- **AdminUser** (`id="admin"`, `is_super_admin=True`) — credenciais via env var, acesso total
- **DbUser** (`id="user_<db_id>"`) — criado no painel, vê apenas seus próprios convidados

Sub-usuários com `must_change_password=True` são redirecionados para `/change_password` em toda requisição (via `before_request`).

Senha padrão para novos usuários: `102030@` (constante `DEFAULT_PASSWORD` em `app.py:70`).

## Rotas principais

| Rota | Acesso | Descrição |
|------|--------|-----------|
| `/login` | Público | Login |
| `/invite/<token>` | Público | Página de confirmação do convidado |
| `/admin/respostas` | Login | Lista de respostas com paginação e busca |
| `/admin/exportar_xlsx` | Login | Download da lista em Excel |
| `/admin/convidados/add` | Login | Adicionar convidado |
| `/admin/textos` | Super admin | Editar textos do convite |
| `/admin/usuarios` | Super admin | Gerenciar sub-usuários |
| `/change_password` | Login (DbUser) | Troca de senha obrigatória |

## Deploy

Push para `main` aciona o workflow `.github/workflows/deploy.yml`:
1. SSH na VPS (secrets: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`, `VPS_PATH`)
2. `git pull origin main`
3. `docker compose up -d --build --remove-orphans`
4. `docker image prune -f`

O backend roda na porta interna 8000, exposta apenas em `127.0.0.1:3000` (nginx/proxy na frente).
Usuário do container: `1002:1002` (deve coincidir com o UID do usuário na VPS).

## Convenções

- Todo SQL usa `text()` do SQLAlchemy com parâmetros nomeados — sem concatenação direta.
- Uploads salvos com nome UUID (`uuid4().hex`) + extensão original via `secure_filename`.
- Extensões permitidas para upload: `jpg`, `jpeg`, `png`, `mp4` (máx 50MB).
- Versão da aplicação lida do arquivo `VERSION` na raiz e injetada nos templates via `context_processor`.
