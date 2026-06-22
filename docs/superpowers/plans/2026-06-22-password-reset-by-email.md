# Password Reset por Usuário ou Email — Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que sub-usuários solicitem reset de senha digitando username **ou** email em um único campo na tela `/forgot_password`.

**Architecture:** Detecção automática por `@` no input — se contiver `@`, busca por `LOWER(email)`; caso contrário, busca por `username`. Adiciona `UNIQUE INDEX` em `users.email` via migração incremental com try/except para não quebrar deploys com dados legados. Nenhuma nova rota ou tabela.

**Tech Stack:** Python 3.12, Flask 3.0, SQLAlchemy 2.0 `text()`, pytest + MagicMock, Jinja2.

## Global Constraints

- Todo SQL usa `text()` do SQLAlchemy com parâmetros nomeados — sem concatenação de strings.
- Padrão de migração incremental: checar existência antes de alterar (`_col_exists` / `_index_exists`).
- Mensagem de resposta ao usuário deve ser **sempre a mesma** independentemente do resultado — evita enumeração de usuários.
- Testes usam o padrão `qresult()` / `setup_db()` definido em `backend/tests/conftest.py`.
- Arquivo de testes relevante: `backend/tests/test_password_reset.py`.
- Admin principal (`AdminUser`) está fora do escopo — sem alterações.

---

### Task 1: Adicionar `_index_exists` e migração UNIQUE em `users.email`

**Files:**
- Modify: `backend/app.py:96-152`
- Modify: `backend/tests/test_password_reset.py` (adicionar 2 testes)

**Interfaces:**
- Produz: `_index_exists(conn, table: str, index_name: str) -> bool` — usada internamente por `init_db()`

- [ ] **Step 1: Escrever os testes para `_index_exists`**

Adicionar ao **final** de `backend/tests/test_password_reset.py`:

```python
def test_index_exists_retorna_true_quando_indice_existe():
    """_index_exists deve retornar True quando o índice existe no information_schema."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 1
    assert _app._index_exists(conn, 'users', 'idx_users_email_unique') is True


def test_index_exists_retorna_false_quando_indice_nao_existe():
    """_index_exists deve retornar False quando o índice não existe."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 0
    assert _app._index_exists(conn, 'users', 'idx_users_email_unique') is False
```

- [ ] **Step 2: Rodar os testes para confirmar FAIL**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/test_password_reset.py::test_index_exists_retorna_true_quando_indice_existe tests/test_password_reset.py::test_index_exists_retorna_false_quando_indice_nao_existe -v
```

Esperado: `FAILED` — `AttributeError: module 'app' has no attribute '_index_exists'`

- [ ] **Step 3: Adicionar `_index_exists` em `app.py` logo após `_col_exists`**

Em `backend/app.py`, após a função `_col_exists` (linha ~101), inserir:

```python
def _index_exists(conn, table: str, index_name: str) -> bool:
    count = conn.execute(text("""
        SELECT COUNT(*) FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name   = :t
          AND index_name   = :i
    """), {"t": table, "i": index_name}).scalar()
    return bool(count)
```

- [ ] **Step 4: Adicionar migração UNIQUE em `init_db()` em `app.py`**

Dentro de `init_db()`, após o bloco que adiciona `whatsapp` (linha ~137) e antes do comentário `# Tabela de tokens de reset de senha`, inserir:

```python
                # Migração: UNIQUE INDEX em users.email
                if not _index_exists(conn, "users", "idx_users_email_unique"):
                    try:
                        conn.execute(text(
                            "ALTER TABLE users ADD UNIQUE INDEX idx_users_email_unique (email)"
                        ))
                    except Exception as e:
                        logger.warning(
                            f"Não foi possível adicionar UNIQUE em users.email: {e}"
                        )
```

- [ ] **Step 5: Rodar os testes para confirmar PASS**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/test_password_reset.py::test_index_exists_retorna_true_quando_indice_existe tests/test_password_reset.py::test_index_exists_retorna_false_quando_indice_nao_existe -v
```

Esperado: `2 passed`

- [ ] **Step 6: Rodar a suite completa para confirmar sem regressões**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/ -v
```

Esperado: todos passando (nenhum novo FAIL).

- [ ] **Step 7: Commit**

```bash
git add backend/app.py backend/tests/test_password_reset.py
git commit -m "feat: adiciona _index_exists e migração UNIQUE em users.email"
```

---

### Task 2: Atualizar rota `forgot_password` para aceitar username ou email

**Files:**
- Modify: `backend/app.py:448-502`
- Modify: `backend/tests/test_password_reset.py` (atualizar 3 testes + adicionar 3 novos)

**Interfaces:**
- Consome: `_index_exists` (Task 1, já existente)
- Produz: `POST /forgot_password` com campo `identifier` (antes `username`)

- [ ] **Step 1: Atualizar os testes existentes que usam `username=`**

Em `backend/tests/test_password_reset.py`, fazer exatamente 3 substituições de string:

| Linha (aprox.) | De | Para |
|---|---|---|
| ~75 | `data={'username': 'ninguem'}` | `data={'identifier': 'ninguem'}` |
| ~89 | `data={'username': 'maria'}` | `data={'identifier': 'maria'}` |
| ~105 | `data={'username': 'joao'}` | `data={'identifier': 'joao'}` |

