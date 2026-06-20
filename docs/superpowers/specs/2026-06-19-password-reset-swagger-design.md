# Design Spec: Reset de Senha Self-Service + Swagger

**Data:** 2026-06-19
**Status:** Aprovado

---

## 1. Contexto e Objetivo

O sistema Comemore+ possui sub-usuários (`DbUser`) criados pelo admin. Atualmente, quando um sub-usuário esquece a senha, só o admin consegue resetá-la pelo painel. O objetivo desta feature é permitir que o próprio usuário redefina sua senha de forma autônoma, sem depender do admin.

Em paralelo, será adicionada documentação Swagger de todas as APIs do projeto via Flasgger.

---

## 2. Escopo

### Incluído
- Fluxo completo de reset de senha por link de email
- Campos `email` (obrigatório) e `whatsapp` (opcional) na tabela `users`
- Email obrigatório ao criar novo sub-usuário no painel admin
- Nova tabela `password_reset_tokens`
- Documentação Swagger de todas as rotas existentes e novas
- UI do Swagger protegida por login de super admin

### Excluído
- Reset via WhatsApp (pode ser adicionado futuramente)
- Rate limiting no endpoint de forgot_password
- Notificação por email ao criar usuário

---

## 3. Banco de Dados

### 3.1 Alterações na tabela `users`

Duas colunas adicionadas via migração incremental com `_col_exists()`:

```sql
ALTER TABLE users ADD COLUMN email    VARCHAR(255) NULL;
ALTER TABLE users ADD COLUMN whatsapp VARCHAR(30)  NULL;
```

- `email`: obrigatório no formulário de criação (validado no backend), NULL permitido no banco para compatibilidade com usuários existentes
- `whatsapp`: opcional, sem validação de formato por ora

### 3.2 Nova tabela `password_reset_tokens`

Criada em `init_db()`:

```sql
CREATE TABLE IF NOT EXISTS password_reset_tokens (
  id         INT AUTO_INCREMENT PRIMARY KEY,
  user_id    INT NOT NULL,
  token      VARCHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME NOT NULL,
  used       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_prt_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

**Propriedades do token:**
- Gerado via `uuid4().hex` (32 chars, 128 bits de entropia)
- Válido por 1 hora (`expires_at = NOW() + 1h`)
- Single-use: `used = TRUE` após primeiro uso
- Tokens expirados/usados não são deletados automaticamente (cleanup pode ser adicionado futuramente)

---

## 4. Configuração — Variáveis de Ambiente

Novas variáveis adicionadas ao `.env.example`:

```env
# Email (SMTP) — necessário para reset de senha self-service
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=true
MAIL_USERNAME=seu_email@gmail.com
MAIL_PASSWORD=xxxx xxxx xxxx xxxx
MAIL_FROM=Comemore+ <seu_email@gmail.com>
APP_BASE_URL=https://seu-dominio.com
```

**Comportamento sem SMTP configurado:** se `MAIL_SERVER` não estiver definido, o sistema loga um aviso (`logger.warning`) mas não lança exceção. O token é gerado e salvo no banco, mas o email não é enviado — útil para desenvolvimento local.

---

## 5. Novas Rotas

### 5.1 `GET /forgot_password`
Exibe formulário com campo `username`.

### 5.2 `POST /forgot_password`
- Recebe `username` via form
- Busca usuário no banco
- **Se não encontrado ou sem email:** exibe mensagem genérica (não revela se usuário existe)
- **Se encontrado com email:**
  1. Gera token `uuid4().hex`
  2. Salva em `password_reset_tokens` com `expires_at = NOW() + 1h`
  3. Chama `send_reset_email(to_address, reset_url)`
  4. Redireciona para `/login` com flash de instrução genérica
- Rota isenta de `@login_required`
- CSRF protegido (token no form)

### 5.3 `GET /reset_password/<token>`
- Valida token: existe + `used=FALSE` + `expires_at > NOW()`
- **Inválido/expirado:** flash de erro → redirect `/forgot_password`
- **Válido:** exibe formulário de nova senha

### 5.4 `POST /reset_password/<token>`
- Revalida token (mesmas condições)
- Valida senha:
  - Mínimo 8 caracteres
  - Diferente de `DEFAULT_PASSWORD`
  - Confirmação coincide
- Atualiza `password_hash` e `must_change_password=FALSE` na tabela `users`
- Marca token `used=TRUE`
- Flash de sucesso → redirect `/login`
- Rota isenta de `@login_required`

---

## 6. Função de Envio de Email

```python
def send_reset_email(to_address: str, reset_url: str) -> None:
    # usa smtplib + email.mime — sem dependência externa
    # loga warning e retorna sem erro se MAIL_SERVER não configurado
