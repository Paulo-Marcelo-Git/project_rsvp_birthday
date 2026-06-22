# Design Spec: Reset de Senha por Usuário ou Email

**Data:** 2026-06-22  
**Status:** Aprovado  
**Escopo:** `backend/app.py`, `backend/templates/forgot_password.html`

---

## Problema

O fluxo de "Esqueci minha senha" aceita apenas o campo `username`. O usuário não consegue solicitar o reset digitando seu endereço de email — o que é uma expectativa comum e uma limitação em sistemas onde o usuário não lembra o username.

## Objetivo

Permitir que o usuário solicite o reset de senha digitando **username ou email** em um único campo inteligente na tela `/forgot_password`.

---

## Decisões de Design

| Decisão | Escolha | Motivo |
|---|---|---|
| UI do campo | Campo único com detecção automática | Menos atrito que dois campos separados |
| Detecção de tipo | Presença de `@` no input | Padrão da indústria, simples e sem ambiguidade |
| Admin principal | Fora do escopo | Admin gerencia senha via env var na VPS |
| Unicidade de email | Adicionar UNIQUE constraint em `users.email` | Email é identificador; duplicatas quebram o fluxo de reset |
| Emails duplicados em produção | Migração com try/except + warning | Não quebra deploy; loga alerta para o operador |

---

## Arquitetura

Nenhuma nova tabela ou rota. Alterações cirúrgicas em dois arquivos existentes.

### Migração de banco (`init_db()`)

Adicionar helper `_index_exists(conn, table, index_name)` logo abaixo do `_col_exists` existente em `app.py`:

```python
def _index_exists(conn, table: str, index_name: str) -> bool:
    row = conn.execute(text("""
        SELECT COUNT(*) as cnt FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name   = :t
          AND index_name   = :i
    """), {"t": table, "i": index_name}).mappings().fetchone()
    return bool(row["cnt"])
```

Aplicar a migração dentro de `init_db()`:

```python
if not _index_exists(conn, "users", "idx_users_email_unique"):
    try:
        conn.execute(text(
            "ALTER TABLE users ADD UNIQUE INDEX idx_users_email_unique (email)"
        ))
        conn.commit()
    except Exception as e:
        logger.warning(f"Não foi possível adicionar UNIQUE em users.email: {e}")
```

### Rota `forgot_password` (`app.py`)

**Campo recebido:** `identifier` (renomear de `username`)

**Lógica de detecção e busca:**

```python
identifier = request.form.get("identifier", "").strip()

if "@" in identifier:
    query = text("""SELECT id, username, email FROM users
                    WHERE LOWER(email) = LOWER(:id)""")
else:
    query = text("""SELECT id, username, email FROM users
                    WHERE username = :id""")

row = conn.execute(query, {"id": identifier}).mappings().fetchone()
```

O restante do fluxo (criação de token em `password_reset_tokens`, envio via `send_reset_email`, mensagem genérica ao usuário) permanece sem alteração.

**Docstring Swagger:** atualizar o parâmetro de `username` para `identifier` com descrição `"Nome de usuário ou endereço de email"`.

### Template `forgot_password.html`

```html
<!-- Antes -->
<label class="form-label">Usuário</label>
<input type="text" name="username" ...>

<!-- Depois -->
<label class="form-label">Usuário ou email</label>
<input type="text" name="identifier" ...
       placeholder="Seu usuário ou endereço de email">
```

Texto de instrução atualizado:  
*"Informe seu usuário ou email e enviaremos um link de redefinição para a sua conta."*

---

## Fora do Escopo

- Rota `reset_password` — sem alterações
- Template `login.html` — sem alterações
- `AdminUser` — reset não se aplica; credenciais via env var
- Reforço de unicidade no formulário de criação/edição de usuário — já funciona via constraint do banco

---

## Critérios de Sucesso

1. Digitar o **username** correto → link de reset chega no email cadastrado
2. Digitar o **email** correto → link de reset chega nesse email
3. Digitar username ou email inexistente → mesma mensagem genérica (sem revelar se existe)
4. Banco de produção com ou sem emails duplicados → deploy não quebra

---

## Testes a Cobrir

- `POST /forgot_password` com username válido (com email cadastrado)
- `POST /forgot_password` com email válido
- `POST /forgot_password` com username sem email cadastrado
- `POST /forgot_password` com identifier inexistente
- `POST /forgot_password` com email em case diferente (ex: `User@Gmail.com`)
