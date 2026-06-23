# Comemore+
Sistema de RSVP para convites — SaaS multi-tenant.

Aplicação web desenvolvida com **Flask**, **MySQL** e **Docker** que permite o envio de convites personalizados com link único e o acompanhamento das respostas dos convidados em tempo real.

---

## Funcionalidades

- Signup self-service: cada cliente cria sua própria conta e tenant
- Verificação de email obrigatória na criação de conta
- Convites com link único por convidado
- Página pública de confirmação (Sim / Não) com campo de observação
- Upload de mídia personalizada por convidado (imagem ou vídeo)
- Painel administrativo protegido por login
- Estatísticas em tempo real (confirmados / recusados / aguardando)
- Envio direto via WhatsApp com link pré-preenchido
- Exportação da lista de convidados para Excel (.xlsx)
- Textos do convite configuráveis pelo painel
- Gerenciamento de sub-usuários (cada um vê apenas seus próprios convidados)
- Reset de senha self-service por email (link com TTL de 1h)
- Backup automático diário com retenção configurável

---

## Como Executar

### 1. Pré-requisitos

- Docker + Docker Compose instalados

### 2. Configurar variáveis de ambiente

Copie `.env.example` para `.env` e preencha os valores:

```env
# Banco
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=senha_mysql
DB_HOST=db

# Flask
SECRET_KEY=chave_flask_aleatoria

# Email SMTP — obrigatório em produção (signup falha com erro claro sem isso)
EMAIL_SMTP=smtp.gmail.com
EMAIL_PORTA=587
EMAIL_USER=seu_email@gmail.com
EMAIL_PASS=app_password_gmail

# URL base nos links de email (sem barra no final)
APP_BASE_URL=https://seudominio.com.br

# Dev only — jamais em produção
# SKIP_EMAIL_VERIFICATION=1

# Backup (opcional — default já aplicado no container)
BACKUP_RETENTION_DAYS=7
```

> `EMAIL_PASS` deve ser um **App Password** do Google: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

### 3. Subir os containers

```bash
docker compose up --build -d
```

