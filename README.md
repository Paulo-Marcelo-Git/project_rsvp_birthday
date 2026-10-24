# Comemore+
Sistema de RSVP para convites — SaaS multi-tenant.

Aplicação web desenvolvida com **Flask**, **MySQL** e **Docker** que permite o envio de convites personalizados com link único e o acompanhamento das respostas dos convidados em tempo real.

---

## Funcionalidades

- Signup self-service: cada cliente cria sua própria conta e tenant
- Verificação de email obrigatória na criação de conta
- Convites com link único por convidado
- Página pública de confirmação (Sim / Não) com campo de observação
- Imagem/vídeo padrão **obrigatória por evento**; o convidado pode ter a própria mídia (precedência: convidado → evento → só texto)
- Botão de som no convite quando a mídia é vídeo
- Painel administrativo protegido por login
- Estatísticas em tempo real (confirmados / recusados / aguardando)
- Envio direto via WhatsApp com link pré-preenchido
- Exportação da lista de convidados para Excel (.xlsx)
- Textos do convite configuráveis pelo painel
- Gerenciamento de membros: cada evento tem um responsável (member) que gerencia os convidados, a imagem, os textos e o tema dos seus eventos
- Reset de senha self-service por email (link com TTL de 1h)
- Backup automático diário (banco e uploads) com retenção configurável
- Múltiplos eventos por tenant, cada um com tema visual (padrão / menina / menino)
- Edição e exclusão de convidados já cadastrados
- Envio de email assíncrono via fila Redis + RQ (fallback síncrono em dev sem Redis)
- Rate limiting (login, signup, reset de senha, confirmação de convite) contra abuso
- Termos de uso e política de privacidade (LGPD), com aceite obrigatório no cadastro
- Limites de uso por plano (free / pro / business): eventos, convidados (por evento) e membros
- Trial de 14 dias no plano Free, contado a partir do 1º login
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
# EMAIL_FROM (opcional): remetente validado no provedor; fallback = EMAIL_USER.
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
# Este email NÃO pode já existir como usuário comum no banco:
# `flask create-superadmin` recusa (não promove automaticamente um usuário existente).
# SUPERADMIN_EMAIL=admin@seudominio.com

