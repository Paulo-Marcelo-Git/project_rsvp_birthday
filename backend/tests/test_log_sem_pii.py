"""
PR-0 — Logs sem dado pessoal (LGPD).

Executa os fluxos que logam e falha se QUALQUER registro capturado (root
logger, todos os níveis, inclusive traceback) contiver e-mail completo, nome,
observação, telefone ou username de teste, ou um token conhecido.
Também varre o código-fonte (AST) proibindo dado pessoal em chamadas logger.*.
"""
import ast
import io
import logging
from datetime import datetime
from pathlib import Path

import pymysql
import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

import app as app_module
from tests.conftest import _MEMBER_DBUSER, EVENT_ROW, LIMITS_NONE, PNG_BYTES

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Dados de teste com acento/emoji de propósito (Review Focus 4).
LOGIN_EMAIL = "joão.conceição@exemplo.com.br"
LOGIN_PW = "SenhaForte@123"
USERNAME = "joão.conceição"
SIGNUP_EMAIL = "maría.josé@exemplo.com"
HOST_NAME = "Família Conceição"
GUEST_NAME = "Ana Júlia Conceição"
GUEST_EMAIL = "ana.julia@convidados.com.br"
GUEST_PHONE = "11987654321"
OBS = "Levo meu filho 🎉 e chego às 20h"
INVITE_TOKEN = "TokConvitePr0Xyz123"
MEMBER_NAME = "Carlos Membro"
MEMBER_EMAIL = "carlos.membro@exemplo.com"

ALL_PII = (LOGIN_EMAIL, USERNAME, SIGNUP_EMAIL, HOST_NAME, GUEST_NAME, GUEST_EMAIL,
           GUEST_PHONE, OBS, INVITE_TOKEN, MEMBER_NAME, MEMBER_EMAIL)


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.DEBUG)
    return caplog


def _assert_sem_pii(caplog, *proibidos):
    texto = "\n".join(r.getMessage() for r in caplog.records) + "\n" + caplog.text
    for item in proibidos or ALL_PII:
        assert item not in texto, f"dado pessoal/token no log: {item!r}\n{texto}"


def _patch_repo(monkeypatch, **fns):
    for name, fn in fns.items():
        monkeypatch.setattr(app_module.repo, name, fn)


def _noop(*args, **kwargs):
    return None


# ── L1: login ─────────────────────────────────────────────────────────────────

def _user_row(**over):
    row = {
        "id": 77, "username": USERNAME, "email": LOGIN_EMAIL,
        "password_hash": generate_password_hash(LOGIN_PW),
        "must_change_password": False, "tenant_id": 5,
        "role": "tenant_admin", "is_active": 1,
    }
    row.update(over)
    return row


def _tenant(status="active", plan="free", trial_expired=False, trial_ends_at=None):
    return {"status": status, "plan": plan, "trial_ends_at": trial_ends_at,
            "trial_expired": trial_expired, "trial_days_remaining": None,
            "suspended_reason": None}


def test_login_sucesso_loga_ids(client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                get_user_by_email_global=lambda conn, email: _user_row(),
                get_tenant_status_and_trial=lambda conn, tid: _tenant())
    resp = client.post("/login", data={"email": LOGIN_EMAIL, "password": LOGIN_PW})
    assert resp.status_code == 302
    assert "Login bem-sucedido: user_id=77 tenant_id=5." in logs.text
    _assert_sem_pii(logs)


def test_login_email_inexistente_loga_email_mascarado(client, db, monkeypatch, logs):
    _patch_repo(monkeypatch, get_user_by_email_global=lambda conn, email: None)
    client.post("/login", data={"email": LOGIN_EMAIL, "password": "errada"})
    assert "Tentativa de login inválida: email=j***@exemplo.com.br." in logs.text
    _assert_sem_pii(logs)


def test_login_senha_errada_loga_user_id(client, db, monkeypatch, logs):
    _patch_repo(monkeypatch, get_user_by_email_global=lambda conn, email: _user_row())
    client.post("/login", data={"email": LOGIN_EMAIL, "password": "errada"})
    assert "Tentativa de login inválida: user_id=77." in logs.text
    _assert_sem_pii(logs)


