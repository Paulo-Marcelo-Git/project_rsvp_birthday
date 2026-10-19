# Checklist de Deploy em Produção — Comemore+ (VPS Hostinger)

> **Contexto:** Ubuntu VPS Hostinger · usuário `pcs` · projeto em `/srv/projects/project_rsvp_birthday`
> **Stack:** Docker Compose · nginx → gunicorn:8000 (porta 3000 do host, só em 127.0.0.1) · MySQL 8 · Redis 7 · RQ worker · backup cron 02h BRT
> **Regra de ouro:** só vai para produção quando **todos** os itens `[BLOQUEADOR]` estiverem marcados (ver tabela Go/No-Go na seção 18).

---

## 0. Como usar este checklist

### Legenda

| Marcador | Significado |
|---|---|
| `[BLOQUEADOR]` | Sem isso, **não** vai para produção. |
| `[RECOMENDADO]` | Importante, mas pode entrar logo após o go-live. |
| `[🎭 PLAYWRIGHT]` | Validação de front-end executada pelo Claude Code via **Playwright MCP**. |
| `[👤 MANUAL]` | Precisa de uma pessoa (login, e-mail, celular físico). |
| `[⚙️ CÓDIGO]` | Pode exigir mudança no código/compose. Verificar antes se já existe. |

### Variáveis usadas nos comandos

```bash
export DOMINIO=seudominio.com.br          # ← PREENCHER (sem https://)
export BASE_URL=https://$DOMINIO
```

### Regras para as validações com Playwright

1. **Todo teste de front-end (telas, formulários, fluxo do convidado, isolamento entre tenants, páginas de erro, mobile) é feito pelo Claude Code com o Playwright MCP**, seguindo a seção 11.
2. **O agente nunca digita senhas.** Quando um passo exigir login, o agente abre a tela, **pausa** e pede para você logar manualmente na janela do navegador aberta pelo Playwright. Isso mantém senhas de produção fora do contexto do modelo, dos logs e do histórico.
   - Se o Playwright MCP estiver rodando *headless* (sem janela visível, comum no WSL sem WSLg), habilite o modo com janela antes de começar. Sem janela, os passos com login precisam ser feitos por você em um navegador comum.
3. **Use apenas contas e dados de teste**: dois tenants dedicados (`teste-a@…` e `teste-b@…`), criados para isso e removidos no fim (seção 11.10). Nunca rode os testes sobre eventos reais de clientes.
4. **Evidências (screenshots) ficam fora do git** em `.playwright-mcp/` (adicionar ao `.gitignore`). Screenshots de admin podem conter dados pessoais (LGPD).
5. Os testes de backend que não envolvem tela (headers, rate limit, debug) usam `curl` (seção 10) por serem mais precisos que o navegador.

---

## 1. Pré-deploy — gates no código (máquina local)

Tudo aqui é verificado **antes** de subir qualquer coisa para a VPS.

### 1.1 Testes e qualidade

- [ ] `[BLOQUEADOR]` Suíte de testes passando localmente:

  ```bash
  docker compose run --rm backend pytest -q
  ```

- [ ] `[BLOQUEADOR]` `[⚙️ CÓDIGO]` Existe teste automatizado do **fluxo crítico**: convidado abre `/invite/<token>` → confirma presença → a resposta aparece em `/admin/respostas` do tenant correto.
- [ ] `[BLOQUEADOR]` `[⚙️ CÓDIGO]` Existem testes automatizados de **isolamento entre tenants**: tenant A não lê, edita nem apaga convidados, eventos, respostas ou uploads do tenant B (esperado: 403 ou 404 em toda rota).
- [ ] `[BLOQUEADOR]` `[⚙️ CÓDIGO]` Existe teste de que **toda rota `/admin/*` e `/superadmin/*` sem sessão** redireciona para `/login` ou retorna 401/403. Ideal: o teste percorre `app.url_map` automaticamente, para que uma rota nova esquecida falhe o teste.

### 1.2 Segredos

- [ ] `[BLOQUEADOR]` Nenhum segredo no histórico do git. O `--redact` impede que o valor encontrado seja impresso no terminal:

  ```bash
  docker run --rm -v "$PWD:/repo" ghcr.io/gitleaks/gitleaks:latest detect --source /repo --redact -v
  # Esperado: "no leaks found"
  ```

  Se encontrar algo: **revogar e rotacionar a credencial primeiro**; reescrever o histórico vem depois e não substitui a rotação.

- [ ] `[BLOQUEADOR]` `.dockerignore` contém `.env`, `.env.*` (exceto `.env.example`), `logs/`, `backup/*.sql*`, `.git`:

  ```bash
  grep -nE '^\.env|logs|\.git' .dockerignore
  ```

- [ ] `[BLOQUEADOR]` `.env` está no `.gitignore` e não está rastreado:

  ```bash
  git ls-files | grep -E '(^|/)\.env$'   # deve retornar vazio
  ```

### 1.3 Configuração de segurança do Flask `[⚙️ CÓDIGO]`

- [ ] `[BLOQUEADOR]` Debug desligado em produção: `app.debug` é `False` e `FLASK_DEBUG` não é definido no ambiente de produção.
- [ ] `[BLOQUEADOR]` App atrás de proxy reconhece HTTPS (sem isso, redirects e cookies podem sair como HTTP):

  ```python
  from werkzeug.middleware.proxy_fix import ProxyFix
  app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
  ```

- [ ] `[BLOQUEADOR]` Cookies de sessão seguros em produção:

  ```python
  SESSION_COOKIE_SECURE = True
  SESSION_COOKIE_HTTPONLY = True
  SESSION_COOKIE_SAMESITE = "Lax"
  # Se usar Flask-Login:
  REMEMBER_COOKIE_SECURE = True
  REMEMBER_COOKIE_HTTPONLY = True
  ```

- [ ] `[BLOQUEADOR]` Proteção CSRF ativa em todos os formulários `POST` (ex.: Flask-WTF `CSRFProtect`).
- [ ] `[BLOQUEADOR]` Rate limit na aplicação (ex.: Flask-Limiter com storage no Redis que já existe) em: login, signup, reenvio de e-mail de verificação, recuperação de senha (se existir) e endpoint público de RSVP. O nginx (seção 7) é a segunda camada.
- [ ] `[BLOQUEADOR]` Toda consulta de dados do admin filtra pelo tenant da **sessão**, nunca por um ID de tenant vindo da URL, formulário ou cookie.
- [ ] `[BLOQUEADOR]` Uploads validados no backend: extensão **e** tipo real do arquivo (magic bytes, ex.: via Pillow), apenas imagens raster (JPEG, PNG, WebP). **SVG e HTML recusados**, porque permitem XSS armazenado. Nome do arquivo gerado pelo servidor (UUID), nunca o nome enviado pelo usuário.
- [ ] `[RECOMENDADO]` Senhas com hash forte (bcrypt/argon2 ou `werkzeug.security` com scrypt/pbkdf2), nunca reversíveis.

### 1.4 Logs sem dados pessoais `[⚙️ CÓDIGO]`

- [ ] `[BLOQUEADOR]` A aplicação não loga e-mail, telefone, senha, token de convite, token de verificação nem `SECRET_KEY`. Verificação após rodar os testes localmente (mostra só a **contagem**, sem imprimir os dados):

  ```bash
  grep -cE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' logs/app.log   # e-mails → esperado 0
  grep -cE '/invite/[A-Za-z0-9_-]{8,}|verify-email/[A-Za-z0-9_.-]{8,}' logs/app.log  # tokens → esperado 0
  ```

  Atenção: o access log do gunicorn/nginx registra URLs. Se o token de convite está na URL (`/invite/<token>`), ele vai aparecer no access log. Aceite isso conscientemente (log com retenção curta e acesso restrito) ou configure o formato de log para mascarar o caminho.

### 1.5 Dependências e imagem

- [ ] `[RECOMENDADO]` Sem vulnerabilidades conhecidas graves nas dependências Python (ajuste o caminho do requirements):

  ```bash
  pip install pip-audit && pip-audit -r backend/requirements.txt
  ```

