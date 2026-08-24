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
- Múltiplos eventos por tenant, cada um com tema visual (padrão / menina / menino)
- Edição e exclusão de convidados já cadastrados
- Envio de email assíncrono via fila Redis + RQ (fallback síncrono em dev sem Redis)
- Rate limiting (login, signup, reset de senha, confirmação de convite) contra abuso
- Termos de uso e política de privacidade (LGPD), com aceite obrigatório no cadastro
- Limites de uso por plano (free / pro / business): eventos, convidados e membros
- Painel super-admin do SaaS: gerenciar plano e status (ativo/suspenso) de cada tenant

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
# Dev local rápido: Gmail App Password. Produção: use Brevo/Resend (ver seção
# "Configuração de Email Transacional" mais abaixo).
EMAIL_SMTP=smtp.gmail.com
EMAIL_PORTA=587
EMAIL_USER=seu_email@gmail.com
EMAIL_PASS=app_password_gmail

# URL base nos links de email (sem barra no final)
APP_BASE_URL=https://seudominio.com.br

# Dev only — jamais em produção
# SKIP_EMAIL_VERIFICATION=1

# Fila de email assíncrono (Redis + RQ) — ausente = executa síncrono (dev)
REDIS_URL=redis://redis:6379/0

# Backup (opcional — default já aplicado no container)
BACKUP_RETENTION_DAYS=7

# Super-admin do SaaS — acessa /superadmin para gerenciar tenants (plano/status)
# Este email NÃO pode existir como conta de tenant no banco, senão o acesso é bloqueado.
# SUPERADMIN_EMAIL=admin@seudominio.com
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
| `/signup` | Público | Criar conta (tenant + tenant_admin + evento padrão) — rate limit 5/hora |
| `/login` | Público | Login — rate limit 10/min |
| `/logout` | Login | Encerra a sessão |
| `/forgot_password` | Público | Solicitar reset de senha — rate limit 5/hora |
| `/reset_password/<token>` | Público | Redefinir senha via link de email |
| `/resend-verification` | Público | Reenviar link de verificação de email |
| `/verify-email/<token>` | Público | Confirma o email a partir do link (TTL 24h) |
| `/termos` | Público | Termos de uso (LGPD) |
| `/privacidade` | Público | Política de privacidade (LGPD) |
| `/invite/<token>` | Público | Página de confirmação do convidado — rate limit 30/min (GET) / 10/min (POST) |
| `/uploads/<filename>` | Tenant autenticado ou convidado c/ session | Serve arquivo de upload com validação de posse |
| `/admin/respostas` | Login | Lista de respostas com paginação e busca |
| `/admin/exportar_xlsx` | Login | Download da lista em Excel |
| `/admin/convidados/add` | Login | Adicionar convidado |
| `/admin/convidados/<id>/edit` | Login | Editar convidado |
| `/admin/convidados/<id>/delete` | Login | Excluir convidado |
| `/admin/textos` | tenant_admin | Editar textos do convite |
| `/admin/set_tema` | tenant_admin | Define o tema visual do evento (padrão/menina/menino) |
| `/admin/eventos` | Login | Lista os eventos do tenant |
| `/admin/eventos/criar` | Login | Cria um novo evento no tenant |
| `/admin/usuarios` | tenant_admin | Gerenciar membros do tenant |
| `/admin/usuarios/add` | tenant_admin | Convida um novo membro (senha temporária por email) |
| `/admin/usuarios/<id>/edit` | tenant_admin | Edita dados de um membro |
| `/admin/usuarios/<id>/reset_senha` | tenant_admin | Reenvia senha temporária a um membro |
| `/admin/usuarios/<id>/delete` | tenant_admin | Remove um membro do tenant |
| `/change_password` | Login (member) | Troca de senha obrigatória |
| `/superadmin` | Super-admin do SaaS | Lista todos os tenants do sistema |
| `/superadmin/tenant/<id>/set_plan` | Super-admin do SaaS | Altera o plano (free/pro/business) de um tenant |
| `/superadmin/tenant/<id>/suspend` | Super-admin do SaaS | Suspende o acesso de um tenant |
| `/superadmin/tenant/<id>/reactivate` | Super-admin do SaaS | Reativa um tenant suspenso |