# Opcionais
# EMAIL_FROM=noreply@seudominio.com  # remetente validado no provedor; fallback = EMAIL_USER
# TZ_OFFSET_HOURS=-3                 # default -3 (BRT)
# LOG_FILE=logs/app.log              # default; nome-base → logs/app-AAAA-MM-DD.log (1 arquivo/dia, UTC)
# LOG_RETENTION_DAYS=5               # default; dias de log mantidos (purge diário no container backup)
# UPLOAD_FOLDER=/app/uploads         # default (volume uploads_data)
# DEBUGPY_ENABLED=true               # SOMENTE DEV — troca gunicorn por flask run + debugpy (porta 5678)
```

> No exemplo acima (Gmail, dev local), `EMAIL_PASS` deve ser um **App Password** do Google: [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Em produção, `EMAIL_PASS` é a chave SMTP do Brevo/Resend (ver "Configuração de Email Transacional").

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
| `tenant_admin` | Acesso total ao tenant. Único que cria eventos, define o responsável de cada evento e gerencia membros |
| `member` | Gerencia os eventos dos quais é responsável (convidados, imagem, textos, tema). Não cria eventos nem define responsável |

O primeiro `tenant_admin` é criado pelo signup self-service (`/signup`).
Novos membros são criados pelo painel (`/admin/usuarios`); recebem email de convite com link para definir a senha (ou senha temporária em dev sem SMTP).

---

## Rotas

| Rota | Acesso | Descrição |
|------|--------|-----------|
| `/signup` | Público | Criar conta (tenant + tenant_admin, sem evento; o primeiro evento é criado em `/admin/primeiro-evento`) — rate limit 5/hora |
| `/login` | Público | Login — rate limit 10/min |
| `/logout` | Login | Encerra a sessão |
| `/forgot_password` | Público | Solicitar reset de senha — rate limit 5/hora |
| `/reset_password/<token>` | Público | Redefinir senha via link de email |
| `/resend-verification` | Público | Reenviar link de verificação de email |
| `/verify-email/<token>` | Público | Confirma o email a partir do link (TTL 24h) |
| `/termos` | Público | Termos de uso (LGPD) |
| `/privacidade` | Público | Política de privacidade (LGPD) |
| `/invite/<token>` | Público | Página de confirmação do convidado — rate limit 30/min (GET) / 10/min (POST) |
| `/uploads/<filename>` | Tenant autenticado ou convidado c/ session | Serve arquivo de upload com validação de posse (convidado: a própria mídia **ou** a do seu evento; usuário logado: mídia de convidados e eventos do próprio tenant) |
| `/admin/respostas` | Login | Lista de respostas com paginação e busca |
| `/admin/exportar_xlsx` | Login | Download da lista em Excel |
| `/admin/convidados/add` | Login | Adicionar convidado |
| `/admin/convidados/<id>/edit` | Login | Editar convidado |
| `/admin/convidados/<id>/delete` | Login | Excluir convidado |
| `/admin/textos` | tenant_admin ou member responsável pelo evento | Editar textos do convite |
| `/admin/set_tema` | tenant_admin ou member responsável pelo evento | Define o tema visual do evento (padrão/menina/menino) |
| `/admin/eventos` | Login | Lista os eventos do tenant |
| `/admin/eventos/criar` | tenant_admin | Cria um novo evento no tenant (imagem obrigatória; respeita `max_events`) |
| `/admin/primeiro-evento` | tenant_admin | GET/POST — cria o primeiro evento do tenant recém-cadastrado |
| `/admin/eventos/<id>/imagem` | Quem gerencia o evento (tenant_admin ou member responsável) | POST — envia/troca a imagem padrão do evento |
| `/admin/eventos/<id>/responsavel` | tenant_admin | POST — define o member responsável pelo evento |
| `/apidocs` | tenant_admin | Documentação Swagger da API |
| `/admin/usuarios` | tenant_admin | Gerenciar membros do tenant |
| `/admin/usuarios/add` | tenant_admin | Convida um novo membro (senha temporária por email) |
| `/admin/usuarios/<id>/edit` | tenant_admin | Edita dados de um membro |
| `/admin/usuarios/<id>/reset_senha` | tenant_admin | Reenvia senha temporária a um membro |
| `/admin/usuarios/<id>/delete` | tenant_admin | Remove um membro do tenant |
| `/change_password` | Login | Troca de senha (obrigatória para não-tenant_admin com `must_change_password`) |
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
| `tenants` | Conta do cliente. Raiz da árvore de FK (apagar cascateia tudo = LGPD). Tem `plan` (free/pro/business) e `status` (trial/active/suspended/canceled), geridos via `/superadmin`; `trial_ends_at` (NULL até o 1º login) e `suspended_reason` (trial_expired/manual). |
| `users` | Usuários com `tenant_id` e `role` (`tenant_admin`/`member`/`super_admin`). Email UNIQUE global. `accepted_terms_at` registra o aceite dos termos no signup. |
| `events` | N eventos por tenant, com textos do convite e `theme` (padrão/menina/menino) por evento; `media_url` (imagem padrão, obrigatória na criação) e `owner_user_id` (member responsável). |
| `invitees` | Convidados com `tenant_id` desnormalizado e `token` UNIQUE global. |
| `password_reset_tokens` | Tokens de reset com TTL de 1h e flag `used`. |
| `email_verification_tokens` | Tokens de verificação de email com TTL de 24h e flag `used`. |
| `plan_limits` | Limites por plano (PK `plan`): `max_events`, `max_invitees` (por evento), `max_members` (`NULL` = ilimitado). Seed: free(2, 50, 1), pro(10, 500, 5), business(ilimitado). |

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
[2026-06-24 05:00:06] Iniciando backup dos uploads (/uploads)...
[2026-06-24 05:00:07] Backup de uploads salvo: comemore_uploads_20260624_050006.tar.gz (1.2M)
[2026-06-24 05:00:07] Retenção: 0 arquivo(s) removido(s) (>7 dias)
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

### Backup externo (B2)

Além do backup local (7 dias, volume `backup_data`), o container `backup` envia uma cópia **criptografada** (`rclone crypt`: conteúdo e nomes de arquivo) para o Backblaze B2, logo após o backup local (**02:05 BRT / 05:05 UTC**):

| O quê | Destino no bucket | Observação |
|---|---|---|
| Dumps SQL válidos (`comemore_*.sql.gz`) | `comemore/db/` | envia também os dias que falharam antes |
| Uploads | `comemore/uploads/` | `rclone sync` incremental (não um tar por dia) |
| `.env` de produção | `comemore/env/env_AAAAMMDD` | montado somente leitura em `/run/comemore/env` |

- **RPO:** 1 dia. **Retenção externa:** 30 dias, garantida por **Object Lock (30 dias)** no bucket + regras de ciclo de vida por prefixo: `comemore/db/` e `comemore/env/` — esconder após 30 dias e apagar 1 dia depois; `comemore/uploads/` — apagar 30 dias depois de escondido.
- **Chave de aplicação do B2:** restrita ao bucket e **sem `deleteFiles`**.
- **Alertas (Healthchecks.io):** dois checks, `backup-local` e `backup-externo`. Sem ping no prazo ou `/fail` = alerta por e-mail/Telegram.
- **Sem B2 configurado (dev):** a cópia externa é pulada com aviso. Configuração parcial em produção falha com saída ≠ 0 e ping `/fail`.

Variáveis (`.env`, ver `.env.example`; valores só no `.env`/gerenciador de senhas, nunca no repo): `B2_ACCOUNT_ID`, `B2_APP_KEY`, `B2_BUCKET`, `CRYPT_PASSWORD`, `CRYPT_SALT`, `HC_BACKUP_URL`, `HC_OFFSITE_URL`.

> **Depois de editar o `.env`, recrie o container:** `docker compose up -d backup`. O `.env` é montado como arquivo único (um editor que substitui o arquivo deixa o container vendo o antigo) e `/etc/backup.env` só é gravado na partida do container. Um `restart` não basta se o arquivo foi substituído.

Backup manual completo (local + externo): `docker exec rsvp_backup sh -c '. /etc/backup.env; /backup.sh'`.

Conferir o que está no B2 (só nomes e tamanhos):

```bash
docker exec rsvp_backup sh -c '. /etc/backup.env; . /rclone-env.sh; rclone_env_export; rclone ls b2crypt:db'
```

Comparar contagem de linhas por tabela (produção × restore; só números):

```bash
docker exec rsvp_backup sh -c '. /etc/backup.env; sh /count-rows.sh rsvp_db'
docker exec rsvp_backup sh -c '. /etc/backup.env; sh /count-rows.sh rsvp_restore_test'
```

### Restore do zero a partir do B2

> **ATENÇÃO: sem `CRYPT_PASSWORD` e `CRYPT_SALT` o backup externo é ilegível** (nem o B2 nem ninguém recupera). Guarde os dois, junto com `B2_ACCOUNT_ID`, `B2_APP_KEY` e `B2_BUCKET`, no gerenciador de senhas — **fora da VPS**.

Partindo de uma VPS nova, só com o repositório, a conta B2 e o gerenciador de senhas:

1. Clonar o repositório e instalar o **rclone v1.75.1** conferindo o checksum (SHA-256 `982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab`, do `SHA256SUMS` oficial):
   ```bash
   curl -fsSLO https://github.com/rclone/rclone/releases/download/v1.75.1/rclone-v1.75.1-linux-amd64.zip
   echo "982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab  rclone-v1.75.1-linux-amd64.zip" | sha256sum -c -
   unzip -j rclone-v1.75.1-linux-amd64.zip '*/rclone' -d /usr/local/bin && chmod 755 /usr/local/bin/rclone
   ```
2. Exportar as 5 variáveis na sessão do shell (digitadas por você, a partir do gerenciador de senhas; evite deixá-las no histórico, ex.: `read -rs B2_APP_KEY; export B2_APP_KEY`): `B2_ACCOUNT_ID`, `B2_APP_KEY`, `B2_BUCKET`, `CRYPT_PASSWORD`, `CRYPT_SALT`.
3. Baixar (sem container; o script usa o `rclone-env.sh` ao lado dele):
   ```bash
   sh backup/restore-offsite.sh /root/restore            # dump mais recente
   sh backup/restore-offsite.sh /root/restore 20261022   # ou de uma data
   ```
   Cria em `DESTINO/`: `comemore_<data>_*.sql.gz`, `env_<data>` (permissão `0600`, conteúdo nunca impresso) e `uploads/`. No container: `docker exec rsvp_backup sh /restore-offsite.sh /tmp/restore [AAAAMMDD]` (com `. /etc/backup.env`).
4. Restaurar o `.env` (`cp /root/restore/env_<data> .env`), subir só o banco (`docker compose up -d db`) e aplicar o dump com `restore.sh` (ver "Restore manual"); restaurar os uploads com `restore-uploads.sh` (ou copiando `uploads/` para o volume `uploads_data`).
5. Conferir com `count-rows.sh`, subir o resto (`docker compose up -d`) e testar login e um convite.
6. Apagar o diretório baixado (`rm -rf /root/restore`): ele contém o `.env` e dados de convidados.

### Uploads (imagens e vídeos dos convites)

O backup diário também gera `comemore_uploads_YYYYMMDD_HHMMSS.tar.gz` em `/backups`, com a mesma retenção (`BACKUP_RETENTION_DAYS`).

Testar um restore (em diretório temporário, sem tocar produção):

    docker exec rsvp_backup sh /restore-uploads.sh /backups/comemore_uploads_XYZ.tar.gz

Restaurar **em produção** (sobrescreve o volume — faça um backup manual antes):

    docker compose stop backend worker
    docker run --rm -v project_rsvp_birthday_uploads_data:/uploads -v project_rsvp_birthday_backup_data:/backups:ro \
      alpine sh -c 'tar -xzf /backups/comemore_uploads_XYZ.tar.gz -C /uploads'
    docker compose start backend worker

(Confirme os nomes reais dos volumes com `docker volume ls | grep rsvp`.)

---

## Logs

- **Conteúdo (LGPD):** os logs identificam por ID (`user_id`, `tenant_id`, `event_id`, `invitee_id`). Nunca nome, e-mail, username, telefone, observação ou token. E-mail só aparece mascarado (`a***@dominio.com`) e exceções só pelo tipo (ex.: `IntegrityError(mysql=1062)`). `backend/tests/test_log_sem_pii.py` garante a regra.
- **Arquivo do app:** `logs/app-AAAA-MM-DD.log` (um por dia, data UTC; `LOG_FILE` define o nome-base). O container `backup` roda `purge-logs.sh` às 02:20 (horário do container) e apaga os arquivos com mais de `LOG_RETENTION_DAYS` dias (default 5). A retenção só vale com o `LOG_FILE` padrão (`logs/app.log`): o purge apaga apenas `app-AAAA-MM-DD.log` no `./logs` montado no backup — outro nome-base ou diretório acumula arquivos sem limite.
- **Access log do gunicorn** (`docker logs rsvp_backend`): configurado em `backend/gunicorn.conf.py`; tokens aparecem como `/invite/***`, `/verify-email/***`, `/reset_password/***`.
- **Worker** (`docker logs rsvp_worker`): mostra só o nome da função do job (`default: send_reset_email (<id>)`), nunca os argumentos. Jobs que falharam ficam no Redis por no máximo 5 dias.
- **Logs do Docker** (backend e worker): `json-file` com `max-size: 10m` e `max-file: 3`.

```bash
ls -l logs/                                            # arquivos diários
docker exec rsvp_backup /purge-logs.sh                 # limpeza manual
docker exec rsvp_backup sh -c 'tail -n 5 /var/log/purge-logs.log'
```

---

## Uploads de Mídia

Os arquivos enviados (imagem/vídeo padrão de cada evento e mídia por convidado) são armazenados no volume Docker nomeado `uploads_data`, montado em `/app/uploads` no container.

### Comportamento por ambiente

| Ambiente | Onde ficam os arquivos |
|----------|----------------------|
| Produção / Docker | Volume nomeado `uploads_data` — persiste entre rebuilds |
| Dev local (sem Docker) | defina `UPLOAD_FOLDER` (default `/app/uploads`) |

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

### Regras de upload

- Extensões permitidas: `jpg`, `jpeg`, `png`, `mp4`; máximo de 50MB.
- O conteúdo é validado por magic bytes (a extensão sozinha não basta); o arquivo é salvo com nome UUID.
- Todas as respostas levam `X-Content-Type-Options: nosniff`.
- Arquivo acima do limite: o navegador bloqueia antes do envio (evita a página 413 crua do nginx) e, se chegar ao app, o 413 vira mensagem de erro com redirecionamento.

### Limpeza de arquivos órfãos

Arquivos em `UPLOAD_FOLDER` sem referência no banco podem ser listados (dry-run por padrão; ignora arquivos com menos de 60 minutos):

```bash
docker exec rsvp_backend flask cleanup-orphan-uploads
```

Use `--apply` para remover de fato — só depois de revisar a lista e fazer um backup.

### Acesso protegido

A rota `/uploads/<filename>` não é pública:
- **Usuário logado:** o arquivo deve pertencer ao tenant do usuário autenticado
- **Convidado sem login:** session do Flask valida o token de convite contra a mídia do próprio convidado **ou** a imagem padrão do seu evento (sem expor o token em query string)
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

| Plano | Eventos | Convidados (por evento) | Membros |
|-------|---------|-----------|---------|
| `free` | 2 | 50 | 1 |
| `pro` | 10 | 500 | 5 |
| `business` | ilimitado | ilimitado | ilimitado |

Ao atingir o limite, a criação de novo evento/convidado/membro é bloqueada com uma mensagem clara — sem exceção silenciosa.

### Trial

- Tenants no plano Free começam em `trial`: o prazo de 14 dias é contado a partir do **primeiro login** (`trial_ends_at` fica NULL até lá).
- Quando faltam 3 dias ou menos, o login exibe um aviso de expiração.
- Ao expirar, o tenant é suspenso automaticamente no próximo login (`suspended_reason=trial_expired`) e o login é bloqueado.
- Upgrade para `pro`/`business` em `/superadmin` reativa automaticamente apenas suspensão por trial expirado. Suspensão manual exige "reativar" no painel, mesmo após o upgrade.

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

## Testes

Testes unitários (não precisam de MySQL; o `pytest.ini` deseleciona os marcados `integration` por default):

```bash
pytest
```

### Testes de integração

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