def test_login_email_nao_verificado_loga_user_id(client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                get_user_by_email_global=lambda conn, email: _user_row(is_active=0))
    client.post("/login", data={"email": LOGIN_EMAIL, "password": LOGIN_PW})
    assert "Login bloqueado (email não verificado): user_id=77." in logs.text
    _assert_sem_pii(logs)


@pytest.mark.parametrize("tenant, trecho", [
    (_tenant(status="suspended"), "Login bloqueado (tenant suspenso): user_id=77 tenant_id=5."),
    (_tenant(status="trial", trial_expired=True, trial_ends_at=datetime(2020, 1, 1)),
     "Login bloqueado (trial expirado): user_id=77 tenant_id=5."),
    (_tenant(status="canceled"),
     "Login bloqueado (status desconhecido/cancelado 'canceled'): user_id=77 tenant_id=5."),
])
def test_login_bloqueios_logam_ids(client, db, monkeypatch, logs, tenant, trecho):
    _patch_repo(monkeypatch,
                get_user_by_email_global=lambda conn, email: _user_row(),
                get_tenant_status_and_trial=lambda conn, tid: dict(tenant),
                set_tenant_status=_noop)
    resp = client.post("/login", data={"email": LOGIN_EMAIL, "password": LOGIN_PW})
    assert resp.status_code == 200
    assert trecho in logs.text
    _assert_sem_pii(logs)


# ── L2: signup com erro ───────────────────────────────────────────────────────

def test_signup_erro_loga_so_tipo_e_codigo_mysql(client, db, monkeypatch, logs):
    monkeypatch.delenv("SKIP_EMAIL_VERIFICATION", raising=False)
    monkeypatch.setenv("EMAIL_SMTP", "smtp.exemplo.test")
    monkeypatch.setenv("EMAIL_USER", "bot")

    def _create_tenant(conn, nome):
        raise IntegrityError(
            "INSERT INTO users ...", {"email": SIGNUP_EMAIL},
            pymysql.err.IntegrityError(
                1062, f"Duplicate entry '{SIGNUP_EMAIL}' for key 'users.email'"),
        )

    _patch_repo(monkeypatch,
                get_user_by_email_global=lambda conn, email: None,
                create_tenant=_create_tenant)
    resp = client.post("/signup", data={
        "nome_anfitriao": HOST_NAME, "email": SIGNUP_EMAIL,
        "password": "SenhaForte@123", "confirm_password": "SenhaForte@123",
        "accept_terms": "on",
    })
    assert resp.status_code == 200
    assert "Erro ao criar conta: IntegrityError(mysql=1062)" in logs.text
    _assert_sem_pii(logs)


# ── L3: resposta do convidado ─────────────────────────────────────────────────

def _invitee(**over):
    row = {"id": 31, "event_id": 8, "tenant_id": 5, "name": GUEST_NAME,
           "token": INVITE_TOKEN, "response": "pending", "custom_message": None,
           "response_date": None, "media_url": None, "phone": GUEST_PHONE,
           "email": GUEST_EMAIL, "created_at": None, "event_media_url": "evento.jpg"}
    row.update(over)
    return row


def test_resposta_do_convite_loga_ids_sem_nome_nem_observacao(client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                get_invitee_by_token=lambda conn, token: _invitee(),
                update_invitee=_noop)
    resp = client.post(f"/invite/{INVITE_TOKEN}", data={"response": "yes", "observacao": OBS})
    assert resp.status_code == 302
    assert "Resposta registrada: invitee_id=31 event_id=8 tenant_id=5 resposta=yes" in logs.text
    _assert_sem_pii(logs)


# ── L4: convidados (add / editar / excluir) ───────────────────────────────────

def _admin_event(**over):
    ev = dict(EVENT_ROW, id=8, owner_user_id=1, media_url="evento.jpg")
    ev.update(over)
    return ev