- [ ] `[RECOMENDADO]` `[⚙️ CÓDIGO]` O container do backend roda como usuário não-root (`USER app` no Dockerfile).
- [ ] `[RECOMENDADO]` Imagens base com versão fixada (`python:3.12-slim`, `mysql:8.0`, `redis:7-alpine`), não `latest`.

### 1.6 docker-compose.yml `[⚙️ CÓDIGO]`

- [ ] `[BLOQUEADOR]` Todos os serviços com `restart: unless-stopped`.
- [ ] `[BLOQUEADOR]` Backend com `healthcheck` (não só o MySQL). Se não existir rota de health, criar `/healthz` que responde 200 e testa conexão com banco e Redis, **sem** exigir login e **sem** expor detalhes internos.
- [ ] `[BLOQUEADOR]` MySQL e Redis **sem** `ports:` publicados; backend publicado só em `127.0.0.1:3000:8000`. O Docker ignora o `ufw` para portas publicadas, então expor `0.0.0.0` furaria o firewall.
- [ ] `[RECOMENDADO]` Rotação dos logs do Docker em todos os serviços (evita encher o disco):

  ```yaml
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "5"
  ```

- [ ] `[BLOQUEADOR]` Imagem do backend com **tag de versão**, para permitir rollback (seção 13):

  ```yaml
  backend:
    image: comemore-backend:${APP_VERSION:-dev}
    build: ./backend
  worker:
    image: comemore-backend:${APP_VERSION:-dev}   # mesma imagem do backend
  ```

- [ ] `[BLOQUEADOR]` Uploads (`/app/uploads`) em **volume nomeado**, para não se perderem ao recriar o container e para entrarem no backup (seção 12).

### 1.7 Versionamento

- [ ] `[BLOQUEADOR]` `VERSION` contém **só o semver** (ex.: `1.4.0`, sem prefixo nem `v`). Todos os comandos deste checklist (`$(cat VERSION)`, `APP_VERSION`) dependem disso.
  > ⚠ Hoje o arquivo contém `Comemore+ v1.4.0`, que gera tags inválidas (`vComemore+ v1.4.0`). Padronizar o arquivo e ajustar quem o lê (`app.py`) antes de usar os comandos abaixo.
- [ ] `[BLOQUEADOR]` Tag criada no git para a versão que vai para produção:

  ```bash
  git tag -a "v$(cat VERSION)" -m "Release $(cat VERSION)"
  git push origin "v$(cat VERSION)"
  ```

### 1.8 Migrations

- [ ] `[BLOQUEADOR]` `alembic upgrade head` aplicado do zero em banco vazio sem erro (primeiro deploy).
- [ ] `[BLOQUEADOR]` A partir do **segundo deploy**: migrations testadas contra uma **cópia restaurada do backup de produção**, não só banco vazio (ver seção 12.4).
- [ ] `[RECOMENDADO]` Cada migration tem `downgrade()` funcional, ou está documentado que ela não é reversível e o rollback exige restore.

---

## 2. Preparação e hardening da VPS

Conecte-se e execute como `pcs`:

```bash
ssh pcs@SEU_IP_VPS
```

### 2.1 Pacotes base

- [ ] **Docker Engine + Compose v2**

  ```bash
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker pcs
  # logout/login para o grupo valer
  docker --version && docker compose version
  ```

  Atenção: estar no grupo `docker` equivale a acesso root na máquina. Proteja o acesso SSH do `pcs` como se fosse root.

- [ ] **Git, tmux, utilitários**

  ```bash
  sudo apt-get update && sudo apt-get install -y git tmux curl jq
  tmux new -s deploy    # tudo a seguir roda dentro da sessão tmux
  ```

- [ ] (Opcional) zsh + Oh My Zsh

  ```bash
  sudo apt-get install -y zsh
  sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
  chsh -s $(which zsh) pcs
  ```

### 2.2 SSH `[BLOQUEADOR]`

- [ ] Login por chave funcionando para `pcs` **antes** de desligar senha (teste em outro terminal).
- [ ] Desligar login por senha e login direto de root:

  ```bash
  sudo nano /etc/ssh/sshd_config.d/99-hardening.conf
  ```

  ```
  PasswordAuthentication no
  KbdInteractiveAuthentication no
  PermitRootLogin no
  ```

  ```bash
  sudo sshd -t && sudo systemctl reload ssh
  # Em OUTRO terminal, confirme que ainda consegue entrar antes de fechar o atual
  ```

### 2.3 Firewall `[BLOQUEADOR]`

- [ ] Apenas SSH, HTTP e HTTPS abertos:

  ```bash
  sudo ufw default deny incoming
  sudo ufw default allow outgoing
  sudo ufw allow OpenSSH
  sudo ufw allow 80/tcp
  sudo ufw allow 443/tcp
  sudo ufw enable
  sudo ufw status verbose
  ```

- [ ] Verificar o firewall do painel da Hostinger também (se ativo, liberar só 22/80/443).

### 2.4 Proteção e manutenção `[RECOMENDADO]`

- [ ] **fail2ban** (bloqueia força bruta no SSH):

  ```bash
  sudo apt-get install -y fail2ban
  sudo systemctl enable --now fail2ban
  sudo fail2ban-client status sshd
  ```

- [ ] **Atualizações automáticas de segurança**:

  ```bash
  sudo apt-get install -y unattended-upgrades
  sudo dpkg-reconfigure -plow unattended-upgrades
  ```

- [ ] **Swap** (VPS pequena + MySQL + build Docker pode estourar memória):

  ```bash
  free -h   # se não houver swap:
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
  sudo mkswap /swapfile && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
  ```

- [ ] **Fuso e relógio**: `timedatectl` mostra NTP sincronizado. Manter o sistema em UTC é o padrão seguro; a aplicação já converte com `TZ_OFFSET_HOURS=-3`.

---

## 3. DNS e e-mail

- [ ] `[BLOQUEADOR]` Registros `A` de `seudominio.com.br` e `www` apontando para o IP da VPS:

  ```bash
  dig +short $DOMINIO
  dig +short www.$DOMINIO
  ```

- [ ] `[BLOQUEADOR]` Domínio autenticado na Brevo, com **SPF, DKIM e DMARC** configurados no DNS (Brevo → Remetentes, domínios e IPs dedicados → Domínios). Sem isso, o e-mail de verificação tende a cair em spam e o usuário não consegue concluir o cadastro.

  ```bash
  dig +short TXT $DOMINIO            # SPF: deve conter include:spf.brevo.com
  dig +short TXT _dmarc.$DOMINIO     # DMARC: v=DMARC1; p=none (começar com none e endurecer depois)
  ```

- [ ] `[RECOMENDADO]` Remetente (`EMAIL_USER`/From) usa o próprio domínio, não Gmail.

---

## 4. Clone do repositório e estrutura

```bash
cd /home/pcs
git clone https://github.com/Paulo-Marcelo-Git/project_rsvp_birthday.git
cd project_rsvp_birthday
git checkout "v$(cat VERSION)"   # deploy sempre de uma tag, nunca de branch solta
mkdir -p logs
ls -la   # deve conter: backend/ backup/ docker-compose.yml .env.example CLAUDE.md VERSION
```

---

## 5. `.env` de produção

**Nunca comite o `.env`. Nunca copie o `.env.example`, porque ele tem valores de dev. Nunca cole valores deste arquivo no chat de nenhuma IA nem em issues/PRs.**

```bash
nano /srv/projects/project_rsvp_birthday/.env
```

