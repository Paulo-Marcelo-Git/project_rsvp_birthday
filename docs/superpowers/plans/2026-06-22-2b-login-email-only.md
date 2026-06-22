# 2B — Login Exclusivo por Email

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover o caminho de autenticação por username de `login()` e `forgot_password()` — login e reset de senha passam a aceitar **somente email**, pois `email` é UNIQUE global e resolve o tenant sem ambiguidade.

**Architecture:** `login()` lê o campo `email` (era `username`/`identifier`) e verifica primeiro contra `ADMIN_EMAIL` (env var nova, **TRANSITÓRIA**), depois chama `repo.get_user_by_email_global`. `forgot_password()` remove a detecção por `@` e sempre chama `repo.get_user_by_email_global`. Templates recebem `type=email`. Zero novos helpers ou rotas.

> ⚠️ **ADMIN_EMAIL é TRANSITÓRIO:** o bloco `if admin_email and email == admin_email` sai na **Fase 2D**, junto com a remoção completa de `AdminUser`, `ADMIN_USER` e `ADMIN_PASS` por env. Após o signup (2C), todo admin será um `DbUser` com `role=tenant_admin` na tabela `users`. O comentário no código deve deixar isso explícito para que não vire uma segunda via de login permanente.

**Tech Stack:** Python 3.12, Flask 3.0, SQLAlchemy 2.0 `text()`, pytest + MagicMock.

## Global Constraints

- SQL via `text()` com parâmetros nomeados — zero concatenação direta.
- `repo.get_user_by_email_global(conn, email)` já faz `LOWER(email) = LOWER(:email)` — não duplicar a lógica.
- Mensagem de resposta ao usuário SEMPRE genérica — nunca revelar se email existe (prevenção de enumeração).
- AdminUser (`id="admin"`) continua autenticado via env vars `ADMIN_EMAIL` + `ADMIN_PASS`. O campo `ADMIN_USER` permanece (controla o username de exibição) mas não é mais usado no login.
- Suíte não-integration deve passar completa: `python3 -m pytest tests/ -q` (exclui testes marcados `integration`).
- Commits frequentes, diff enxuto. Não tocar em nada fora das rotas `login`, `forgot_password`, templates correspondentes, conftest e test_auth/test_password_reset.

---

### Task 1: Rota `login()` — email-only + conftest + test_auth.py

**Files:**
- Modify: `backend/app.py:369-422` (rota `login`)
- Modify: `backend/tests/conftest.py:9-18` (adicionar `ADMIN_EMAIL`)
- Modify: `backend/tests/test_auth.py` (atualizar todos os testes + adicionar 1)

**Interfaces:**
- Consome: `repo.get_user_by_email_global(conn, email: str) -> dict | None` (já existe em `backend/repo.py:384`)
- Consome: `os.getenv("ADMIN_EMAIL")` — nova var de ambiente adicionada ao conftest
- Produz: `POST /login` com campo `email` (era `username`)

- [ ] **Step 1: Adicionar `ADMIN_EMAIL` ao conftest**

Em `backend/tests/conftest.py`, adicionar `'ADMIN_EMAIL': 'testadmin@test.com'` no bloco `os.environ.update({...})`:

```python
os.environ.update({
    'DB_USER': 'test',
    'DB_PASSWORD': 'test',
    'DB_HOST': 'localhost',
    'DB_NAME': 'test_db',
    'SECRET_KEY': 'test-secret-key-for-pytest-only!!',
    'ADMIN_USER': 'testadmin',
    'ADMIN_EMAIL': 'testadmin@test.com',
    'ADMIN_PASS': generate_password_hash(ADMIN_PASSWORD),
    'DEFAULT_PASSWORD': 'Default@1234',
})
```

- [ ] **Step 2: Escrever os testes atualizados e o novo teste de regressão**

Substituir o conteúdo completo de `backend/tests/test_auth.py`:

```python
from werkzeug.security import generate_password_hash
from tests.conftest import ADMIN_PASSWORD, qresult, setup_db


def test_login_page_loads(client):
    resp = client.get('/login')
    assert resp.status_code == 200


def test_login_credenciais_invalidas_exibe_erro(client, db):
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/login', data={
        'email': 'ninguem@test.com',
        'password': 'errada',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'inválidos' in resp.data.decode()


def test_login_admin_valido_redireciona_para_respostas(client):
    resp = client.post('/login', data={
        'email': 'testadmin@test.com',
        'password': ADMIN_PASSWORD,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


def test_rota_protegida_redireciona_sem_autenticacao(client):
    resp = client.get('/admin/respostas')

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_logout_redireciona_para_login(admin_client):
    resp = admin_client.get('/logout')

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_login_usuario_db_com_troca_obrigatoria_redireciona(client, db):
    user_hash = generate_password_hash('Default@1234')
    user_row = {
        'id': 1,
        'username': 'operador',
        'email': 'operador@test.com',
        'password_hash': user_hash,
        'must_change_password': True,
        'tenant_id': 1,
        'role': 'member',
        'is_active': 1,
    }
    setup_db(db, qresult(fetchone=user_row))

    resp = client.post('/login', data={
        'email': 'operador@test.com',
        'password': 'Default@1234',
    })

    assert resp.status_code == 302


def test_login_por_username_falha_limpo(client, db):
    """Submeter username sem @ não autentica — o caminho por username foi removido."""
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/login', data={
        'email': 'operador',
        'password': 'Default@1234',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'inválidos' in resp.data.decode()
```

- [ ] **Step 3: Rodar os testes para confirmar FAIL**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/test_auth.py -v
```

Esperado: a maioria FAIL — `test_login_admin_valido` falha porque a rota ainda lê `username`, não `email`.

- [ ] **Step 4: Substituir a rota `login()` em `app.py`**

Localizar a rota (linha ~369) e substituir o bloco completo:

```python
@app.route("/login", methods=["GET", "POST"])
def login():
    """
    Login de usuário
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: email
        type: string
        required: true
      - in: formData
        name: password
        type: string
        required: true
    responses:
      302:
        description: Redireciona para /admin/respostas (sucesso) ou reexibe form (falha)
      200:
        description: Página de login
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        user = None

        # TRANSITÓRIO (2D): bloco ADMIN_EMAIL sai quando signup criar DbUser tenant_admin
        admin_email = os.getenv("ADMIN_EMAIL", "").lower()
        if admin_email and email == admin_email:
            candidate = AdminUser()
            if candidate.check_password(password):
                user = candidate
        else:
            with engine.connect() as conn:
                row = repo.get_user_by_email_global(conn, email)
                if row and row.get("is_active"):
                    candidate = DbUser(
                        row["id"], row["username"], row["password_hash"],
                        row["must_change_password"], row["tenant_id"], row["role"],
                    )
                    if candidate.check_password(password):
                        user = candidate

        if user:
            login_user(user)
            logger.info(f"Login bem-sucedido: '{email}'.")
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("respostas"))

        logger.warning(f"Tentativa de login inválida: '{email}'.")
        flash("Email ou senha inválidos.", "danger")
    return render_template("login.html")
```

- [ ] **Step 5: Rodar os testes para confirmar PASS**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/test_auth.py -v
```

Esperado: todos os 8 testes PASS.

- [ ] **Step 6: Rodar suite completa para confirmar sem regressões**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/ -q
```

Esperado: todos passando (integration skipped).

- [ ] **Step 7: Commit**

```bash
git add backend/app.py backend/tests/conftest.py backend/tests/test_auth.py
git commit -m "feat(2B-1): login exclusivo por email — remove caminho de username"
```

---

### Task 2: Rota `forgot_password()` — email-only + test_password_reset.py

**Files:**
- Modify: `backend/app.py:440-498` (rota `forgot_password`)
- Modify: `backend/tests/test_password_reset.py` (atualizar 6 testes)

**Interfaces:**
- Consome: `repo.get_user_by_email_global(conn, email: str) -> dict | None` (Task 1, já existe)
- Produz: `POST /forgot_password` com campo `email` (era `identifier`)

- [ ] **Step 1: Atualizar os testes em `test_password_reset.py`**

Fazer as seguintes substituições e renomeações em `backend/tests/test_password_reset.py`:

**a) Renomear e atualizar `test_forgot_password_post_usuario_nao_encontrado_mostra_mensagem_generica`:**

```python
def test_forgot_password_post_email_nao_cadastrado_mostra_mensagem_generica(client, db):
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'ninguem@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o email' in body or 'email' in body.lower()
```

**b) Renomear e repropor `test_forgot_password_post_usuario_sem_email_mostra_mensagem_generica`:**

```python
def test_forgot_password_post_username_sem_arroba_nao_autentica(client, db):
    """Username sem @ não é email — route retorna mensagem genérica sem tocar no DB."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'joao'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'email' in resp.data.decode().lower()