> **Super-admin do SaaS:** acesso a `/superadmin/*` exige `role='super_admin'` gravado no banco (não mais uma comparação de email a cada request). A conta é provisionada uma única vez via `flask create-superadmin`, que lê `SUPERADMIN_EMAIL` — ver seção "Limites por Plano e Painel Super-Admin" abaixo.

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
| `tenants` | Conta do cliente. Raiz da árvore de FK (apagar cascateia tudo = LGPD). Tem `plan` (free/pro/business) e `status` (trial/active/suspended/canceled), geridos via `/superadmin`. |
| `users` | Usuários com `tenant_id` e `role` (`tenant_admin`/`member`/`super_admin`). Email UNIQUE global. `accepted_terms_at` registra o aceite dos termos no signup. |
| `events` | N eventos por tenant, com textos do convite e `theme` (padrão/menina/menino) por evento. |
| `invitees` | Convidados com `tenant_id` desnormalizado e `token` UNIQUE global. |
| `password_reset_tokens` | Tokens de reset com TTL de 1h e flag `used`. |
| `email_verification_tokens` | Tokens de verificação de email com TTL de 24h e flag `used`. |
| `plan_limits` | Limites por plano (PK `plan`): `max_events`, `max_invitees`, `max_members` (`NULL` = ilimitado). Seed: free(2, 50, 1), pro(10, 500, 5), business(ilimitado). |

---

## Configuração de Email Transacional

O app usa `smtplib` puro — **nenhum SDK proprietário necessário**. Para mudar de provedor, altere apenas os valores de `EMAIL_*` no `.env`. Zero mudança de código.

### Brevo × Resend — comparativo

| | Brevo **(recomendado)** | Resend |
|---|---|---|
| Free tier | **300 emails/dia** | 3 000/mês (≈ 100/dia) |
| SMTP puro (porta 587 + STARTTLS) | ✅ `smtp-relay.brevo.com` | ✅ `smtp.resend.com` |
| Domínio próprio de envio | ✅ SPF + DKIM pelo dashboard | ✅ SPF + DKIM pelo dashboard |
| SDK obrigatório | ✗ SMTP puro funciona | ✗ SMTP puro funciona |
| No mercado desde | 2012 | 2023 |

**Escolha: Brevo** — free tier 3× maior que o Resend e reputação de entrega mais consolidada. Ambos suportam SMTP puro sem SDK.

---

### Brevo — passo a passo

1. Crie conta em **brevo.com**
2. Vá em **Configurações → SMTP e API** → aba **SMTP** → crie uma chave SMTP
3. Vá em **Senders & IPs → Domains** → adicione e verifique seu domínio de envio (SPF + DKIM são gerados aqui)

Valores para o `.env`:

```env
EMAIL_SMTP=smtp-relay.brevo.com
EMAIL_PORTA=587
EMAIL_USER=seu-login@brevo.com     # login SMTP (Configurações → SMTP e API) — só autentica
EMAIL_PASS=xSMTP-KEY-BREVO         # chave gerada no passo 2
EMAIL_FROM=noreply@seu-dominio.com # remetente — precisa ser um endereço do domínio verificado no passo 3
```

> **Atenção:** `EMAIL_USER` (login SMTP) e `EMAIL_FROM` (remetente) são coisas diferentes no Brevo. Algumas contas geram um login SMTP no formato `xxxxx@smtp-brevo.com`, que autentica mas **não é um remetente válido** — usá-lo como `From` faz o Brevo aceitar a mensagem no protocolo e rejeitá-la depois, de forma assíncrona (o envio parece "OK" no app, mas o email nunca chega). Sempre configure `EMAIL_FROM` com um endereço do domínio verificado no passo 3.

---

### Resend — passo a passo

1. Crie conta em **resend.com**
2. Vá em **API Keys** → crie uma chave com permissão *Sending access*
3. Vá em **Domains** → adicione e verifique seu domínio (SPF + DKIM gerados aqui)

Valores para o `.env`:

```env
EMAIL_SMTP=smtp.resend.com
EMAIL_PORTA=587
EMAIL_USER=resend                  # literal "resend" — não é seu e-mail
EMAIL_PASS=re_xxxxxxxxxxxx         # API key gerada no passo 2
EMAIL_FROM=noreply@seu-dominio.com # remetente — precisa ser um endereço do domínio verificado no passo 3
```

---

### Autenticação de domínio: SPF, DKIM e DMARC

Sem esses registros DNS os emails quase certamente caem em spam, mesmo com provedor confiável.

#### SPF — autoriza o provedor a enviar pelo seu domínio

Adicione um registro **TXT** na raiz do domínio (`@`):

| Provedor | Valor do registro TXT |
|----------|-----------------------|
| Brevo | `v=spf1 include:spf.brevo.com ~all` |
| Resend | `v=spf1 include:spf.resend.com ~all` |