def test_add_convidado_loga_ids(admin_client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                lock_tenant_for_update=_noop,
                get_event=lambda conn, tid, eid: _admin_event(),
                get_plan_limits=lambda conn, tid: dict(LIMITS_NONE),
                count_invitees_for_event=lambda conn, tid, eid: 0,
                add_invitee=_noop)
    resp = admin_client.post("/admin/convidados/add", data={
        "event_id": "8", "name": GUEST_NAME, "email": GUEST_EMAIL,
        "phone": GUEST_PHONE, "custom_message": OBS,
    })
    assert resp.status_code == 302
    assert "Convidado adicionado: event_id=8 tenant_id=1 por user_id=1." in logs.text
    _assert_sem_pii(logs)


def test_editar_convidado_loga_ids(admin_client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                get_invitee=lambda conn, tid, iid: _invitee(event_owner_user_id=1),
                update_invitee=_noop)
    resp = admin_client.post("/admin/convidados/31/edit", data={
        "name": GUEST_NAME, "email": GUEST_EMAIL, "phone": GUEST_PHONE,
        "custom_message": OBS, "response": "yes",
    })
    assert resp.status_code == 302
    assert "Convidado id=31 atualizado por user_id=1." in logs.text
    _assert_sem_pii(logs)


def test_excluir_convidado_loga_ids(admin_client, db, monkeypatch, logs):
    _patch_repo(monkeypatch,
                get_invitee=lambda conn, tid, iid: _invitee(event_owner_user_id=1),
                delete_invitee=_noop)
    resp = admin_client.post("/admin/convidados/31/delete")
    assert resp.status_code == 302
    assert "Convidado id=31 (event_id=8) excluído por user_id=1." in logs.text
    _assert_sem_pii(logs)


# ── L5: ações administrativas ─────────────────────────────────────────────────

def test_textos_tema_imagem_e_responsavel_logam_user_id(admin_client, db, monkeypatch, logs, upload_dir):
    _patch_repo(monkeypatch,
                get_event=lambda conn, tid, eid: _admin_event(),
                update_event_texts=_noop,
                set_event_theme=_noop,
                set_event_media=lambda conn, tid, eid, filename: None,
                set_event_owner=lambda conn, tid, eid, uid: True)

    assert admin_client.post("/admin/textos", data={"event_id": "8", "question_text": "Vem?"}).status_code == 302
    assert admin_client.post("/admin/set_tema", data={"event_id": "8", "theme": "girl"}).status_code == 302
    assert admin_client.post(
        "/admin/eventos/8/imagem",
        data={"media_file": (io.BytesIO(PNG_BYTES), "convite.png")},
        content_type="multipart/form-data",
    ).status_code == 302
    assert admin_client.post("/admin/eventos/8/responsavel", data={"owner_user_id": "2"}).status_code == 302

    assert "Textos do evento id=8 atualizados por user_id=1." in logs.text
    assert "Tema do evento id=8 alterado para 'girl' por user_id=1." in logs.text
    assert "Imagem do evento id=8 atualizada por user_id=1." in logs.text
    assert "Responsável do evento id=8 definido para user_id=2 por user_id=1." in logs.text
    _assert_sem_pii(logs, "testadmin")


def _member_row(**over):
    row = {"id": 9, "tenant_id": 1, "username": MEMBER_NAME, "email": MEMBER_EMAIL,
           "whatsapp": GUEST_PHONE, "role": "member", "is_active": 1,
           "must_change_password": True, "created_at": None}
    row.update(over)
    return row


def test_gestao_de_usuarios_loga_ids(admin_client, db, monkeypatch, logs):
    monkeypatch.delenv("EMAIL_SMTP", raising=False)
    monkeypatch.delenv("EMAIL_USER", raising=False)
    _patch_repo(monkeypatch,
                lock_tenant_for_update=_noop,
                get_plan_limits=lambda conn, tid: dict(LIMITS_NONE),
                count_members_for_tenant=lambda conn, tid: 0,
                add_user=lambda *a, **k: 9,
                get_user_by_id=lambda conn, tid, uid: _member_row(),
                update_user=_noop,
                delete_user=_noop)

    assert admin_client.post("/admin/usuarios/add", data={
        "username": MEMBER_NAME, "email": MEMBER_EMAIL, "whatsapp": GUEST_PHONE,
    }).status_code == 302
    assert admin_client.post("/admin/usuarios/9/edit", data={
        "username": MEMBER_NAME, "email": MEMBER_EMAIL, "whatsapp": GUEST_PHONE,
    }).status_code == 302
    assert admin_client.post("/admin/usuarios/9/reset_senha").status_code == 302
    assert admin_client.post("/admin/usuarios/9/delete").status_code == 302

    assert "Usuário id=9 criado por user_id=1." in logs.text
    assert "Usuário id=9 atualizado por user_id=1." in logs.text
    assert "Senha do usuário id=9 resetada por user_id=1." in logs.text
    assert "Usuário id=9 excluído por user_id=1." in logs.text
    _assert_sem_pii(logs, MEMBER_NAME, MEMBER_EMAIL, GUEST_PHONE, "testadmin")