```

**c) Atualizar `test_forgot_password_post_usuario_valido_envia_email`:**

```python
def test_forgot_password_post_usuario_valido_envia_email(client, db):
    user_row = {'id': 2, 'username': 'joao', 'password_hash': 'x',
                'must_change_password': False, 'email': 'joao@test.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'email': 'joao@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_email.assert_called_once()
    args = mock_email.call_args[0]
    assert args[0] == 'joao@test.com'
    assert args[1] == 'joao'
    assert '/reset_password/' in args[2]
```

**d) Atualizar `test_forgot_password_post_com_email_valido_envia_reset`** (campo `identifier` → `email`):

```python
def test_forgot_password_post_com_email_valido_envia_reset(client, db):
    """Enviar email existente no campo email → cria token e chama send_reset_email."""
    user_row = {'id': 3, 'username': 'ana', 'email': 'ana@test.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'email': 'ana@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_email.assert_called_once()
    args = mock_email.call_args[0]
    assert args[0] == 'ana@test.com'
    assert args[1] == 'ana'
    assert '/reset_password/' in args[2]
```

**e) Atualizar `test_forgot_password_post_com_email_case_insensitive`** (campo `identifier` → `email`):

```python
def test_forgot_password_post_com_email_case_insensitive(client, db):
    """Busca por email usa LOWER() — case-insensitive."""
    user_row = {'id': 4, 'username': 'carlos', 'email': 'carlos@gmail.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'email': 'Carlos@Gmail.com'})

    assert resp.status_code == 302
    mock_email.assert_called_once()
    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    assert 'lower' in first_call_sql.lower()
```

**f) Atualizar `test_forgot_password_post_email_inexistente_mensagem_generica`** (campo `identifier` → `email`):

```python
def test_forgot_password_post_email_inexistente_mensagem_generica(client, db):
    """Email não cadastrado → mensagem genérica (sem revelar inexistência)."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'naoexiste@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o email' in body or 'email' in body.lower()
```

- [ ] **Step 2: Rodar os testes para confirmar FAIL**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/test_password_reset.py -v -k "forgot_password"
```

Esperado: testes com `data={'email': ...}` falham porque a rota ainda lê `identifier`.

- [ ] **Step 3: Substituir a rota `forgot_password()` em `app.py`**

Localizar a rota (linha ~440) e substituir o bloco completo:

```python
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    """
    Solicitar redefinição de senha por email
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: email
        description: Endereço de email cadastrado
        type: string
        required: true
    responses:
      302:
        description: Sempre redireciona para /login com mensagem genérica
      200:
        description: Formulário de solicitação
    """
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        email_to_send = None
        username_to_send = None
        token_to_send = None

        with engine.connect() as conn:
            row = repo.get_user_by_email_global(conn, email)

            if row and row.get("email"):
                token = uuid.uuid4().hex
                expires = datetime.utcnow() + timedelta(hours=1)
                conn.execute(
                    text("""INSERT INTO password_reset_tokens
                            (user_id, token, expires_at) VALUES (:uid, :tok, :exp)"""),
                    {"uid": row["id"], "tok": token, "exp": expires},
                )
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                email_to_send = row["email"]
                username_to_send = row["username"]
                token_to_send = f"{base_url}/reset_password/{token}"

        if email_to_send:
            try:
                send_reset_email(email_to_send, username_to_send, token_to_send)
            except Exception as e:
                logger.error(f"Erro ao enviar email de reset: {e}")

        flash(
            "Se o email estiver cadastrado, você receberá um link de redefinição em breve.",
            "info",
        )
        return redirect(url_for("login"))

    return render_template("forgot_password.html")
```

- [ ] **Step 4: Rodar os testes para confirmar PASS**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/test_password_reset.py -v -k "forgot_password"
```

Esperado: todos os testes de `forgot_password` PASS.

- [ ] **Step 5: Rodar suite completa**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/ -q
```

Esperado: todos passando (integration skipped).

- [ ] **Step 6: Commit**

```bash
git add backend/app.py backend/tests/test_password_reset.py
git commit -m "feat(2B-2): forgot_password email-only — remove detecção por @ e caminho de username"
```

---

### Task 3: Templates + `.env.example`

**Files:**
- Modify: `backend/templates/login.html`
- Modify: `backend/templates/forgot_password.html`
- Modify: `.env.example`

**Interfaces:**
- Consome: campo `name="email"` esperado pela rota `login()` (Task 1)
- Consome: campo `name="email"` esperado pela rota `forgot_password()` (Task 2)

- [ ] **Step 1: Atualizar `login.html`**

Substituir o conteúdo completo de `backend/templates/login.html`:

```html
<!-- backend/templates/login.html -->

{% extends "base.html" %}
{% block title %}Comemore+ - Login{% endblock %}

{% block content %}
<style>
  body {
    background: linear-gradient(to right, #fce4ec, #e3f2fd);
  }
  .login-header {
    font-weight: 700;
    font-size: 2rem;
    color: #2c3e50;
    margin-bottom: 20px;
  }
  .login-box {
    background: #ffffff;
    padding: 30px;
    border-radius: 16px;
    box-shadow: 0 8px 30px rgba(0, 0, 0, 0.1);
    width: 100%;
    max-width: 400px;
  }
  .form-label {
    font-weight: 500;
  }
  .btn-login {
    background: #1976d2;
    color: white;
    font-weight: 600;
  }
  .btn-login:hover {
    background: #1565c0;
  }
  .footer-version {
    margin-top: 20px;
    font-size: 0.9rem;
    color: #666;
  }
</style>

<div class="container d-flex flex-column align-items-center justify-content-center" style="min-height: 90vh;">
  <h1 class="login-header">Comemore+</h1>

  <div class="login-box">
    <h4 class="mb-4 text-center">Área do Anfitrião</h4>

    <form method="POST" action="{{ url_for('login') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="mb-3">
        <label class="form-label">Email</label>
        <input type="email" name="email" class="form-control" required autofocus>
      </div>
      <div class="mb-3">
        <label class="form-label">Senha</label>
        <input type="password" name="password" class="form-control" required>
      </div>
      <div class="d-grid">
        <button type="submit" class="btn btn-login">Entrar</button>
      </div>
      <div class="text-center mt-3">
        <a href="{{ url_for('forgot_password') }}" class="text-muted small">
          Esqueci minha senha
        </a>
      </div>
    </form>
  </div>

  <div class="footer-version text-center">
    {{ app_version }}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 2: Atualizar `forgot_password.html`**

Substituir o conteúdo completo de `backend/templates/forgot_password.html`:

```html
<!-- backend/templates/forgot_password.html -->
{% extends "base.html" %}
{% block title %}Comemore+ - Esqueci minha senha{% endblock %}

{% block content %}
<style>
  body { background: linear-gradient(to right, #fce4ec, #e3f2fd); }
  .card-box {
    background: #fff; padding: 30px; border-radius: 16px;
    box-shadow: 0 8px 30px rgba(0,0,0,0.1); width: 100%; max-width: 400px;
  }
  .btn-primary-custom { background: #1976d2; color: white; font-weight: 600; }
  .btn-primary-custom:hover { background: #1565c0; color: white; }
</style>

<div class="container d-flex flex-column align-items-center justify-content-center"
     style="min-height: 90vh;">
  <h1 style="font-weight:700;font-size:2rem;color:#2c3e50;margin-bottom:20px;">
    Comemore+
  </h1>

  <div class="card-box">
    <h4 class="mb-1 text-center">Esqueci minha senha</h4>
    <p class="text-muted text-center small mb-4">
      Informe seu email e enviaremos um link de redefinição para a sua conta.
    </p>

    <form method="POST" action="{{ url_for('forgot_password') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="mb-3">
        <label class="form-label">Email</label>
        <input type="email" name="email" class="form-control" required autofocus
               placeholder="Seu endereço de email">
      </div>
      <div class="d-grid mb-3">
        <button type="submit" class="btn btn-primary-custom">Enviar link</button>
      </div>
      <div class="text-center">
        <a href="{{ url_for('login') }}" class="text-muted small">← Voltar ao login</a>
      </div>
    </form>
  </div>

  <div class="mt-3 text-muted small">{{ app_version }}</div>
</div>
{% endblock %}
```

- [ ] **Step 3: Adicionar `ADMIN_EMAIL` ao `.env.example`**

No arquivo `.env.example`, adicionar após a linha `ADMIN_PASS=`:

```
ADMIN_EMAIL=admin@seu-dominio.com
```

O bloco completo do admin fica:

```
# Admin (super usuário)
# ADMIN_PASS deve ser o hash bcrypt gerado com generate_password_hash() do Werkzeug
# Exemplo para gerar: python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('sua_senha'))"
ADMIN_USER=admin
ADMIN_PASS=
ADMIN_EMAIL=admin@seu-dominio.com
```

- [ ] **Step 4: Rodar suite completa para confirmar sem regressões**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python3 -m pytest tests/ -q
```

Esperado: todos passando (integration skipped).

- [ ] **Step 5: Commit**

```bash
git add backend/templates/login.html backend/templates/forgot_password.html .env.example
git commit -m "feat(2B-3): templates login e forgot_password com type=email — remove campo username"
```