> **Atenção:** se já existe um registro SPF, **não crie um segundo** — apenas adicione o `include:` ao existente.
> Exemplo com Google Workspace também configurado: `v=spf1 include:spf.brevo.com include:_spf.google.com ~all`

#### DKIM — assinatura criptográfica dos emails

Cada provedor gera os registros DNS exatos na tela de verificação de domínio:

- **Brevo:** Senders & IPs → Domains → botão "Autenticar" → copie o registro TXT fornecido (geralmente em `mail._domainkey.seu-dominio.com`)
- **Resend:** Domains → seu domínio → copie os registros CNAME fornecidos

Cole os registros exatamente como mostrados no dashboard — seletor e valor incluídos.

#### DMARC — política de rejeição para emails não autenticados

Adicione um registro **TXT** em `_dmarc.seu-dominio.com`:

```
v=DMARC1; p=none; rua=mailto:postmaster@seu-dominio.com
```

Comece com `p=none` (só monitora, não rejeita). Após confirmar que SPF e DKIM passam em todos os envios, avance:

```
p=none   → monitoramento
p=quarantine → emails suspeitos vão para spam
p=reject     → emails sem autenticação são rejeitados
```

#### Verificar a configuração via terminal

```bash
# SPF
dig TXT seu-dominio.com +short

# DKIM (substitua mail pelo seletor que seu provedor usou)
dig TXT mail._domainkey.seu-dominio.com +short

# DMARC
dig TXT _dmarc.seu-dominio.com +short
```

Para verificação visual, busque por **MXToolbox SuperTool** e use os tipos "SPF Record Lookup", "DKIM Lookup" e "DMARC Lookup".


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

## Fila de Email Assíncrona (Redis + RQ)

Todo envio de email (verificação, reset de senha, convite de membro) passa por `enqueue_email()` (`backend/queue_utils.py`), que decide entre fila e envio direto:

- **`REDIS_URL` presente:** enfileira o job via RQ; o serviço `worker` (container `rsvp_worker`) processa a fila em background.
- **`REDIS_URL` ausente:** executa o envio de forma síncrona (conveniente em dev local sem Redis).
- **`REDIS_URL` presente mas Redis fora do ar:** loga o erro — **não** cai para envio síncrono em produção (evita travar a request esperando o SMTP).

```bash
# Ver logs do worker (deve mostrar "Performed" para cada job)
docker logs -f rsvp_worker

# Inspecionar quantos jobs estão na fila
docker exec rsvp_redis redis-cli llen rq:queue:default
```

---

## Rate Limiting

Via **Flask-Limiter**, com storage Redis (mesma instância da fila) e fallback automático para `memory://` se o Redis não estiver configurado:

| Rota | Limite |
|------|--------|
| `/login` (POST) | 10 por minuto |
| `/signup` (POST) | 5 por hora |
| `/forgot_password` (POST) | 5 por hora |
| `/invite/<token>` (GET) | 30 por minuto |
| `/invite/<token>` (POST) | 10 por minuto |

---

## Limites por Plano e Painel Super-Admin

Cada tenant tem um `plan` (`free`/`pro`/`business`) e um `status` (`trial`/`active`/`suspended`/`canceled`). Os limites de uso por plano ficam na tabela `plan_limits`:

| Plano | Eventos | Convidados | Membros |
|-------|---------|-----------|---------|
| `free` | 2 | 50 | 1 |
| `pro` | 10 | 500 | 5 |
| `business` | ilimitado | ilimitado | ilimitado |

Ao atingir o limite, a criação de novo evento/convidado/membro é bloqueada com uma mensagem clara — sem exceção silenciosa.

O painel `/superadmin` permite ao operador do SaaS listar todos os tenants e alterar plano/status (suspender, reativar). A conta em si é registrada no banco como `role='super_admin'` — não é mais uma comparação de email a cada request.

**Provisionar o super-admin (uma vez):**

```bash
docker exec rsvp_backend flask create-superadmin
```

- Lê `SUPERADMIN_EMAIL` do `.env`, cria a conta no tenant reservado `Comemore+ System` com senha temporária.
- Envia email de convite (mesmo mecanismo de "novo membro") se `EMAIL_SMTP`/`EMAIL_USER` estiverem configurados; senão imprime a senha temporária no terminal.
- Idempotente: rodar de novo com a mesma `SUPERADMIN_EMAIL` não duplica a conta.
- Ao logar, a conta é reconhecida como `super_admin` automaticamente e cai direto em `/superadmin` — fica impedida de acessar as rotas de tenant normal.

---

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
