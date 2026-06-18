# Comemore+ 🎉
Sistema de RSVP para convites de aniversário — v1.2.3

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
│       └── change_password.html
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
```

> `ADMIN_PASS` deve ser o hash gerado com `generate_password_hash()` do Werkzeug — nunca a senha em texto puro.

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

## 🗃️ Banco de Dados

As tabelas são criadas automaticamente via `init.sql`. O sistema também aplica migrações incrementais em cada inicialização.

| Tabela | Descrição |
|--------|-----------|
| `users` | Sub-usuários do painel |
| `invitees` | Convidados, tokens únicos e respostas |
| `settings` | Textos configuráveis do convite |

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