def test_troca_de_senha_loga_user_id(member_client, db, monkeypatch, logs):
    _patch_repo(monkeypatch, update_user=_noop)
    monkeypatch.setattr(app_module, "load_user", lambda uid: _MEMBER_DBUSER)
    resp = member_client.post("/change_password", data={
        "new_password": "NovaSenha@123", "confirm_password": "NovaSenha@123",
    })
    assert resp.status_code == 302
    assert "Usuário id=2 alterou sua senha." in logs.text
    _assert_sem_pii(logs, "membertest", "member@test.com")


# ── A2: varredura do código-fonte ─────────────────────────────────────────────

# Variáveis/atributos/chaves que carregam dado pessoal, segredo ou mensagem de
# exceção crua. Dentro de mask_email()/mask_url()/exc_label()/mask_token_paths()
# e em `.__name__` (tipo da exceção, nome da função) é permitido.
_FORBIDDEN_NAMES = {"e", "exc", "err", "value", "email", "new_email", "username",
                    "new_username", "name", "nome", "observacao", "msg", "phone",
                    "whatsapp", "to_address", "token", "redis_url", "superadmin_email"}
_FORBIDDEN_ATTRS = {"username", "email", "name", "phone", "whatsapp"}
_FORBIDDEN_KEYS = {"name", "username", "email", "phone", "whatsapp", "observation",
                   "custom_message", "token"}
_SANITIZERS = {"mask_email", "mask_url", "mask_token_paths", "exc_label"}

LOGGED_FILES = ["app.py"]


def _unsafe(node):
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _SANITIZERS:
        return None
    if isinstance(node, ast.Attribute) and node.attr == "__name__":
        return None
    if isinstance(node, ast.Name) and node.id in _FORBIDDEN_NAMES:
        return node.id
    if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
        return "." + node.attr
    if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
            and node.slice.value in _FORBIDDEN_KEYS):
        return f"[{node.slice.value!r}]"
    for child in ast.iter_child_nodes(node):
        found = _unsafe(child)
        if found:
            return found
    return None


def _violations(filename, base_dir=BACKEND_DIR):
    tree = ast.parse((base_dir / filename).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"):
            continue
        if node.func.attr == "exception":
            found.append((node.lineno, "logger.exception"))
        found += [(node.lineno, "exc_info") for kw in node.keywords if kw.arg == "exc_info"]
        for arg in node.args:
            bad = _unsafe(arg)
            if bad:
                found.append((node.lineno, bad))
    return found


@pytest.mark.parametrize("filename", LOGGED_FILES)
def test_codigo_nao_loga_dado_pessoal(filename):
    assert _violations(filename) == [], f"{filename}: logger.* com dado pessoal/exceção crua"


def test_varredura_detecta_os_padroes_proibidos(tmp_path):
    """A varredura em si funciona (senão o teste acima passaria vazio)."""
    (tmp_path / "amostra.py").write_text(
        "logger.info(f\"x {email}\")\n"
        "logger.info(f\"x {current_user.username}\")\n"
        "logger.info(f\"x {res['name']}\")\n"
        "logger.error(f\"x {e}\")\n"
        "logger.exception('x')\n"
        "logger.error('x', exc_info=True)\n"
        "logger.info(f\"ok {mask_email(email)} {exc_label(e)} {type(e).__name__} {user['id']}\")\n",
        encoding="utf-8",
    )
    assert [line for line, _ in _violations("amostra.py", tmp_path)] == [1, 2, 3, 4, 5, 6]
