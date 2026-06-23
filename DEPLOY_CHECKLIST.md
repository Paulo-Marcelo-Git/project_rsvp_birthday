# Checklist de Primeiro Deploy — Comemore+ (VPS Hostinger)

> **Contexto:** Ubuntu VPS Hostinger · usuário `pcs` · projeto em `/home/pcs/project_rsvp_birthday`
> Stack: Docker Compose · nginx → gunicorn:8000 (porta 3000 do host) · MySQL 8 · Redis 7 · RQ worker · backup cron 02h BRT

---

## 1. Pré-requisitos na VPS

Conecte-se à VPS e execute como `pcs`:

```bash
ssh pcs@SEU_IP_VPS
```

- [ ] **Docker Engine**

  ```bash
  # Instalar Docker (Ubuntu)
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker pcs
  # Faça logout e login novamente para o grupo valer
  docker --version          # deve imprimir Docker version 24+
  ```

- [ ] **Docker Compose v2** (plugin embutido no Docker Engine 24+)

  ```bash
  docker compose version    # deve imprimir Docker Compose version v2+
  ```

- [ ] **Git**

  ```bash
  sudo apt-get update && sudo apt-get install -y git
  git --version
  ```

- [ ] **zsh + Oh My Zsh** (opcional, mas é o shell padrão do usuário)

  ```bash
  sudo apt-get install -y zsh
  sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
  chsh -s $(which zsh) pcs   # define zsh como shell padrão
  ```

- [ ] **tmux** (manter sessão viva durante o primeiro deploy)

  ```bash
  sudo apt-get install -y tmux
  tmux new -s deploy         # abra uma sessão — tudo a seguir roda aqui dentro
  ```

- [ ] **nginx + Certbot** (reverse proxy + HTTPS)

  ```bash
  sudo apt-get install -y nginx certbot python3-certbot-nginx
  ```

---

## 2. Clone do repositório e estrutura de diretórios

```bash
cd /home/pcs
git clone https://github.com/Paulo-Marcelo-Git/project_rsvp_birthday.git
cd project_rsvp_birthday
```

- [ ] Criar diretório `logs/` (montado como volume pelo backend):

  ```bash
  mkdir -p logs
  ```

- [ ] Verificar estrutura mínima:

  ```bash
  ls -la
  # Deve conter: backend/ backup/ docker-compose.yml .env.example CLAUDE.md
  ```

---

## 3. Criar o `.env` de produção

**Nunca comite o `.env`. Nunca copie o `.env.example` diretamente — ele tem Gmail/dev.**

```bash
nano /home/pcs/project_rsvp_birthday/.env
```

Cole o conteúdo abaixo, substituindo os valores marcados com `← PREENCHER`:

```env
# ── Banco de dados ────────────────────────────────────────────────────────────
DB_NAME=rsvp_db
DB_USER=root
DB_PASSWORD=← gerar com: openssl rand -base64 32
DB_HOST=db

# ── Flask ─────────────────────────────────────────────────────────────────────
SECRET_KEY=← gerar com: openssl rand -base64 32

# ── Opcionais ─────────────────────────────────────────────────────────────────
TZ_OFFSET_HOURS=-3
LOG_FILE=logs/app.log
UPLOAD_FOLDER=/app/uploads

# ── Email transacional — Brevo (recomendado: 300/dia grátis) ─────────────────
EMAIL_SMTP=smtp-relay.brevo.com
EMAIL_PORTA=587
EMAIL_USER=← seu login de cadastro na Brevo (ex: admin@seudominio.com)
EMAIL_PASS=← chave SMTP gerada em Brevo > Configurações > SMTP e API

# ── URL base (links de email) ─────────────────────────────────────────────────
APP_BASE_URL=https://← seudominio.com.br

# ── SKIP_EMAIL_VERIFICATION: NÃO definir em produção (ausência = verificação obrigatória)

# ── Redis / RQ ────────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── Backup ────────────────────────────────────────────────────────────────────
BACKUP_RETENTION_DAYS=7

# ── Super-admin ───────────────────────────────────────────────────────────────
# ⚠ Este email NÃO deve existir como conta de tenant no banco.
# Use um email dedicado nunca cadastrado via signup.
SUPERADMIN_EMAIL=← email-admin-dedicado@seudominio.com
```

- [ ] Gerar `DB_PASSWORD`:

  ```bash
  openssl rand -base64 32
  ```