- Painel: [http://localhost:3000/login](http://localhost:3000/login)
- Criar conta: [http://localhost:3000/signup](http://localhost:3000/signup)
- Convites: `http://localhost:3000/invite/<token>`

---

## Níveis de Acesso

| Role | O que pode fazer |
|------|-----------------|
| `tenant_admin` | Acesso total ao tenant: vê todos os convidados, gerencia membros, edita textos |
| `member` | Vê e gerencia apenas os convidados dos seus próprios eventos |

O primeiro `tenant_admin` é criado pelo signup self-service (`/signup`).
Novos membros são criados pelo painel (`/admin/usuarios`); recebem email de convite com link para definir a senha (ou senha temporária em dev sem SMTP).

---

## Rotas

| Rota | Acesso | Descrição |
|------|--------|-----------|
| `/signup` | Público | Criar conta (tenant + tenant_admin + evento padrão) |
| `/login` | Público | Login |
| `/forgot_password` | Público | Solicitar reset de senha |
| `/reset_password/<token>` | Público | Redefinir senha via link de email |
| `/resend-verification` | Público | Reenviar link de verificação de email |
| `/invite/<token>` | Público | Página de confirmação do convidado |
| `/uploads/<filename>` | Tenant autenticado ou convidado c/ session | Serve arquivo de upload com validação de posse |
| `/admin/respostas` | Login | Lista de respostas com paginação e busca |
| `/admin/exportar_xlsx` | Login | Download da lista em Excel |
| `/admin/convidados/add` | Login | Adicionar convidado |
| `/admin/textos` | tenant_admin | Editar textos do convite |
| `/admin/usuarios` | tenant_admin | Gerenciar membros do tenant |
| `/change_password` | Login (member) | Troca de senha obrigatória |

---

## Banco de Dados

As migrações são gerenciadas pelo **Alembic** e rodam automaticamente no boot do container.

Para aplicar manualmente:

```bash
docker compose exec backend alembic upgrade head
```

Schema SaaS multi-tenant:

| Tabela | Descrição |
|--------|-----------|
| `tenants` | Conta do cliente. Raiz da árvore de FK (apagar cascateia tudo = LGPD). |
| `users` | Usuários com `tenant_id` e `role` (`tenant_admin`/`member`). Email UNIQUE global. |
| `events` | N eventos por tenant, com textos do convite por evento. |
| `invitees` | Convidados com `tenant_id` desnormalizado e `token` UNIQUE global. |
| `password_reset_tokens` | Tokens de reset com TTL de 1h e flag `used`. |
| `email_verification_tokens` | Tokens de verificação de email com TTL de 24h e flag `used`. |

---

## Backup

O container `backup` roda `mysqldump` automaticamente todo dia às **02:00 BRT / 05:00 UTC** e salva o dump comprimido em volume Docker nomeado (`backup_data`).

### Verificar se o backup rodou

```bash
docker logs rsvp_backup --tail 20
```

Saída esperada:
```
[2026-06-24 05:00:05] Iniciando backup de rsvp_db...
[2026-06-24 05:00:06] Backup salvo: comemore_20260624_050005.sql.gz (48K)
[2026-06-24 05:00:06] Retenção: 0 arquivo(s) removido(s) (>7 dias)
```

### Listar backups disponíveis

```bash
docker exec rsvp_backup ls -lh /backups/
```

### Executar backup manualmente

```bash
docker exec rsvp_backup /backup.sh
```

### Restore manual

> **Atenção:** o restore cria um banco separado (`rsvp_restore_test` por padrão) e **não toca no banco de produção**.

```bash
# Restaura o arquivo mais recente (substitua pelo nome real)
docker exec rsvp_backup sh /restore.sh /backups/comemore_YYYYMMDD_HHMMSS.sql.gz rsvp_restore_test
```

O script:
1. Cria o banco `rsvp_restore_test` (se não existir)
2. Descomprime e restaura o dump
3. Imprime `SHOW TABLES` para confirmar

Para verificar as migrations no banco restaurado:

```bash
docker exec rsvp_backend env DB_NAME=rsvp_restore_test python -m alembic upgrade head
```

---

## Uploads de Mídia

Os arquivos enviados (imagens/vídeos por convidado) são armazenados no volume Docker nomeado `uploads_data`, montado em `/app/uploads` no container.

### Comportamento por ambiente

| Ambiente | Onde ficam os arquivos |
|----------|----------------------|
| Produção / Docker | Volume nomeado `uploads_data` — persiste entre rebuilds |
| Dev local (sem Docker) | `backend/static/uploads/` (fallback do default) |

### Confirmar persistência após rebuild

```bash
# Sobe com rebuild — arquivos no volume são preservados
docker compose up --build -d

# Listar arquivos no volume (via container)
docker compose exec backend ls -lh /app/uploads/
```

### Migração de arquivos existentes

Se houver arquivos em `backend/static/uploads/` de um deploy anterior (antes da Fase 3B), copie-os para o volume:

```bash
docker compose exec backend mkdir -p /app/uploads
docker cp backend/static/uploads/. rsvp_backend:/app/uploads/
```

Após a cópia, os arquivos em `static/uploads/` no host podem ser removidos — eles não são mais servidos pelo app.

### Acesso protegido

A rota `/uploads/<filename>` não é pública:
- **Usuário logado:** o arquivo deve pertencer ao tenant do usuário autenticado
- **Convidado sem login:** session do Flask valida o token de convite contra o `media_url` do registro (sem expor o token em query string)
- Qualquer outro acesso → 404 (sem vazar existência do arquivo)

## Testes de integração

```bash
# Valida schema, índices de tenant_id e FKs num banco rsvp_test dedicado
docker compose --profile test run --rm backend-test
```

---

## CI/CD

Push na branch `main` dispara deploy automático via GitHub Actions:

1. Conecta na VPS via SSH
2. `git pull origin main`
3. `docker compose up -d --build --remove-orphans`
4. Remove imagens antigas

Secrets necessários: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`, `VPS_PATH`.

---

## Licença

Este projeto é open-source e pode ser utilizado livremente para fins pessoais ou educativos.
