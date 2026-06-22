# Comemore+ 🎉
Sistema de RSVP para convites de aniversário — v1.2.9

Aplicação web desenvolvida com **Flask**, **MySQL** e **Docker** que permite o envio de convites personalizados com link único e o acompanhamento das respostas dos convidados em tempo real.

---

## ✨ Funcionalidades

- Convites com link único por convidado
- Página pública de confirmação (Sim / Não) com campo de observação
- Upload de mídia personalizada por convidado (imagem ou vídeo)
- Painel administrativo protegido por login
- Estatísticas em tempo real (confirmados / recusados / aguardando)
- Envio direto via WhatsApp com link pré-preenchido
- Exportação da lista de convidados para Excel (.xlsx)
- Textos do convite configuráveis pelo painel
- Gerenciamento de sub-usuários (cada um vê apenas seus próprios convidados)
- Troca de senha obrigatória para novos usuários
- **Reset de senha self-service** por username ou email (link enviado por email)
- Deploy automatizado via GitHub Actions

---

## 📦 Estrutura do Projeto

```
project_rsvp_birthday/
├── backend/
│   ├── app.py               # Aplicação principal Flask
│   ├── Dockerfile           # Imagem Python 3.12-slim
│   ├── init.sql             # Criação das tabelas MySQL
│   ├── requirements.txt     # Dependências Python
│   ├── static/
│   │   ├── admin.css        # Estilo do painel admin
│   │   └── imagen.jpg       # Imagem da página de convite
│   └── templates/
│       ├── base.html
│       ├── login.html
│       ├── invite.html
│       ├── admin_responses.html
│       ├── admin_users.html
│       ├── change_password.html
│       ├── forgot_password.html
│       └── reset_password.html
├── .github/
│   └── workflows/
│       └── deploy.yml       # CI/CD: push em main → deploy SSH
├── .env                     # Variáveis de ambiente (não versionado)
├── .gitignore
├── VERSION                  # Versão atual da aplicação
└── docker-compose.yml       # Orquestração dos containers
```

---

## 🚀 Como Executar

### 1. Pré-requisitos

- Docker + Docker Compose instalados

### 2. Configurar variáveis de ambiente

Crie um arquivo `.env` na raiz:

```env
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=sua_senha_mysql
DB_HOST=db

ADMIN_USER=admin
ADMIN_PASS=hash_bcrypt_da_senha

SECRET_KEY=chave_secreta_flask_aleatoria

# Opcionais
TZ_OFFSET_HOURS=-3
LOG_FILE=logs/app.log
UPLOAD_FOLDER=static/uploads
DEFAULT_PASSWORD=102030@

# Email SMTP — necessário para reset de senha self-service
EMAIL_SMTP=smtp.gmail.com
EMAIL_PORTA=587
EMAIL_USER=seu_email@gmail.com
EMAIL_PASS=app_password_gmail

# URL base usada nos links de email
APP_BASE_URL=https://seudominio.com.br
```

> `ADMIN_PASS` deve ser o hash gerado com `generate_password_hash()` do Werkzeug — nunca a senha em texto puro.

> `EMAIL_PASS` deve ser um **App Password** do Google. Gere em: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

> `APP_BASE_URL` sem barra no final.

### 3. Subir os containers

```bash
docker compose up --build
```

- Painel admin: [http://localhost:3000/login](http://localhost:3000/login)
- Convites: `http://localhost:3000/invite/<token>`

---

## 🛠️ Acesso

| Tipo | Usuário | Senha |
|------|---------|-------|
| Super admin | valor de `ADMIN_USER` no `.env` | valor de `ADMIN_PASS` (hash) |
| Sub-usuário | criado no painel `/admin/usuarios` | `102030@` (padrão, troca obrigatória no primeiro login) |

---

## 👥 Níveis de Acesso

- **Super admin** — acesso total: vê todos os convidados, gerencia sub-usuários, edita textos
- **Sub-usuário** — vê e gerencia apenas os convidados que ele mesmo cadastrou

---

## 🗂️ Rotas

| Rota | Acesso | Descrição |
|------|--------|-----------|
| `/login` | Público | Login |
| `/forgot_password` | Público | Solicitar reset de senha (username ou email) |
| `/reset_password/<token>` | Público | Redefinir senha via link enviado por email |
| `/invite/<token>` | Público | Página de confirmação do convidado |
| `/admin/respostas` | Login | Lista de respostas com paginação e busca |
| `/admin/exportar_xlsx` | Login | Download da lista em Excel |
| `/admin/convidados/add` | Login | Adicionar convidado |
| `/admin/textos` | Super admin | Editar textos do convite |
| `/admin/usuarios` | Super admin | Gerenciar sub-usuários |
| `/change_password` | Login (DbUser) | Troca de senha obrigatória |

---

## 🗃️ Banco de Dados

As migrações são gerenciadas pelo **Alembic**. Para aplicar o schema num banco vazio:

```bash
# Aplica todas as migrations (banco vazio → schema SaaS multi-tenant)
docker compose exec backend alembic upgrade head

# Reverte tudo (apenas para dev/teste)
docker compose exec backend alembic downgrade base
```

Schema SaaS multi-tenant (fonte de verdade: `schema_comemore_saas.sql`):

| Tabela | Descrição |
|--------|-----------|
| `tenants` | Conta do cliente SaaS. Raiz da árvore de FK (apagar cascateia tudo). |
| `users` | Usuários com `tenant_id` e `role` (`tenant_admin`/`member`). Email UNIQUE global. |
| `events` | Núcleo do produto — N eventos por tenant, com textos do convite por evento. |
| `invitees` | Convidados com `tenant_id` desnormalizado e `token` UNIQUE global. |
| `password_reset_tokens` | Tokens de reset com TTL de 1h e flag `used`. |

> **Nota:** `invitees` tem dois caminhos de FK cascade até `tenants` (direto e via `events`). MySQL/InnoDB aceita; SQL Server bloquearia com *multiple cascade paths*.

### Testes de integração

```bash
# Valida schema, índices de tenant_id e FKs num banco rsvp_test dedicado
docker compose --profile test run --rm backend-test
```

---

## 🔄 CI/CD

Push na branch `main` dispara deploy automático via GitHub Actions:

1. Conecta na VPS via SSH
2. `git pull origin main`
3. `docker compose up -d --build --remove-orphans`
4. Remove imagens antigas

Secrets necessários no repositório: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`, `VPS_PATH`.

---

## 📄 Licença

Este projeto é open-source e pode ser utilizado livremente para fins pessoais ou educativos.
