"""
Camada de repositório do Comemore+.

REGRA: toda função que toca dado multi-tenant recebe `tenant_id` como
primeiro argumento (após `conn`). Nenhuma rota monta SQL de invitees/
events/users diretamente — tudo passa por aqui.

Aliases de compatibilidade nos SELECTs:
  observation  AS custom_message   — nome antigo usado nos templates
  responded_at AS response_date    — nome antigo usado nos templates
Permite refatorar o banco sem alterar templates durante a transição.
"""
import json

from sqlalchemy import text


# ── helpers internos ──────────────────────────────────────────────────────────

def _extra_where(owner_user_id, search, table_alias="i"):
    """
    Retorna (extra_sql_str, params_dict) para filtros opcionais de owner e busca.
    tenant_id já é filtrado pelo caller — não duplicar aqui.
    """
    clauses = []
    params = {}
    if owner_user_id is not None:
        clauses.append("e.owner_user_id = :owner_user_id")
        params["owner_user_id"] = owner_user_id
    if search:
        clauses.append(f"{table_alias}.name LIKE :search")
        params["search"] = f"%{search}%"
    extra = (" AND " + " AND ".join(clauses)) if clauses else ""
    return extra, params


# ── sem tenant_id (identificadores globalmente únicos) ────────────────────────

def get_invitee_by_token(conn, token: str) -> dict | None:
    """Busca convidado pelo token público (globalmente único)."""
    row = conn.execute(
        text("""
            SELECT i.id, i.event_id, i.tenant_id, i.name, i.token,
                   i.response,
                   i.observation  AS custom_message,
                   i.responded_at AS response_date,
                   i.media_url,
                   i.phone, i.email,
                   i.created_at
            FROM invitees i
            WHERE i.token = :token
        """),
        {"token": token},
    ).mappings().fetchone()
    return dict(row) if row else None


def get_valid_reset_token(conn, token: str) -> dict | None:
    """Retorna token de reset se válido (não usado, não expirado)."""
    row = conn.execute(
        text("""
            SELECT id, user_id
            FROM password_reset_tokens
            WHERE token = :tok
              AND used = FALSE
              AND expires_at > UTC_TIMESTAMP()
        """),
        {"tok": token},
    ).mappings().fetchone()
    return dict(row) if row else None


def create_tenant(conn, name: str) -> int:
    """Cria um novo tenant e retorna o tenant_id gerado."""
    conn.execute(
        text("INSERT INTO tenants (name) VALUES (:name)"),
        {"name": name},
    )
    row = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().fetchone()
    return int(row["id"])


# ── eventos ───────────────────────────────────────────────────────────────────

def get_default_event_id(conn, tenant_id: int) -> int:
    """Retorna o id do primeiro evento publicado do tenant."""
    row = conn.execute(
        text("""
            SELECT id FROM events
            WHERE tenant_id = :tid AND status = 'published'
            ORDER BY id LIMIT 1
        """),
        {"tid": tenant_id},
    ).mappings().fetchone()
    if not row:
        raise RuntimeError(f"Tenant {tenant_id} não tem evento publicado.")
    return int(row["id"])


def get_event_texts(conn, tenant_id: int, event_id: int) -> dict:
    """
    Retorna textos do evento para renderizar templates de convite e configuração.
    post_yes_text e post_no_text ficam em extra_texts (JSON).
    """
    row = conn.execute(
        text("""
            SELECT question_text, yes_text, no_text, extra_texts
            FROM events
            WHERE id = :eid AND tenant_id = :tid
        """),
        {"eid": event_id, "tid": tenant_id},
    ).mappings().fetchone()
    if not row:
        return {}
    extra = json.loads(row["extra_texts"]) if row["extra_texts"] else {}
    return {
        "question_text":  row["question_text"] or "",
        "yes_text":       row["yes_text"]       or "",
        "no_text":        row["no_text"]        or "",
        "post_yes_text":  extra.get("post_yes_text", ""),
        "post_no_text":   extra.get("post_no_text",  ""),
    }