- [ ] Gerar `SECRET_KEY`:

  ```bash
  openssl rand -base64 32
  ```

- [ ] Confirmar que `SKIP_EMAIL_VERIFICATION` **não aparece** no arquivo:

  ```bash
  grep SKIP_EMAIL .env   # deve retornar vazio
  ```

- [ ] Confirmar que `EMAIL_SMTP` é Brevo e não Gmail:

  ```bash
  grep EMAIL_SMTP .env   # deve mostrar smtp-relay.brevo.com
  ```

---

## 4. Configurar nginx (reverse proxy)

- [ ] Criar config de site:

  ```bash
  sudo nano /etc/nginx/sites-available/comemore
  ```

  Conteúdo:

  ```nginx
  server {
      listen 80;
      server_name seudominio.com.br www.seudominio.com.br;

      client_max_body_size 55M;   # uploads até 50 MB + margem

      location / {
          proxy_pass         http://127.0.0.1:3000;
          proxy_set_header   Host $host;
          proxy_set_header   X-Real-IP $remote_addr;
          proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
          proxy_set_header   X-Forwarded-Proto $scheme;
          proxy_read_timeout 60s;
      }
  }
  ```

- [ ] Habilitar e testar:

  ```bash
  sudo ln -s /etc/nginx/sites-available/comemore /etc/nginx/sites-enabled/
  sudo nginx -t          # deve retornar "syntax is ok"
  sudo systemctl reload nginx
  ```