```env
# ── Banco de dados ────────────────────────────────────────────────────────────
DB_NAME=rsvp_db
DB_USER=rsvp_app                  # usuário dedicado, NÃO root (seção 6)
DB_PASSWORD=← gerar: openssl rand -base64 32
DB_ROOT_PASSWORD=← gerar: openssl rand -base64 32 (diferente da anterior) [⚙️ ver nota]
DB_HOST=db

# ── Flask ─────────────────────────────────────────────────────────────────────
SECRET_KEY=← gerar: openssl rand -base64 32

# ── Opcionais ─────────────────────────────────────────────────────────────────
TZ_OFFSET_HOURS=-3
LOG_FILE=logs/app.log
UPLOAD_FOLDER=/app/uploads

# ── Email transacional — Brevo ────────────────────────────────────────────────
EMAIL_SMTP=smtp-relay.brevo.com
EMAIL_PORTA=587
EMAIL_USER=← login da Brevo
EMAIL_PASS=← chave SMTP (Brevo > Configurações > SMTP e API)

# ── URL base (links de email) ─────────────────────────────────────────────────
APP_BASE_URL=https://← seudominio.com.br

# ── SKIP_EMAIL_VERIFICATION: NÃO definir em produção
# ── FLASK_DEBUG: NÃO definir em produção

# ── Redis / RQ ────────────────────────────────────────────────────────────────
REDIS_URL=redis://redis:6379/0

# ── Backup ────────────────────────────────────────────────────────────────────
BACKUP_RETENTION_DAYS=7
HEALTHCHECK_BACKUP_URL=← URL de ping do Healthchecks.io (seção 15)

# ── Versão em execução (usada na tag da imagem) ───────────────────────────────
APP_VERSION=← conteúdo do arquivo VERSION

# ── Super-admin ───────────────────────────────────────────────────────────────
# ⚠ Este email NÃO deve existir como conta de tenant. Use um email dedicado.
SUPERADMIN_EMAIL=← email-admin-dedicado@seudominio.com
```

> **Nota `[⚙️ CÓDIGO]`:** verifique no `docker-compose.yml` como o MySQL recebe a senha de root. Se hoje ele usa `MYSQL_ROOT_PASSWORD=${DB_PASSWORD}`, troque para `${DB_ROOT_PASSWORD}`, para que a aplicação e o root tenham senhas diferentes.

- [ ] `[BLOQUEADOR]` Todos os segredos gerados **agora**, na VPS, e diferentes dos de desenvolvimento (`DB_PASSWORD`, `DB_ROOT_PASSWORD`, `SECRET_KEY`, senha do superadmin).
- [ ] `[BLOQUEADOR]` Permissão restrita ao dono:

  ```bash
  chmod 600 .env && ls -l .env    # -rw------- pcs pcs
  ```

- [ ] `[BLOQUEADOR]` Variáveis que não podem existir em produção (as linhas de comentário acima não contam):

  ```bash
  grep -E '^(SKIP_EMAIL_VERIFICATION|FLASK_DEBUG)=' .env   # deve retornar vazio
  grep -E '^EMAIL_SMTP=' .env                              # smtp-relay.brevo.com
  grep -E '^DB_USER=' .env                                 # rsvp_app (não root)
  ```

- [ ] `[BLOQUEADOR]` Nenhum placeholder esquecido:

  ```bash
  grep -c '←' .env   # deve retornar 0
  ```

---

## 6. Usuário dedicado do MySQL `[BLOQUEADOR]`

A aplicação não deve conectar como `root`: uma falha de SQL injection com root dá controle total do servidor de banco.

> Se o compose cria o usuário automaticamente via `MYSQL_USER`/`MYSQL_PASSWORD` (com os valores de `DB_USER`/`DB_PASSWORD`), este passo já está resolvido e só precisa ser verificado. Caso contrário, faça manualmente após o MySQL subir (seção 8):

```bash
docker exec -it rsvp_mysql mysql -u root -p
# digite a DB_ROOT_PASSWORD quando pedir (não passe a senha na linha de comando)
```

```sql
-- Substitua o placeholder digitando a senha do .env diretamente no prompt do MySQL.
CREATE USER IF NOT EXISTS 'rsvp_app'@'%' IDENTIFIED BY 'COLE_AQUI_O_DB_PASSWORD';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, REFERENCES
  ON rsvp_db.* TO 'rsvp_app'@'%';
FLUSH PRIVILEGES;
SHOW GRANTS FOR 'rsvp_app'@'%';   -- só rsvp_db.*, nada em *.*
```

- [ ] `SHOW GRANTS` mostra privilégios **apenas** em `rsvp_db.*`.
- [ ] Limpar o histórico do cliente MySQL, que guarda o comando com a senha:

  ```bash
  docker exec rsvp_mysql sh -c 'rm -f /root/.mysql_history'
  ```

> `CREATE`, `ALTER`, `DROP` e `INDEX` estão aqui porque o Alembic roda com o mesmo usuário. Uma melhoria futura é separar um usuário só de migration e deixar a aplicação com `SELECT, INSERT, UPDATE, DELETE`.

---

## 7. nginx, HTTPS e headers de segurança

### 7.1 Configuração inicial

```bash
sudo nano /etc/nginx/sites-available/comemore
```

```nginx
# Zonas de rate limit (este arquivo é incluído dentro do bloco http)
limit_req_zone $binary_remote_addr zone=auth:10m  rate=5r/m;
limit_req_zone $binary_remote_addr zone=rsvp:10m  rate=20r/m;
limit_req_zone $binary_remote_addr zone=geral:10m rate=10r/s;

server {
    listen 80;
    server_name seudominio.com.br www.seudominio.com.br;

    server_tokens off;
    client_max_body_size 55M;   # uploads até 50 MB + margem

    location ~ ^/(login|signup|resend-verification|forgot-password) {
        limit_req zone=auth burst=5 nodelay;
        limit_req_status 429;
        include /etc/nginx/snippets/comemore-proxy.conf;
    }

    # ⚙️ Ajuste para o caminho real do POST de confirmação de presença
    location ~ ^/invite/ {
        limit_req zone=rsvp burst=10 nodelay;
        limit_req_status 429;
        add_header X-Robots-Tag "noindex, nofollow" always;
        include /etc/nginx/snippets/comemore-proxy.conf;
    }

    location / {
        limit_req zone=geral burst=40 nodelay;
        limit_req_status 429;
        include /etc/nginx/snippets/comemore-proxy.conf;
    }
}
```

```bash
sudo nano /etc/nginx/snippets/comemore-proxy.conf
```

```nginx
proxy_pass         http://127.0.0.1:3000;
proxy_set_header   Host $host;
proxy_set_header   X-Real-IP $remote_addr;
proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header   X-Forwarded-Proto $scheme;
proxy_read_timeout 60s;
```

```bash
sudo ln -s /etc/nginx/sites-available/comemore /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t && sudo systemctl reload nginx
```

> Ajuste os nomes das rotas de `auth` e `invite` às rotas reais do app. Rotas que não existirem simplesmente não casam.

### 7.2 HTTPS `[BLOQUEADOR]`

```bash
sudo certbot --nginx -d $DOMINIO -d www.$DOMINIO --redirect
```

### 7.3 Headers de segurança (depois do certbot)

O certbot cria um bloco `server { listen 443 ssl; ... }`. **Dentro dele**, adicione:

```nginx
add_header Strict-Transport-Security "max-age=31536000" always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

> Cuidado com herança no nginx: um `add_header` dentro de um `location` (como o `X-Robots-Tag` em `/invite/`) **anula** os `add_header` do bloco `server` para aquela rota. Repita os headers de segurança dentro de `location ~ ^/invite/`, ou mova-os para um snippet incluído nos dois lugares. A seção 10 verifica isso.

> `Referrer-Policy` evita que o token de convite vaze no cabeçalho `Referer` quando o convidado clica em um link externo (ex.: Google Maps). `Content-Security-Policy` fica como `[RECOMENDADO]` para depois do go-live, porque exige mapear scripts e estilos do front para não quebrar páginas.

- [ ] `[BLOQUEADOR]` Renovação automática do certificado:

  ```bash
  sudo systemctl status certbot.timer   # active
  sudo certbot renew --dry-run
  ```

---

## 8. Primeiro deploy

- [ ] Build e subida, dentro do tmux:

  ```bash
  cd /srv/projects/project_rsvp_birthday
  export APP_VERSION=$(cat VERSION)
  docker compose build
  docker compose up -d
  ```

  O `entrypoint.sh` aguarda o MySQL, aplica `alembic upgrade head` e só então inicia o gunicorn (~2 min na primeira vez).

- [ ] Acompanhar o boot:

  ```bash
  docker logs -f rsvp_backend
  # [entrypoint] Aguardando MySQL...
  # [entrypoint] Aplicando migrations Alembic...
  # [entrypoint] Iniciando gunicorn...
  # [INFO] Booting worker with pid: ...
  ```

- [ ] Executar a seção 6 (usuário MySQL), se o compose não criar o usuário automaticamente, e reiniciar o backend:

  ```bash
  docker compose restart backend worker
  ```

- [ ] Registrar a versão em produção:

  ```bash
  docker image ls comemore-backend   # deve existir a tag $APP_VERSION
  echo "$(date -Iseconds) deploy v$APP_VERSION" >> ~/deploys.log
  ```

---

## 9. Validação dos containers

```bash
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
```

- [ ] `rsvp_mysql` — `Up … (healthy)`, **sem** porta publicada
- [ ] `rsvp_backend` — `Up … (healthy)`, porta `127.0.0.1:3000->8000/tcp` (nunca `0.0.0.0`)
- [ ] `rsvp_worker` — `Up …`, sem porta
- [ ] `rsvp_redis` — `Up …`, sem porta
- [ ] `rsvp_backup` — `Up …`, sem porta

- [ ] `[BLOQUEADOR]` Política de restart em todos:

  ```bash
  for c in rsvp_mysql rsvp_backend rsvp_worker rsvp_redis rsvp_backup; do
    echo "$c: $(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' $c)"
  done
  # todos: unless-stopped
  ```

- [ ] `[BLOQUEADOR]` Teste de auto-recuperação: derrubar o processo e ver o container voltar sozinho:

  ```bash
  docker kill rsvp_backend
  sleep 20 && docker ps --filter name=rsvp_backend
  # Status: Up … (o Docker reiniciou)
  ```

  Observação: `docker kill` aciona a política `unless-stopped`; `docker stop` não aciona (é parada intencional).

- [ ] `[BLOQUEADOR]` Portas realmente fechadas vistas de fora. Rodar **da sua máquina local**, não da VPS:

  ```bash
  nc -zv -w 3 SEU_IP_VPS 3306   # deve falhar (MySQL)
  nc -zv -w 3 SEU_IP_VPS 6379   # deve falhar (Redis)
  nc -zv -w 3 SEU_IP_VPS 3000   # deve falhar (backend direto)
  nc -zv -w 3 SEU_IP_VPS 443    # deve conectar
  ```

- [ ] Worker ouvindo a fila:

  ```bash
  docker logs rsvp_worker | tail -5
  # Worker rsvp_worker: started … Listening on queues: default
  ```

- [ ] Migrations aplicadas:

  ```bash
  docker exec rsvp_backend alembic current   # XXXX (head)
  ```

- [ ] Backup cron ativo:

  ```bash
  docker exec rsvp_backup crontab -l
  # 05 2 * * * /backup.sh >> /var/log/backup.log 2>&1
  ```

- [ ] `[RECOMENDADO]` Backend rodando como não-root:

  ```bash
  docker exec rsvp_backend id -u   # diferente de 0
  ```

---

## 10. Validação do backend (curl)

Rodar da **máquina local**, com `DOMINIO` e `BASE_URL` exportados (seção 0).

### 10.1 HTTPS `[BLOQUEADOR]`

```bash
curl -sI http://$DOMINIO/login | grep -iE '^(HTTP|location)'
# HTTP/1.1 301 … Location: https://seudominio.com.br/login

curl -sI http://www.$DOMINIO/ | grep -iE '^(HTTP|location)'
# 301 para https

curl -sI $BASE_URL/login | head -1
# HTTP/2 200
```

- [ ] Todas as variações em HTTP redirecionam para HTTPS.
- [ ] Certificado válido e com validade restante:

  ```bash
  echo | openssl s_client -connect $DOMINIO:443 -servername $DOMINIO 2>/dev/null \
    | openssl x509 -noout -subject -enddate
  ```

### 10.2 Headers de segurança `[BLOQUEADOR]`

```bash
for path in /login /invite/token-inexistente; do
  echo "== $path"
  curl -sI "$BASE_URL$path" | grep -iE 'strict-transport|x-content-type|x-frame|referrer-policy|^server:'
done
```

- [ ] `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options` e `Referrer-Policy` presentes **nas duas rotas** (confirma que o `add_header` de `/invite/` não anulou os demais).
- [ ] Header `Server` sem versão do nginx (`server: nginx`, sem número).

### 10.3 Debug desligado `[BLOQUEADOR]`

```bash
curl -s $BASE_URL/rota-que-nao-existe-123 | grep -ciE 'traceback|werkzeug|debugger|File "/'
# esperado: 0

docker exec rsvp_backend printenv FLASK_DEBUG FLASK_ENV
# esperado: vazio
```

> Use `printenv VAR` com nomes específicos. **Nunca** rode `docker exec … env` ou `docker inspect` sem filtro: os dois imprimem todas as variáveis, inclusive senhas.

### 10.4 Rotas protegidas sem sessão `[BLOQUEADOR]`

```bash
for path in /admin/respostas /admin/eventos /admin/convidados /superadmin; do
  printf "%-25s " "$path"
  curl -s -o /dev/null -w "%{http_code} -> %{redirect_url}\n" "$BASE_URL$path"
done
# Esperado: 302 -> …/login  (ou 401/403). Nunca 200.
```

- [ ] Nenhuma rota de admin/superadmin retorna 200 sem sessão. Ajuste a lista às rotas reais; o teste automatizado da seção 1.1 cobre todas.

### 10.5 Rate limit `[BLOQUEADOR]`

```bash
for i in $(seq 1 15); do
  curl -s -o /dev/null -w "%{http_code} " -X POST $BASE_URL/login \
    -d "email=naoexiste@example.com&password=senha-errada"
done; echo
# Esperado: algumas respostas 400/401/200 e depois 429
```

- [ ] Aparece `429` após poucas tentativas. Se o CSRF devolver sempre `400`, ainda assim o `429` do nginx deve aparecer, porque ele atua antes do Flask.
- [ ] Repetir para `/signup` e para o POST de confirmação de RSVP.
- [ ] Aguardar 1 minuto e confirmar que o acesso volta ao normal (o bloqueio é temporário).

### 10.6 Health

```bash
curl -s -o /dev/null -w "%{http_code}\n" $BASE_URL/healthz   # 200
```

### 10.7 Segredos na imagem `[BLOQUEADOR]`

```bash
docker history --no-trunc comemore-backend:$APP_VERSION | grep -ciE 'password=|secret_key=|api_key=|token='
# esperado: 0

docker exec rsvp_backend sh -c 'ls -la /app/.env 2>/dev/null || echo "sem .env na imagem"'
# esperado: "sem .env na imagem" (as variáveis chegam via env_file do compose, não via cópia do arquivo)
```

---

## 11. Validação do front-end com Playwright `[🎭 PLAYWRIGHT]`

Toda esta seção é executada pelo **Claude Code com o Playwright MCP**, apontando para `$BASE_URL`. Regras na seção 0: o agente não digita senhas, usa só os tenants de teste e salva evidências em `.playwright-mcp/`.

### Prompt para iniciar no Claude Code

```text
Execute a seção 11 do DEPLOY_CHECKLIST.md contra https://seudominio.com.br usando o Playwright MCP.
Regras:
- Nunca digite senhas. Quando precisar de login, abra a tela de login, pare e me peça para
  logar manualmente na janela do navegador. Continue só depois que eu confirmar.
- Use apenas os tenants de teste teste-a e teste-b. Não acesse eventos reais.
- Para cada item: execute, compare com o "Esperado" e registre PASSOU/FALHOU com uma frase de evidência.
- Screenshots apenas em .playwright-mcp/ e apenas de telas dos tenants de teste.
- Ao terminar, gere uma tabela-resumo com todos os itens e marque os que falharam.
- Não corrija código durante a validação; apenas reporte.
```

### 11.1 HTTPS e segurança no navegador

- [ ] Navegar para `http://seudominio.com.br/login`.
  **Esperado:** URL final começa com `https://`; nenhum aviso de certificado.