```

Usa `smtplib.SMTP` com `starttls()`. O template do email é texto simples + HTML básico com o link de reset.

---

## 7. Alterações no Painel Admin

### 7.1 Formulário "Adicionar usuário" (`/admin/usuarios`)
- Novo campo `email` (obrigatório no frontend e backend)
- Novo campo `whatsapp` (opcional)
- Backend: valida presença de email antes do INSERT; retorna flash de erro se ausente

### 7.2 Formulário "Editar usuário" (`/admin/usuarios/<id>/edit`)
- Exibe campos `email` (obrigatório) e `whatsapp` (opcional) preenchidos com valores atuais
- Backend: valida email antes do UPDATE

### 7.3 Listagem de usuários
- Tabela exibe colunas `email` e `whatsapp`

---

## 8. Swagger / Documentação das APIs

### 8.1 Dependência
```
flasgger==0.9.7
```
Adicionado ao `requirements.txt`.

### 8.2 Inicialização
```python
from flasgger import Swagger
swagger = Swagger(app, config={...})
```
Configuração inclui `title`, `version`, `securityDefinitions` (session cookie).

### 8.3 Proteção
A rota `/apidocs` é protegida via `before_request`: redireciona para `/login` se não autenticado como super admin.

### 8.4 Rotas documentadas

| Grupo | Rotas |
|-------|-------|
| Auth | `POST /login`, `GET /logout`, `GET/POST /change_password`, `GET/POST /forgot_password`, `GET/POST /reset_password/<token>` |
| Convite | `GET/POST /invite/<token>` |
| Respostas | `GET /admin/respostas`, `GET /admin/exportar_xlsx` |
| Convidados | `POST /admin/convidados/add`, `POST /admin/convidados/<id>/edit`, `POST /admin/convidados/<id>/delete` |
| Textos | `POST /admin/textos` |
| Usuários | `GET /admin/usuarios`, `POST /admin/usuarios/add`, `POST /admin/usuarios/<id>/edit`, `POST /admin/usuarios/<id>/reset_senha`, `POST /admin/usuarios/<id>/delete` |

Cada rota documenta: descrição, parâmetros de path/query, corpo do form, responses (200, 302, 400, 403, 404).

Docstrings YAML inline nos decoradores de rota (padrão Flasgger).

---

## 9. Templates HTML Novos

- `forgot_password.html` — formulário de username, link de volta para login
- `reset_password.html` — formulário de nova senha + confirmação

Ambos estendem `base.html`, seguem o estilo visual de `login.html` (card centralizado, gradiente de fundo).

---

## 10. Fluxo Completo (Diagrama)

```
/login
  └─ "Esqueci minha senha" → GET /forgot_password
       └─ POST /forgot_password (username)
            ├─ Não encontrado/sem email → flash genérico → /login
            └─ Encontrado → gera token → salva DB → envia email
                 └─ Email: link /reset_password/<token>
                      ├─ Token inválido/expirado → flash erro → /forgot_password
                      └─ Token válido → GET /reset_password/<token>
                           └─ POST /reset_password/<token> (nova senha)
                                ├─ Validação falha → flash erro → mesmo form
                                └─ Sucesso → atualiza senha → token used=TRUE → /login
```

---

## 11. Segurança

- Token com 128 bits de entropia (uuid4 hex) — resistente a brute force
- Expiração de 1 hora
- Single-use
- Mensagem genérica no POST `/forgot_password` (não revela existência de username)
- CSRF em todos os formulários
- `/apidocs` restrito a super admin

---

## 12. Arquivos Afetados

| Arquivo | Mudança |
|---------|---------|
| `backend/app.py` | Novas rotas, `init_db()`, `send_reset_email()`, Swagger config, docstrings |
| `backend/requirements.txt` | + `flasgger==0.9.7` |
| `backend/templates/login.html` | Link "Esqueci minha senha" |
| `backend/templates/forgot_password.html` | Novo |
| `backend/templates/reset_password.html` | Novo |
| `backend/templates/admin_users.html` | Campos email/whatsapp |
| `.env.example` | Novas variáveis MAIL_* e APP_BASE_URL |