def update_event_texts(conn, tenant_id: int, event_id: int, **texts) -> None:
    """
    Atualiza textos do evento.
    Chaves válidas: question_text, yes_text, no_text, post_yes_text, post_no_text.
    """
    row = conn.execute(
        text("SELECT extra_texts FROM events WHERE id = :eid AND tenant_id = :tid"),
        {"eid": event_id, "tid": tenant_id},
    ).mappings().fetchone()
    if not row:
        return

    extra = json.loads(row["extra_texts"]) if row["extra_texts"] else {}
    set_parts = []
    params = {"eid": event_id, "tid": tenant_id}

    for key in ("question_text", "yes_text", "no_text"):
        if key in texts:
            set_parts.append(f"{key} = :{key}")
            params[key] = texts[key]

    for key in ("post_yes_text", "post_no_text"):
        if key in texts:
            extra[key] = texts[key]

    set_parts.append("extra_texts = :extra_texts")
    params["extra_texts"] = json.dumps(extra, ensure_ascii=False)

    if set_parts:
        conn.execute(
            text(
                f"UPDATE events SET {', '.join(set_parts)} "
                "WHERE id = :eid AND tenant_id = :tid"
            ),
            params,
        )


def create_default_event(
    conn, tenant_id: int, tenant_name: str, *, owner_user_id: int | None = None
) -> int:
    """Cria o evento padrão para um novo tenant (usado no signup). Retorna event_id."""
    import secrets as _sec
    slug = _sec.token_urlsafe(16)[:22]
    extra = json.dumps(
        {"post_yes_text": "Que bom! Te esperamos!", "post_no_text": "Sentiremos sua falta."},
        ensure_ascii=False,
    )
    conn.execute(
        text("""
            INSERT INTO events
                (tenant_id, owner_user_id, title, event_type, slug, status,
                 question_text, yes_text, no_text, extra_texts)
            VALUES
                (:tid, :owner, :title, 'aniversario', :slug, 'draft',
                 'Você vai comparecer?', 'Sim ✅', 'Não ❌', :extra)
        """),
        {
            "tid": tenant_id, "owner": owner_user_id,
            "title": f"Festa de {tenant_name}", "slug": slug, "extra": extra,
        },
    )
    row = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().fetchone()
    return int(row["id"])


# ── invitees ──────────────────────────────────────────────────────────────────