- [ ] Na página de login, ler o console (`browser_console_messages`).
  **Esperado:** sem erros de *mixed content* (recursos carregados via `http://`) e sem erros de JavaScript.
- [ ] Em `browser_network_requests`, conferir que todas as requisições da página usam `https://`.

### 11.2 Cadastro, verificação de e-mail e login

- [ ] Navegar para `/signup`, preencher nome e e-mail do **tenant de teste A**. No campo de senha, **pausar** e pedir para o usuário digitar e enviar.
  **Esperado:** mensagem "Verifique seu email"; o usuário **não** é logado automaticamente.
- [ ] `[👤 MANUAL]` Usuário abre o e-mail recebido.
  **Esperado:** chega em até 2 minutos, **na caixa de entrada (não no spam)**, com link `https://seudominio.com.br/verify-email/<token>`.
  Se não chegar: `docker logs rsvp_worker | grep -i email`.
- [ ] Antes de verificar, tentar logar com o tenant A (usuário digita a senha).
  **Esperado:** login bloqueado com aviso de e-mail não verificado.
- [ ] `[👤 MANUAL]` Usuário cola o link de verificação; o agente navega até ele.
  **Esperado:** redirect para `/login` com "Email verificado".
- [ ] Reabrir o **mesmo** link de verificação.
  **Esperado:** mensagem de link já usado/inválido, sem erro 500.
- [ ] Login do tenant A (usuário digita).
  **Esperado:** redirect para `/admin/respostas`.
- [ ] Repetir cadastro, verificação e login para o **tenant de teste B**.

### 11.3 Painel admin (tenant A)

- [ ] Abrir "Textos", editar e salvar.
  **Esperado:** modal abre e salva sem erro; ao recarregar, o texto novo persiste.
- [ ] "+ Convidado" com nome `Convidado Teste A1`.
  **Esperado:** aparece na lista.
- [ ] **Teste de XSS armazenado:** adicionar convidado com o nome `<img src=x onerror=alert(1)>`.
  **Esperado:** o texto aparece **literalmente** na lista (escapado); nenhum `alert`/diálogo dispara; console sem erros. Repetir a verificação na página do convite desse convidado.
- [ ] Upload de imagem válida (JPEG/PNG) no evento, com `browser_file_upload`.
  **Esperado:** aceita e exibe a imagem.
- [ ] Upload de arquivo **SVG** e de arquivo `.html` renomeado para `.jpg` (fixtures de teste fora do repositório de produção).
  **Esperado:** os dois são **recusados** com mensagem amigável, sem erro 500.
- [ ] Anotar, para o teste 11.5, as URLs de: um convidado, o evento, a lista de respostas, uma imagem enviada e o token de convite do `Convidado Teste A1`.

### 11.4 Fluxo do convidado no celular (fluxo crítico) `[BLOQUEADOR]`

- [ ] `browser_resize` para **390 × 844** (iPhone 12–15).
- [ ] Encerrar a sessão do admin (logout) para simular um convidado anônimo.
- [ ] Navegar para `/invite/<token do Convidado Teste A1>`.
  **Esperado:** página carrega com os textos editados em 11.3 e a imagem do evento.
- [ ] Verificar ausência de rolagem horizontal com `browser_evaluate`:

  ```js
  () => document.documentElement.scrollWidth <= window.innerWidth
  ```

  **Esperado:** `true`.
- [ ] Botões e campos visíveis e clicáveis sem zoom (snapshot e screenshot da tela inteira).
- [ ] **Confirmar presença** preenchendo os campos pedidos.
  **Esperado:** mensagem de confirmação clara; sem erro no console.
- [ ] Recarregar a página do convite.
  **Esperado:** mostra o estado "confirmado" (ou permite alterar), sem duplicar a resposta.
- [ ] Repetir em **360 × 800** (Android comum).
- [ ] Voltar ao tamanho desktop; usuário loga como tenant A; abrir `/admin/respostas`.
  **Esperado:** a confirmação aparece com os dados corretos, **uma única vez**.
- [ ] Navegar para `/invite/token-invalido-xyz`.
  **Esperado:** página amigável de convite não encontrado (404), sem stack trace.

### 11.5 Isolamento entre tenants `[BLOQUEADOR]`

- [ ] Logout do tenant A. Usuário loga como **tenant B**.
- [ ] Logado como B, navegar para cada URL anotada em 11.3 (convidado, evento, respostas e imagem do tenant A).
  **Esperado:** 403 ou 404 em **todas**; nenhum dado do tenant A visível no snapshot.
- [ ] Logado como B, abrir `/admin/respostas`.
  **Esperado:** lista vazia (ou só dados de B); nenhum `Convidado Teste A1`.
- [ ] Se as URLs usam IDs numéricos, trocar o ID de um recurso de B pelo ID vizinho (±1) e navegar.
  **Esperado:** 403/404, nunca o recurso de outro tenant.
- [ ] Logado como B, tentar uma **ação** sobre dado de A (editar ou excluir convidado de A pela URL/rota direta, se for GET; se for POST, usar `browser_evaluate` com `fetch` incluindo o token CSRF da página atual).
  **Esperado:** 403/404; ao voltar como A, o convidado continua intacto.

### 11.6 Superadmin

- [ ] Logado como tenant B, navegar para `/superadmin`.
  **Esperado:** 403 ou redirect; nunca a lista de tenants.
- [ ] Logout. Usuário loga com a conta de `SUPERADMIN_EMAIL`. Navegar para `/superadmin`.
  **Esperado:** lista de tenants contendo teste-a e teste-b.

### 11.7 Sessão e cookies

- [ ] Logado, executar com `browser_evaluate`:

  ```js
  () => document.cookie
  ```

  **Esperado:** o cookie de sessão **não aparece** (prova de `HttpOnly`). Pode haver cookies não sensíveis.
- [ ] Clicar em logout e, em seguida, usar "voltar" do navegador e recarregar uma página de admin.
  **Esperado:** redireciona para `/login`; nenhum dado de admin acessível após o logout.

### 11.8 Páginas de erro e debug

- [ ] Navegar para `/pagina-que-nao-existe`.
  **Esperado:** 404 amigável, sem stack trace, sem nome de arquivo Python, sem a palavra "Werkzeug".
- [ ] Navegar para `/admin/convidados/999999999` (ou a rota equivalente) logado como A.
  **Esperado:** 404 amigável, sem erro 500.

### 11.9 Desempenho percebido (mobile)

- [ ] Em 390 × 844, medir o carregamento da página do convite com `browser_evaluate`:

  ```js
  () => {
    const n = performance.getEntriesByType('navigation')[0];
    return { domContentLoaded: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd) };
  }
  ```

  **Esperado:** `load` abaixo de ~3000 ms. Se as imagens do evento forem grandes, considerar redimensionar no upload.

### 11.10 Limpeza

- [ ] Excluir os convidados e eventos de teste dos tenants A e B pelo painel.
- [ ] Remover os tenants de teste (via superadmin ou banco), **ou** mantê-los desativados e marcados como teste para o próximo deploy. Decisão: ______
- [ ] Apagar `.playwright-mcp/` se os screenshots não forem mais necessários.

### 11.11 Teste em celular físico `[👤 MANUAL]` `[BLOQUEADOR]`

O Playwright simula o tamanho da tela, mas não substitui um aparelho real.

- [ ] Abrir um convite de teste em um **celular físico, em 4G (fora do Wi-Fi)**, a partir do link enviado por WhatsApp, que é como o convidado real recebe.
- [ ] Confirmar presença e verificar no admin.
- [ ] Testar ao menos um iPhone (Safari) e um Android (Chrome), se possível.
- [ ] A pré-visualização do link no WhatsApp (título/imagem) aparece corretamente.

---

## 12. Backup, cópia externa e restore

Backup que nunca foi restaurado não conta. Backup que fica só na própria VPS não protege contra perda da VPS.