Verificar com:
```bash
grep -n "username" backend/tests/test_password_reset.py
```
Esperado: zero ocorrências de `data={'username':` após as substituições.

- [ ] **Step 2: Adicionar os 3 novos testes ao final de `test_password_reset.py`**

```python
def test_forgot_password_post_com_email_valido_envia_reset(client, db):
    """Enviar email existente no campo identifier → cria token e chama send_reset_email."""
    user_row = {'id': 3, 'username': 'ana', 'email': 'ana@test.com'}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),  # SELECT by email
        MagicMock(),                  # INSERT token
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'identifier': 'ana@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_email.assert_called_once()
    args = mock_email.call_args[0]
    assert args[0] == 'ana@test.com'
    assert args[1] == 'ana'
    assert '/reset_password/' in args[2]


def test_forgot_password_post_com_email_case_insensitive(client, db):
    """Busca por email deve usar LOWER() — case-insensitive."""
    user_row = {'id': 4, 'username': 'carlos', 'email': 'carlos@gmail.com'}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'identifier': 'Carlos@Gmail.com'})

    assert resp.status_code == 302
    mock_email.assert_called_once()
    # Verifica que a SQL executada contém LOWER
    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    assert 'lower' in first_call_sql.lower()


def test_forgot_password_post_email_inexistente_mensagem_generica(client, db):
    """Email não cadastrado → mesma mensagem genérica (sem revelar inexistência)."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'identifier': 'naoexiste@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o usuário existir' in body or 'email' in body.lower()
```

- [ ] **Step 3: Rodar os testes para confirmar FAIL**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/test_password_reset.py -v -k "forgot_password"
```

Esperado: testes com `identifier` falhando, testes com `username` ainda passando.

- [ ] **Step 4: Atualizar a rota `forgot_password` em `app.py`**

Substituir o bloco completo da rota (linhas ~448-502). A docstring muda o parâmetro; o corpo muda o campo e a query:

```python
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    """
    Solicitar redefinição de senha por username ou email
    ---
    tags: [Auth]
    parameters:
      - in: formData
        name: identifier
        description: Nome de usuário ou endereço de email
        type: string
        required: true
    responses:
      302:
        description: Sempre redireciona para /login com mensagem genérica
      200:
        description: Formulário de solicitação
    """
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        email_to_send = None
        username_to_send = None
        token_to_send = None

        with engine.connect() as conn:
            if "@" in identifier:
                query = text("""SELECT id, username, email FROM users
                                WHERE LOWER(email) = LOWER(:id)""")
            else:
                query = text("""SELECT id, username, email FROM users
                                WHERE username = :id""")
            row = conn.execute(query, {"id": identifier}).mappings().fetchone()

            if row and row['email']:
                token = uuid.uuid4().hex
                expires = datetime.utcnow() + timedelta(hours=1)
                conn.execute(
                    text("""INSERT INTO password_reset_tokens
                            (user_id, token, expires_at) VALUES (:uid, :tok, :exp)"""),
                    {"uid": row['id'], "tok": token, "exp": expires}
                )
                conn.commit()
                base_url = os.getenv("APP_BASE_URL", request.host_url.rstrip("/"))
                email_to_send = row['email']
                username_to_send = row['username']
                token_to_send = f"{base_url}/reset_password/{token}"

        if email_to_send:
            try:
                send_reset_email(email_to_send, username_to_send, token_to_send)
            except Exception as e:
                logger.error(f"Erro ao enviar email de reset: {e}")

        flash("Se o usuário existir e tiver email cadastrado, "
              "você receberá um link de redefinição em breve.", "info")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")
```

- [ ] **Step 5: Rodar os testes para confirmar PASS**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/test_password_reset.py -v -k "forgot_password"
```

Esperado: todos os testes de `forgot_password` passando.

- [ ] **Step 6: Rodar suite completa para confirmar sem regressões**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/ -v
```

Esperado: todos passando.

- [ ] **Step 7: Commit**

```bash
git add backend/app.py backend/tests/test_password_reset.py
git commit -m "feat: forgot_password aceita username ou email no campo identifier"
```

---

### Task 3: Atualizar template `forgot_password.html`

**Files:**
- Modify: `backend/templates/forgot_password.html`

**Interfaces:**
- Consome: campo `name="identifier"` esperado pela rota (Task 2)

- [ ] **Step 1: Atualizar `forgot_password.html`**

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
      Informe seu usuário ou email e enviaremos um link de redefinição para a sua conta.
    </p>

    <form method="POST" action="{{ url_for('forgot_password') }}">
      <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
      <div class="mb-3">
        <label class="form-label">Usuário ou email</label>
        <input type="text" name="identifier" class="form-control" required autofocus
               placeholder="Seu usuário ou endereço de email">
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

- [ ] **Step 2: Rodar os testes de página para confirmar sem regressões**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/test_password_reset.py::test_forgot_password_page_carrega -v
```

Esperado: `1 passed`

- [ ] **Step 3: Rodar suite completa**

```bash
cd /mnt/c/SRC/GIT/project_rsvp_birthday/backend
python -m pytest tests/ -v
```

Esperado: todos passando.

- [ ] **Step 4: Commit**

```bash
git add backend/templates/forgot_password.html
git commit -m "feat: atualiza template forgot_password com campo identifier (usuário ou email)"
```