def get_invitees(
    conn,
    tenant_id: int,
    *,
    owner_user_id: int | None = None,
    search: str = "",
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Lista convidados do tenant com aliases de compatibilidade.
    Se owner_user_id: filtra pelos eventos desse usuário (visão de member).
    SEMPRE filtra tenant_id.
    """
    extra, params = _extra_where(owner_user_id, search)
    params.update({"tid": tenant_id, "limit": limit, "offset": offset})

    rows = conn.execute(
        text(f"""
            SELECT i.id, i.name, i.token, i.response,
                   i.observation  AS custom_message,
                   i.responded_at AS response_date,
                   i.media_url,
                   i.phone, i.email,
                   i.event_id, i.tenant_id,
                   COALESCE(u.username, '(admin)') AS owner_username
            FROM invitees i
            JOIN  events e ON i.event_id = e.id
            LEFT JOIN users u ON e.owner_user_id = u.id
            WHERE i.tenant_id = :tid{extra}
            ORDER BY i.responded_at IS NULL DESC, i.responded_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


def count_invitees_by_response(
    conn,
    tenant_id: int,
    *,
    owner_user_id: int | None = None,
    search: str = "",
) -> dict:
    """Retorna {total, total_sim, total_nao, total_aguardando}."""
    extra, params = _extra_where(owner_user_id, search)
    params["tid"] = tenant_id

    row = conn.execute(
        text(f"""
            SELECT
                COUNT(*)                        AS total,
                SUM(i.response = 'yes')         AS total_sim,
                SUM(i.response = 'no')          AS total_nao,
                SUM(i.response = 'pending')     AS total_aguardando
            FROM invitees i
            JOIN events e ON i.event_id = e.id
            WHERE i.tenant_id = :tid{extra}
        """),
        params,
    ).mappings().fetchone()
    return {
        "total":            int(row["total"]            or 0),
        "total_sim":        int(row["total_sim"]        or 0),
        "total_nao":        int(row["total_nao"]        or 0),
        "total_aguardando": int(row["total_aguardando"] or 0),
    }


def add_invitee(
    conn,
    tenant_id: int,
    event_id: int,
    name: str,
    token: str,
    *,
    phone: str | None = None,
    email: str | None = None,
    observation: str | None = None,
    media_url: str | None = None,
) -> None:
    """Insere convidado SEMPRE com tenant_id e event_id."""
    conn.execute(
        text("""
            INSERT INTO invitees
                (event_id, tenant_id, name, token, phone, email, observation, media_url)
            VALUES
                (:eid, :tid, :name, :token, :phone, :email, :obs, :media_url)
        """),
        {
            "eid": event_id, "tid": tenant_id,
            "name": name, "token": token,
            "phone": phone, "email": email,
            "obs": observation, "media_url": media_url,
        },
    )


def get_invitee(conn, tenant_id: int, invitee_id: int) -> dict | None:
    """
    Busca convidado por id. SEMPRE filtra tenant_id.
    Inclui event_owner_user_id para que as rotas verifiquem permissão de edição
    sem query adicional.
    """
    row = conn.execute(
        text("""
            SELECT i.id, i.name, i.token, i.response,
                   i.observation  AS custom_message,
                   i.responded_at AS response_date,
                   i.media_url,
                   i.phone, i.email,
                   i.event_id, i.tenant_id,
                   e.owner_user_id AS event_owner_user_id
            FROM invitees i
            JOIN events e ON i.event_id = e.id
            WHERE i.id = :iid AND i.tenant_id = :tid
        """),
        {"iid": invitee_id, "tid": tenant_id},
    ).mappings().fetchone()
    return dict(row) if row else None


def update_invitee(conn, tenant_id: int, invitee_id: int, **fields) -> bool:
    """
    Atualiza campos de convidado.
    Chaves válidas: name, phone, email, observation, response, media_url.
    SEMPRE filtra tenant_id no WHERE. Retorna True se atualizou.
    """
    allowed = {"name", "phone", "email", "observation", "response", "media_url", "responded_at"}
    to_set = {k: v for k, v in fields.items() if k in allowed}
    if not to_set:
        return False
    set_clause = ", ".join(f"{k} = :{k}" for k in to_set)
    params = {**to_set, "iid": invitee_id, "tid": tenant_id}
    result = conn.execute(
        text(f"UPDATE invitees SET {set_clause} WHERE id = :iid AND tenant_id = :tid"),
        params,
    )
    return result.rowcount > 0


def delete_invitee(conn, tenant_id: int, invitee_id: int) -> bool:
    """Deleta convidado. SEMPRE filtra tenant_id. Retorna True se deletou."""
    result = conn.execute(
        text("DELETE FROM invitees WHERE id = :iid AND tenant_id = :tid"),
        {"iid": invitee_id, "tid": tenant_id},
    )
    return result.rowcount > 0


# ── users ─────────────────────────────────────────────────────────────────────

def get_users(conn, tenant_id: int) -> list[dict]:
    """Lista usuários do tenant, mais recentes primeiro."""
    rows = conn.execute(
        text("""
            SELECT id, username, email, whatsapp, role,
                   must_change_password, is_active, created_at
            FROM users
            WHERE tenant_id = :tid
            ORDER BY created_at DESC
        """),
        {"tid": tenant_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def get_user_by_id(conn, tenant_id: int, user_id: int) -> dict | None:
    """Busca usuário por id. SEMPRE filtra tenant_id."""
    row = conn.execute(
        text("""
            SELECT id, tenant_id, username, email, password_hash,
                   role, must_change_password, is_active, whatsapp, created_at
            FROM users
            WHERE id = :uid AND tenant_id = :tid
        """),
        {"uid": user_id, "tid": tenant_id},
    ).mappings().fetchone()
    return dict(row) if row else None


def get_user_by_username(conn, tenant_id: int, username: str) -> dict | None:
    """Busca por username dentro do tenant (username único por tenant)."""
    row = conn.execute(
        text("""
            SELECT id, tenant_id, username, email, password_hash,
                   role, must_change_password, is_active, whatsapp
            FROM users
            WHERE username = :u AND tenant_id = :tid
        """),
        {"u": username, "tid": tenant_id},
    ).mappings().fetchone()
    return dict(row) if row else None


def get_user_by_email_global(conn, email: str) -> dict | None:
    """
    Busca usuário por email sem filtro de tenant.
    Email é UNIQUE GLOBAL — usado para login multi-tenant e forgot_password.
    """
    row = conn.execute(
        text("""
            SELECT id, tenant_id, username, email, password_hash,
                   role, must_change_password, is_active, whatsapp
            FROM users
            WHERE LOWER(email) = LOWER(:email)
        """),
        {"email": email},
    ).mappings().fetchone()
    return dict(row) if row else None


def add_user(
    conn,
    tenant_id: int,
    username: str,
    email: str,
    password_hash: str,
    *,
    role: str = "member",
    whatsapp: str | None = None,
    must_change_password: bool = True,
) -> int:
    """Cria usuário no tenant. Retorna o id gerado."""
    conn.execute(
        text("""
            INSERT INTO users
                (tenant_id, username, email, password_hash,
                 role, whatsapp, must_change_password)
            VALUES
                (:tid, :u, :email, :pw, :role, :whatsapp, :mcp)
        """),
        {
            "tid": tenant_id, "u": username, "email": email,
            "pw": password_hash, "role": role,
            "whatsapp": whatsapp, "mcp": int(must_change_password),
        },
    )
    row = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().fetchone()
    return int(row["id"])


def update_user(conn, tenant_id: int, user_id: int, **fields) -> bool:
    """Atualiza campos do usuário. SEMPRE filtra tenant_id."""
    allowed = {
        "username", "email", "whatsapp", "password_hash",
        "must_change_password", "role", "is_active",
    }
    to_set = {k: v for k, v in fields.items() if k in allowed}
    if not to_set:
        return False
    set_clause = ", ".join(f"{k} = :{k}" for k in to_set)
    params = {**to_set, "uid": user_id, "tid": tenant_id}
    result = conn.execute(
        text(f"UPDATE users SET {set_clause} WHERE id = :uid AND tenant_id = :tid"),
        params,
    )
    return result.rowcount > 0


def delete_user(conn, tenant_id: int, user_id: int) -> bool:
    """Deleta usuário. SEMPRE filtra tenant_id."""
    result = conn.execute(
        text("DELETE FROM users WHERE id = :uid AND tenant_id = :tid"),
        {"uid": user_id, "tid": tenant_id},
    )
    return result.rowcount > 0


def count_invitees_for_user(conn, tenant_id: int, user_id: int) -> int:
    """Conta convidados em eventos do usuário (para exibir na tela de gerência)."""
    row = conn.execute(
        text("""
            SELECT COUNT(*) AS total
            FROM invitees i
            JOIN events e ON i.event_id = e.id
            WHERE i.tenant_id = :tid AND e.owner_user_id = :uid
        """),
        {"tid": tenant_id, "uid": user_id},
    ).mappings().fetchone()
    return int(row["total"] or 0)


# ── signup self-service (2C) ──────────────────────────────────────────────────


def create_tenant_admin_user(
    conn, tenant_id: int, email: str, password_hash: str
) -> int:
    """
    Cria usuário tenant_admin com is_active=0 (aguarda verificação de email).
    username deriva do local-part do email (único por tenant — tenant é novo).
    Retorna o user_id gerado.
    """
    username = email.split("@")[0][:60]
    conn.execute(
        text("""
            INSERT INTO users
                (tenant_id, username, email, password_hash,
                 role, is_active, must_change_password)
            VALUES
                (:tid, :u, :email, :pw, 'tenant_admin', 0, 0)
        """),
        {"tid": tenant_id, "u": username, "email": email, "pw": password_hash},
    )
    row = conn.execute(text("SELECT LAST_INSERT_ID() AS id")).mappings().fetchone()
    return int(row["id"])


def create_email_verification_token(conn, user_id: int, *, ttl_hours: int = 24) -> str:
    """Gera e persiste token de verificação de email. Retorna o token string."""
    import secrets as _sec
    from datetime import datetime, timedelta
    token = _sec.token_urlsafe(32)
    expires = datetime.utcnow() + timedelta(hours=ttl_hours)
    conn.execute(
        text("""
            INSERT INTO email_verification_tokens (user_id, token, expires_at)
            VALUES (:uid, :tok, :exp)
        """),
        {"uid": user_id, "tok": token, "exp": expires},
    )
    return token


def get_valid_verification_token(conn, token: str) -> dict | None:
    """Retorna token de verificação se válido (não usado e não expirado)."""
    row = conn.execute(
        text("""
            SELECT id, user_id
            FROM email_verification_tokens
            WHERE token = :tok
              AND used = 0
              AND expires_at > UTC_TIMESTAMP()
        """),
        {"tok": token},
    ).mappings().fetchone()
    return dict(row) if row else None


def use_verification_token(conn, token_id: int, user_id: int) -> None:
    """Marca token como usado e ativa a conta do usuário (is_active = 1)."""
    conn.execute(
        text("UPDATE email_verification_tokens SET used = 1 WHERE id = :tid"),
        {"tid": token_id},
    )
    conn.execute(
        text("UPDATE users SET is_active = 1 WHERE id = :uid"),
        {"uid": user_id},
    )


def invalidate_verification_tokens(conn, user_id: int) -> None:
    """Invalida todos os tokens de verificação pendentes do usuário (para reenvio)."""
    conn.execute(
        text("""
            UPDATE email_verification_tokens
            SET used = 1
            WHERE user_id = :uid AND used = 0
        """),
        {"uid": user_id},
    )