### 12.1 Backup local do banco

- [ ] Forçar um backup agora:

  ```bash
  docker exec rsvp_backup sh /backup.sh
  docker exec rsvp_backup ls -lh /backups/
  # comemore_YYYYMMDD_HHMMSS.sql.gz com tamanho > 0
  ```

- [ ] Log do backup sem erros:

  ```bash
  docker exec rsvp_backup tail -20 /var/log/backup.log
  ```

### 12.2 Backup dos uploads `[BLOQUEADOR]` `[⚙️ CÓDIGO]`

O `backup.sh` gera dump do MySQL; as imagens enviadas **não** estão nele.

- [ ] Identificar o volume de uploads:

  ```bash
  docker volume ls | grep -i upload
  ```

- [ ] Incluir os uploads na rotina (script da seção 12.3) com `tar` do volume em modo somente leitura.

### 12.3 Cópia externa (offsite) `[BLOQUEADOR]` `[⚙️ CÓDIGO]`

Recomendação: **rclone** com destino em Backblaze B2, S3 ou Google Drive, usando um remote do tipo **crypt**. Os backups contêm dados pessoais de convidados (LGPD) e devem sair da VPS criptografados.

- [ ] `[⚙️ CÓDIGO]` Expor os backups para o host com bind mount no compose (ex.: `/home/pcs/backups:/backups` no serviço `rsvp_backup`), para o script do host conseguir ler.
- [ ] Instalar e configurar o rclone **interativamente na VPS** (as credenciais do destino ficam só no `rclone.conf`, nunca no repositório):

  ```bash
  sudo apt-get install -y rclone
  rclone config          # criar remote "destino" e, sobre ele, remote crypt "offsite"
  chmod 600 ~/.config/rclone/rclone.conf
  ```

  Guarde a senha do remote crypt em um gerenciador de senhas **fora da VPS**. Sem ela, o backup externo não pode ser restaurado.

- [ ] Criar o arquivo de ambiente do script, com permissão restrita:

  ```bash
  nano ~/.offsite.env && chmod 600 ~/.offsite.env
  # HEALTHCHECK_OFFSITE_URL=← URL de ping do Healthchecks.io
  # UPLOADS_VOLUME=← nome do volume de uploads
  ```