- [ ] Emitir certificado HTTPS (Let's Encrypt):

  ```bash
  sudo certbot --nginx -d seudominio.com.br -d www.seudominio.com.br
  # Certbot reescreve a config para redirecionar 80 → 443 automaticamente
  ```

---

## 5. Primeiro deploy

- [ ] Build e subida dos containers (dentro de tmux):

  ```bash
  cd /home/pcs/project_rsvp_birthday
  docker compose up --build -d
  ```

  O `entrypoint.sh` do backend aguarda o MySQL, aplica `alembic upgrade head` e só então inicia o gunicorn. A primeira subida demora ~2 min.

- [ ] Acompanhar logs do backend para confirmar migrations e boot:

  ```bash
  docker logs -f rsvp_backend
  # Esperar:
  # [entrypoint] Aguardando MySQL...
  # [entrypoint] Aplicando migrations Alembic...
  # [entrypoint] Iniciando gunicorn...
  # [INFO] Booting worker with pid: ...
  ```

---

## 6. Validação dos 5 containers

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

- [ ] `rsvp_mysql` — Status: `Up X minutes (healthy)`
- [ ] `rsvp_backend` — Status: `Up X minutes` · porta `127.0.0.1:3000->8000/tcp`
- [ ] `rsvp_worker` — Status: `Up X minutes` (sem porta exposta)
- [ ] `rsvp_redis` — Status: `Up X minutes` (sem porta exposta)
- [ ] `rsvp_backup` — Status: `Up X minutes` (sem porta exposta)

- [ ] Worker ouvindo a fila:

  ```bash
  docker logs rsvp_worker | tail -5
  # Deve mostrar: Worker rsvp_worker: started, version X.Y.Z
  #               Listening on queues: default
  ```

- [ ] Migrations aplicadas:

  ```bash
  docker exec rsvp_backend alembic current
  # Deve mostrar: XXXX (head)  ← revision 0004
  ```

- [ ] Backup cron ativo (cron dispara 02h BRT / 05h UTC):

  ```bash
  docker exec rsvp_backup crontab -l
  # Deve mostrar: 05 2 * * * /backup.sh >> /var/log/backup.log 2>&1
  ```

---

## 7. Smoke test mínimo de produção

Execute cada passo no browser e verifique que nenhum erro 500 aparece.

- [ ] **Signup:** `https://seudominio.com.br/signup`
  - Preencha nome, email, senha → clique "Criar conta"
  - Esperado: "Verifique seu email" (não logar ainda)

- [ ] **Email chega (Brevo):** abra o email de verificação
  - Esperado: link `https://seudominio.com.br/verify-email/<token>`
  - Se não chegar em 2 min: `docker logs rsvp_worker | grep -i email` para ver se a tarefa foi enfileirada e executada

- [ ] **Verificar email:** clique no link do email
  - Esperado: redirect para `/login` com flash "Email verificado"

- [ ] **Login:** `https://seudominio.com.br/login`
  - Esperado: redirect para `/admin/respostas`

- [ ] **Criar evento / editar textos:** clique em "Textos" no painel
  - Esperado: modal abre, salva sem erro

- [ ] **Adicionar convidado:** clique em "+ Convidado"
  - Preencha nome → "Adicionar"
  - Esperado: convidado aparece na lista

- [ ] **Página do convidado:** clique no token do convidado ou acesse `/invite/<token>`
  - Esperado: página do convite carrega com os textos corretos

- [ ] **Superadmin:** `https://seudominio.com.br/superadmin`
  - Logar com a conta cujo email == `SUPERADMIN_EMAIL` (criar uma conta separada se necessário)
  - Esperado: lista de tenants com o tenant recém-criado

---

## 8. Configurar CI/CD — GitHub Actions

O workflow `.github/workflows/deploy.yml` já está pronto. Só precisa dos segredos no repositório GitHub.

**Caminho:** GitHub → seu repositório → Settings → Secrets and variables → Actions → New repository secret

- [ ] `VPS_HOST` — IP público da VPS (ex: `123.45.67.89`)
- [ ] `VPS_USER` — `pcs`
- [ ] `VPS_PORT` — porta SSH (padrão `22`; confirme em `/etc/ssh/sshd_config`)
- [ ] `VPS_PATH` — `/home/pcs/project_rsvp_birthday`
- [ ] `VPS_SSH_KEY` — chave privada SSH que autentica como `pcs` na VPS

  **Gerar par de chaves dedicado para o CI (não use sua chave pessoal):**

  ```bash
  # Na sua máquina local:
  ssh-keygen -t ed25519 -C "github-actions-comemore" -f ~/.ssh/comemore_ci
  # Sem passphrase (Actions não suporta interativo)

  # Copiar chave pública para a VPS:
  ssh-copy-id -i ~/.ssh/comemore_ci.pub pcs@SEU_IP_VPS

  # O conteúdo de comemore_ci (privada) vai no segredo VPS_SSH_KEY:
  cat ~/.ssh/comemore_ci
  ```

- [ ] Validar CI/CD: faça um commit qualquer em `main` e acompanhe em Actions
  - Esperado: deploy termina em ~60s com "✓ Deploy concluído."

---

## 9. Monitoramento mínimo

- [ ] **Verificar logs do worker** (email assíncrono):

  ```bash
  docker logs rsvp_worker --since 24h | grep -E "Performed|Failed|Error"
  ```

- [ ] **Verificar backup diário** (após 02h BRT do dia seguinte):

  ```bash
  # Listar backups no volume:
  docker exec rsvp_backup ls -lh /backups/
  # Deve mostrar: comemore_YYYYMMDD_HHMMSS.sql.gz

  # Ver log do último backup:
  docker exec rsvp_backup cat /var/log/backup.log
  ```

- [ ] **Forçar backup agora** (para testar antes das 02h):

  ```bash
  docker exec rsvp_backup sh /backup.sh
  docker exec rsvp_backup ls -lh /backups/
  ```

- [ ] **Restore de teste** (em banco separado — não toca o rsvp_db):

  ```bash
  # Substitua o nome do arquivo pelo gerado acima:
  docker exec rsvp_backup sh /restore.sh /backups/comemore_YYYYMMDD_HHMMSS.sql.gz rsvp_restore_test
  # Esperado: "Restore concluído." + lista de tabelas
  ```

- [ ] **Health check rápido**:

  ```bash
  docker ps --filter "health=unhealthy"   # deve retornar vazio
  curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:3000/login
  # Deve retornar: 200
  ```

- [ ] **Renovação automática do certificado SSL** (Certbot agenda via systemd):

  ```bash
  sudo systemctl status certbot.timer     # deve estar active
  sudo certbot renew --dry-run            # simula renovação
  ```

---

## 10. Referência rápida — comandos do dia a dia

```bash
# Ver status de todos os containers
docker ps

# Restart de um container específico
docker restart rsvp_backend

# Ver logs em tempo real
docker logs -f rsvp_backend
docker logs -f rsvp_worker

# Inspecionar fila Redis
docker exec rsvp_redis redis-cli llen rq:queue:default

# Entrar no MySQL
docker exec -it rsvp_mysql mysql -uroot -p$DB_PASSWORD rsvp_db

# Parar tudo (não apaga volumes)
docker compose down

# ⚠ Apagar volumes (DESTRÓI dados — só em reset total):
# docker compose down -v
```