- [ ] Criar `~/bin/offsite-backup.sh`:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  source ~/.offsite.env
  BACKUP_DIR=/home/pcs/backups
  STAMP=$(date +%Y%m%d_%H%M%S)

  trap 'curl -fsS -m 10 --retry 3 "$HEALTHCHECK_OFFSITE_URL/fail" >/dev/null || true' ERR

  # Uploads (somente leitura)
  docker run --rm -v "$UPLOADS_VOLUME":/data:ro -v "$BACKUP_DIR":/out alpine \
    tar czf "/out/uploads_$STAMP.tar.gz" -C /data .

  # Envia o que foi gerado nas últimas 26h
  rclone copy "$BACKUP_DIR" offsite:comemore --max-age 26h

  # Retenção externa: 30 dias
  rclone delete offsite:comemore --min-age 30d

  # Retenção local dos tarballs de upload: 7 dias
  find "$BACKUP_DIR" -name 'uploads_*.tar.gz' -mtime +7 -delete

  curl -fsS -m 10 --retry 3 "$HEALTHCHECK_OFFSITE_URL" >/dev/null
  ```

  ```bash
  chmod 700 ~/bin/offsite-backup.sh
  ~/bin/offsite-backup.sh && rclone ls offsite:comemore
  ```

- [ ] Agendar após o backup do banco (02h05 BRT = 05h05 UTC):

  ```bash
  crontab -e
  # 30 5 * * * /home/pcs/bin/offsite-backup.sh >> /home/pcs/logs-offsite.log 2>&1
  ```

### 12.4 Restore de teste `[BLOQUEADOR]`

Critério: **restaurei o backup de ontem, a partir da cópia externa, num banco limpo, e os dados estavam lá**.

- [ ] Baixar o dump mais recente **da cópia externa** (não do disco local):

  ```bash
  mkdir -p /tmp/restore-test
  rclone copy offsite:comemore /tmp/restore-test --include 'comemore_*.sql.gz' --max-age 26h
  ls -lh /tmp/restore-test
  ```

- [ ] Restaurar em banco separado (não toca o `rsvp_db`):

  ```bash
  ARQ=$(ls -t /tmp/restore-test/comemore_*.sql.gz | head -1)
  docker cp "$ARQ" rsvp_backup:/tmp/restore.sql.gz
  docker exec rsvp_backup sh /restore.sh /tmp/restore.sql.gz rsvp_restore_test
  # "Restore concluído."
  ```

- [ ] Comparar **contagem de linhas** das tabelas principais (tabela restaurada vazia também gera "Restore concluído"). Ajuste os nomes das tabelas:

  ```bash
  docker exec -it rsvp_mysql mysql -u root -p -e "
    SELECT 'prod', (SELECT COUNT(*) FROM rsvp_db.convidados), (SELECT COUNT(*) FROM rsvp_db.eventos)
    UNION ALL
    SELECT 'restore', (SELECT COUNT(*) FROM rsvp_restore_test.convidados), (SELECT COUNT(*) FROM rsvp_restore_test.eventos);"
  ```

  **Esperado:** números iguais ou muito próximos (diferença = o que entrou desde o backup).

- [ ] Restaurar o tarball de uploads em diretório temporário e conferir que as imagens abrem:

  ```bash
  rclone copy offsite:comemore /tmp/restore-test --include 'uploads_*.tar.gz' --max-age 26h
  mkdir -p /tmp/restore-test/uploads && tar xzf $(ls -t /tmp/restore-test/uploads_*.tar.gz | head -1) -C /tmp/restore-test/uploads
  ls /tmp/restore-test/uploads | head
  ```

- [ ] Limpar:

  ```bash
  docker exec -it rsvp_mysql mysql -u root -p -e "DROP DATABASE rsvp_restore_test;"
  rm -rf /tmp/restore-test
  ```

- [ ] Registrar data e duração do restore: ______ (tempo de restore = parte do tempo de recuperação em um incidente real)

### 12.5 Testar migrations contra cópia dos dados reais (a partir do 2º deploy)

- [ ] Restaurar o backup mais recente em `rsvp_staging` (mesmo procedimento da 12.4).
- [ ] Rodar as migrations **da nova versão** contra ele, sem tocar produção:

  ```bash
  docker compose run --rm -e DB_NAME=rsvp_staging backend alembic upgrade head
  ```

- [ ] Se a migration tem `downgrade`, testar a volta:

  ```bash
  docker compose run --rm -e DB_NAME=rsvp_staging backend alembic downgrade -1
  ```

- [ ] Remover `rsvp_staging`.

---

## 13. Plano de rollback `[BLOQUEADOR]`

Objetivo: voltar para a versão anterior em **menos de 10 minutos**.

### 13.1 Script de deploy com backup prévio `[⚙️ CÓDIGO]`

Criar `/home/pcs/bin/deploy.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
TAG="${1:?uso: deploy.sh vX.Y.Z}"
[[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Tag inválida: $TAG"; exit 1; }

cd /srv/projects/project_rsvp_birthday
PREV=$(grep '^APP_VERSION=' .env | cut -d= -f2)
NEW="${TAG#v}"

echo "→ Backup pré-deploy"
docker exec rsvp_backup sh /backup.sh

echo "→ Código $TAG"
git fetch --tags --quiet
git checkout --quiet "$TAG"

echo "→ Build e subida v$NEW"
sed -i "s/^APP_VERSION=.*/APP_VERSION=$NEW/" .env
docker compose build backend
docker compose up -d

echo "→ Health check"
for i in $(seq 1 12); do
  if curl -fs -o /dev/null http://127.0.0.1:3000/healthz; then
    echo "$(date -Iseconds) deploy $PREV -> $NEW OK" >> ~/deploys.log
    echo "✓ Deploy concluído: v$NEW (anterior: v$PREV)"
    exit 0
  fi
  sleep 5
done

echo "✗ Health check falhou. Siga a seção 13.2 para voltar para v$PREV."
echo "$(date -Iseconds) deploy $PREV -> $NEW FALHOU" >> ~/deploys.log
exit 1
```

```bash
chmod 700 /home/pcs/bin/deploy.sh
```

> O docker compose lê `APP_VERSION` do `.env` na pasta do projeto para montar a tag da imagem, então não é preciso exportar a variável.

### 13.2 Procedimento de rollback

**Ponto crítico:** o `entrypoint.sh` roda `alembic upgrade head`. Se a versão nova aplicou uma migration, o código antigo não conhece essa revisão e **o backend antigo pode não subir**. Por isso o banco precisa voltar antes do código.

**Caso A — a versão nova não teve migration:**

```bash
cd /srv/projects/project_rsvp_birthday
git checkout vANTERIOR
sed -i "s/^APP_VERSION=.*/APP_VERSION=ANTERIOR/" .env
docker compose up -d          # sem build: a imagem antiga ainda existe localmente
curl -fs -o /dev/null -w "%{http_code}\n" http://127.0.0.1:3000/healthz
```

**Caso B — teve migration com `downgrade` funcional:**

```bash
# 1. Com o código NOVO ainda em execução, voltar o banco para a revisão anterior
docker exec rsvp_backend alembic downgrade <revisão_anterior>
# 2. Depois, executar o Caso A
```

**Caso C — teve migration sem `downgrade` (ou o downgrade falhou):**

```bash
# Restaurar o backup feito pelo deploy.sh logo antes do deploy.
# ⚠ Perde o que foi gravado entre o deploy e agora. Avisar os tenants afetados.
docker exec rsvp_backup sh /restore.sh /backups/<arquivo_pre_deploy>.sql.gz rsvp_db
# Depois, executar o Caso A
```

- [ ] `[BLOQUEADOR]` **Rollback ensaiado uma vez** antes do go-live: deploy de uma versão de teste (ex.: `v0.0.1-rc`) seguido de rollback, cronometrado. Tempo: ______ min.
- [ ] `[BLOQUEADOR]` Imagens das **3 últimas versões** mantidas na VPS. Nunca rodar `docker image prune -a` sem conferir:

  ```bash
  docker image ls comemore-backend
  ```

---

## 14. CI/CD — GitHub Actions

### 14.1 Segredos do repositório

GitHub → repositório → Settings → Secrets and variables → Actions:

- [ ] `VPS_HOST`, `VPS_USER` (`pcs`), `VPS_PORT`, `VPS_PATH`
- [ ] `VPS_SSH_KEY` — chave **dedicada** ao CI, sem passphrase:

  ```bash
  # Na máquina local
  ssh-keygen -t ed25519 -C "github-actions-comemore" -f ~/.ssh/comemore_ci
  ssh-copy-id -i ~/.ssh/comemore_ci.pub pcs@SEU_IP_VPS
  ```

  Cole o conteúdo da chave privada **direto no campo do GitHub**, abrindo o arquivo em um editor local. Não exiba com `cat` em terminal compartilhado, não cole em chat de IA e apague a cópia local se não for mais usá-la.

### 14.2 Gates do workflow `[BLOQUEADOR]` `[⚙️ CÓDIGO]`

- [ ] O job de deploy depende do job de testes (`needs: test`). Testes falhando = nenhum deploy.
- [ ] Merge em `main` só via PR com CI verde.
  > ⚠ Repositório **privado** em conta pessoal no plano **GitHub Free** não tem branch protection (disponível só em repo público ou nos planos pagos). Por isso o bloqueio obrigatório é no **deploy** (`needs: test`, item acima); o "só mergear com CI verde" é disciplina do responsável. Se o repositório for público ou o plano mudar, ativar a branch protection exigindo PR + CI verde.
- [ ] O workflow chama o `deploy.sh` (seção 13.1), garantindo backup pré-deploy e health check.
- [ ] Nenhum `echo` de segredo no workflow; logs do Actions revisados no primeiro deploy.
- [ ] `[RECOMENDADO]` Deploy disparado por **tag** (`on: push: tags: ['v*']`), não por todo push em `main`. Assim só vai para produção o que foi versionado.
- [ ] `[RECOMENDADO]` GitHub Environment `production` com aprovação manual obrigatória.

### 14.3 Restringir o que a chave do CI pode fazer `[RECOMENDADO]` `[⚙️ CÓDIGO]`

Como `pcs` está no grupo `docker` (equivale a root), uma chave do CI vazada daria controle total da VPS. Restrinja a chave para só conseguir disparar o deploy.

- [ ] Criar `/home/pcs/bin/deploy-from-ci.sh`:

  ```bash
  #!/usr/bin/env bash
  set -euo pipefail
  TAG="${SSH_ORIGINAL_COMMAND:-}"
  [[ "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "Comando recusado"; exit 1; }
  exec /home/pcs/bin/deploy.sh "$TAG"
  ```

- [ ] Em `~/.ssh/authorized_keys` da VPS, prefixar a linha da chave do CI:

  ```
  command="/home/pcs/bin/deploy-from-ci.sh",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty ssh-ed25519 AAAA… github-actions-comemore
  ```

- [ ] Ajustar o `deploy.yml` para executar apenas `ssh … pcs@host "v1.2.3"`.
- [ ] Testar que a chave **não** abre shell:

  ```bash
  ssh -i ~/.ssh/comemore_ci pcs@SEU_IP_VPS "ls"   # deve responder "Comando recusado"
  ```

### 14.4 Validação

- [ ] Criar tag de teste e acompanhar em Actions.
  **Esperado:** testes passam → deploy → "✓ Deploy concluído" em ~60–120 s.
- [ ] Criar um commit com teste quebrado em branch e abrir PR.
  **Esperado:** CI vermelho e **nenhum deploy** (mesmo que o PR seja mergeado). Com branch protection disponível, o merge também fica bloqueado.

---

## 15. Monitoramento e alertas

O objetivo é saber que algo quebrou **antes** do cliente reclamar.

- [ ] `[BLOQUEADOR]` **Uptime externo** (UptimeRobot, Better Stack ou similar, plano gratuito):
  - Monitor HTTP em `https://seudominio.com.br/healthz`, intervalo de 5 min.
  - Monitor de palavra-chave em `/login` (detecta página carregando, mas quebrada).
  - Alerta por e-mail **e** por um canal que você vê rápido (Telegram, app no celular).
  - Monitor de expiração do certificado SSL (avisar com 14 dias de antecedência).
- [ ] Teste do alerta: `docker stop rsvp_backend` → alerta chega → `docker start rsvp_backend` → alerta de recuperação chega.

- [ ] `[BLOQUEADOR]` **Backup que não rodou gera alerta** (Healthchecks.io, plano gratuito):
  - Check "backup-db" com período de 1 dia + tolerância de 2 h.
  - `[⚙️ CÓDIGO]` No fim do `backup.sh`, após sucesso:

    ```sh
    curl -fsS -m 10 --retry 3 "$HEALTHCHECK_BACKUP_URL" >/dev/null
    ```

    E em caso de erro, ping em `"$HEALTHCHECK_BACKUP_URL/fail"`.
  - Check "backup-offsite" para o script da seção 12.3.
  - As URLs de ping contêm um identificador secreto: mantenha-as no `.env`/`.offsite.env`, nunca no repositório.

- [ ] `[RECOMENDADO]` **Disco**: alerta com uso acima de 80%. Exemplo no cron do host (de hora em hora):

  ```bash
  # ~/bin/check-disk.sh
  USO=$(df --output=pcent / | tail -1 | tr -dc '0-9')
  source ~/.offsite.env
  [ "$USO" -lt 80 ] || curl -fsS -m 10 "$HEALTHCHECK_OFFSITE_URL/fail" >/dev/null
  ```

  (Ideal: um check próprio no Healthchecks.io para disco.)

- [ ] `[RECOMENDADO]` **Erros da aplicação**: Sentry (plano gratuito) com `send_default_pii=False` e filtragem de e-mail/telefone antes do envio.
- [ ] `[RECOMENDADO]` **Cota de e-mail**: conferir no painel da Brevo se o uso diário está longe do limite de 300.
- [ ] `[RECOMENDADO]` Rotação do `logs/app.log` com logrotate no host:

  ```bash
  sudo nano /etc/logrotate.d/comemore
  ```

  ```
  /srv/projects/project_rsvp_birthday/logs/*.log {
      daily
      rotate 14
      compress
      missingok
      notifempty
      copytruncate
  }
  ```

---

## 16. LGPD

> Esta seção cobre o mínimo técnico. Não substitui orientação jurídica.

- [ ] `[BLOQUEADOR]` **Inventário do que é coletado**, com finalidade de cada campo. Remover do formulário o que não for necessário para o RSVP.

  | Dado | De quem | Finalidade | Retenção |
  |---|---|---|---|
  | Nome, e-mail, senha (hash) | Tenant (organizador) | Conta e acesso | Enquanto a conta existir |
  | Nome do convidado | Convidado | Lista de presença | ______ dias após o evento |
  | Telefone/e-mail do convidado (se houver) | Convidado | ______ | ______ |
  | Resposta (confirma/recusa, acompanhantes) | Convidado | RSVP | ______ dias após o evento |
  | Imagens do evento | Tenant | Exibição no convite | ______ |

- [ ] `[BLOQUEADOR]` **Política de privacidade** publicada e com link visível no signup e na página do convite: quem é o controlador, o que é coletado, para quê, por quanto tempo, com quem é compartilhado (Brevo para e-mail, provedor da VPS, destino do backup externo) e como pedir exclusão.
- [ ] `[BLOQUEADOR]` **Exclusão funciona de verdade**: excluir um evento remove convidados, respostas e imagens associados. Verificar após a limpeza da seção 11.10 (substitua o ID e os nomes de tabelas/colunas):

  ```sql
  SELECT COUNT(*) FROM convidados WHERE evento_id = <id_excluido>;  -- 0
  ```

  E conferir que o arquivo de imagem saiu do volume de uploads.

- [ ] `[RECOMENDADO]` `[⚙️ CÓDIGO]` Rotina de expiração: dados de convidados apagados ou anonimizados automaticamente após o prazo de retenção definido.
- [ ] `[BLOQUEADOR]` Logs sem dados pessoais (verificado na seção 1.4; repetir em produção após o smoke test):

  ```bash
  grep -cE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' logs/app.log   # 0
  ```

- [ ] `[BLOQUEADOR]` Backups com dados pessoais saem da VPS **criptografados** (seção 12.3) e têm retenção definida (7 dias local, 30 dias externo).
- [ ] `[RECOMENDADO]` Plano de incidente escrito: quem avaliar, como revogar credenciais, como comunicar titulares e a ANPD dentro do prazo da regulamentação vigente.

---

## 17. Primeiras 48 horas após o go-live

- [ ] Acompanhar erros do backend e do worker:

  ```bash
  docker logs rsvp_backend --since 1h 2>&1 | grep -ciE 'error|exception|traceback'
  docker logs rsvp_worker --since 24h | grep -E "Failed|Error"
  ```

- [ ] **Falsos positivos de rate limit**: no Brasil, muitos usuários de 4G compartilham IP (CGNAT). Vários convidados confirmando ao mesmo tempo podem ser bloqueados como se fossem um só.

  ```bash
  sudo awk '$9 == 429' /var/log/nginx/access.log | wc -l
  ```

  Se houver 429 em `/invite/` com tráfego legítimo, aumentar `rate`/`burst` da zona `rsvp`.

- [ ] Na manhã seguinte: backup das 02h rodou, cópia externa chegou e os dois checks do Healthchecks.io estão verdes.
- [ ] E-mails de verificação chegando (painel da Brevo: entregues × bounces × spam).
- [ ] Uso de disco e memória:

  ```bash
  df -h / && free -h && docker stats --no-stream
  ```

---

## 18. Go / No-Go

Só vai para produção com **todas** as linhas marcadas.

| # | Critério | Seção | Evidência | OK |
|---|---|---|---|---|
| 1 | Testes automatizados passando (fluxo crítico, isolamento, rotas protegidas) | 1.1 | saída do pytest | [ ] |
| 2 | Nenhum segredo no git nem na imagem | 1.2, 10.7 | gitleaks "no leaks"; grep = 0 | [ ] |
| 3 | Debug off, ProxyFix, cookies seguros, CSRF | 1.3, 10.3, 11.7 | curl + Playwright | [ ] |
| 4 | Logs sem dados pessoais e tokens | 1.4, 16 | grep -c = 0 | [ ] |
| 5 | Credenciais de produção novas e distintas das de dev | 5 | checklist do .env | [ ] |
| 6 | App usa usuário MySQL dedicado (não root) | 6 | SHOW GRANTS | [ ] |
| 7 | SSH só por chave, firewall só 22/80/443, portas internas fechadas | 2.2, 2.3, 9 | nc de fora | [ ] |
| 8 | HTTPS com redirect, certificado válido, renovação automática | 7.2, 10.1, 11.1 | curl + dry-run | [ ] |
| 9 | Headers de segurança em todas as rotas | 7.3, 10.2 | curl | [ ] |
| 10 | Rate limit em login, signup e RSVP | 1.3, 7.1, 10.5 | 429 observado | [ ] |
| 11 | Admin e superadmin exigem autenticação e autorização | 10.4, 11.6 | curl + Playwright | [ ] |
| 12 | Isolamento entre tenants | 11.5 | Playwright: 403/404 em tudo | [ ] |
| 13 | Upload aceita só imagens; XSS escapado | 11.3 | Playwright | [ ] |
| 14 | Fluxo do convidado no mobile (simulado + aparelho real) | 11.4, 11.11 | Playwright + teste manual | [ ] |
| 15 | Restart automático e health check | 1.6, 9 | docker kill → volta sozinho | [ ] |
| 16 | Backup do banco **e** uploads, com cópia externa criptografada | 12.1–12.3 | rclone ls | [ ] |
| 17 | Restore testado a partir da cópia externa, com contagem de linhas | 12.4 | tabela prod × restore | [ ] |
| 18 | Rollback ensaiado e cronometrado | 13 | tempo < 10 min | [ ] |
| 19 | CI só faz deploy com testes verdes e com backup prévio | 14.2 | deploy bloqueado com teste vermelho (+ merge bloqueado, se houver branch protection) | [ ] |
| 20 | Alerta de queda e de backup não executado funcionando | 15 | alerta de teste recebido | [ ] |
| 21 | Política de privacidade publicada e exclusão funcionando | 16 | link visível + SQL = 0 | [ ] |
| 22 | SPF/DKIM/DMARC; e-mail chega na caixa de entrada | 3, 11.2 | dig + e-mail recebido | [ ] |

**Decisão:** ☐ GO  ☐ NO-GO — Data: ______  Versão: v______  Responsável: ______

---

## 19. Referência rápida

```bash
# Status
docker ps
docker compose ps

# Logs
docker logs -f rsvp_backend
docker logs -f rsvp_worker

# Restart de um serviço
docker compose restart backend

# Deploy de uma versão (com backup prévio e health check)
~/bin/deploy.sh v1.2.3

# Histórico de deploys
cat ~/deploys.log

# Versão em produção
grep '^APP_VERSION=' .env

# Fila Redis
docker exec rsvp_redis redis-cli llen rq:queue:default

# MySQL (a senha é pedida no prompt; nunca use -pSENHA nem -p$VAR)
docker exec -it rsvp_mysql mysql -u rsvp_app -p rsvp_db

# Backup manual + cópia externa
docker exec rsvp_backup sh /backup.sh && ~/bin/offsite-backup.sh

# Variável específica do container (nunca use `env` ou `docker inspect` sem filtro)
docker exec rsvp_backend printenv APP_BASE_URL

# Parar tudo (mantém volumes)
docker compose down

# ⚠ Apagar volumes (DESTRÓI banco e uploads — só em reset total, com backup externo conferido):
# docker compose down -v
```