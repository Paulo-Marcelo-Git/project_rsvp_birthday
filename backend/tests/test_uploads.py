"""
Testes para a rota /uploads/<filename> (serve_upload).

Cobre os três caminhos de acesso:
  1. Usuário autenticado (tenant_admin/member) — valida posse via tenant_id
  2. Convidado sem login com session['invite_token'] válido — valida via token
  3. Sem autenticação e sem session token — 404

Arquivo de integração: test_isolation.py (TestTenantIsolation) testa que
tenant A não consegue acessar arquivo de tenant B com banco real.
"""
import io
import os
import pytest
from unittest.mock import MagicMock, patch

from tests.conftest import qresult, setup_db, GUEST_ROW

# ── fixtures locais ───────────────────────────────────────────────────────────

FILENAME = "aabbccdd11223344.jpg"
OTHER_TENANT_FILENAME = "ffee99887766554.jpg"


@pytest.fixture
def upload_file(tmp_path, monkeypatch):
    """Cria arquivo temporário e aponta UPLOAD_FOLDER para ele."""
    import app as app_module
    f = tmp_path / FILENAME
    f.write_bytes(b"fake-image-data")
    monkeypatch.setitem(app_module.app.config, "UPLOAD_FOLDER", str(tmp_path))
    return str(tmp_path)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_media_row(tenant_id: int) -> dict:
    return {"tenant_id": tenant_id}


# ── testes: usuário autenticado ───────────────────────────────────────────────

def test_uploads_autenticado_arquivo_proprio_tenant_retorna_200(
    admin_client, db, upload_file
):
    """Tenant admin acessa arquivo que pertence ao seu próprio tenant."""
    # admin_client tem tenant_id=1 (conftest._ADMIN_DBUSER)
    setup_db(db, qresult(fetchone=_make_media_row(tenant_id=1)))

    resp = admin_client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 200


def test_uploads_autenticado_arquivo_outro_tenant_retorna_404(
    admin_client, db, upload_file
):
    """Tenant admin tenta acessar arquivo de outro tenant — deve receber 404."""
    # arquivo pertence ao tenant_id=2, admin está no tenant_id=1
    setup_db(db, qresult(fetchone=_make_media_row(tenant_id=2)))

    resp = admin_client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 404


def test_uploads_autenticado_filename_inexistente_no_bd_retorna_404(
    admin_client, db, upload_file
):
    """Filename não está no banco (nenhum invitee possui esse arquivo)."""
    setup_db(db, qresult(fetchone=None))

    resp = admin_client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 404


# ── testes: convidado via session token ───────────────────────────────────────

def test_uploads_session_token_valido_filename_correto_retorna_200(
    client, db, upload_file
):
    """Convidado com session['invite_token'] válido acessa seu próprio arquivo."""
    invitee = {**GUEST_ROW, "media_url": FILENAME}
    setup_db(db, qresult(fetchone=invitee))

    with client.session_transaction() as sess:
        sess["invite_token"] = GUEST_ROW["token"]

    resp = client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 200


def test_uploads_session_token_valido_filename_errado_retorna_404(
    client, db, upload_file
):
    """Session token válido mas media_url do invitee não bate com o filename pedido."""
    invitee = {**GUEST_ROW, "media_url": OTHER_TENANT_FILENAME}
    setup_db(db, qresult(fetchone=invitee))

    with client.session_transaction() as sess:
        sess["invite_token"] = GUEST_ROW["token"]

    resp = client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 404


def test_uploads_session_token_invalido_retorna_404(client, db, upload_file):
    """session['invite_token'] existe mas token não existe no banco."""
    setup_db(db, qresult(fetchone=None))

    with client.session_transaction() as sess:
        sess["invite_token"] = "tokeninexistente"

    resp = client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 404


# ── testes: sem autenticação e sem session ────────────────────────────────────

def test_uploads_sem_auth_sem_session_retorna_404(client, db, upload_file):
    """Requisição sem login e sem session token deve retornar 404."""
    resp = client.get(f"/uploads/{FILENAME}")

    assert resp.status_code == 404
    assert db.connect.call_count == 0


# ── testes: path traversal ────────────────────────────────────────────────────

def test_uploads_path_traversal_retorna_404(admin_client, db, upload_file):
    """Tentativa de path traversal deve retornar 404 sem acessar o banco."""
    resp = admin_client.get("/uploads/../../etc/passwd")

    assert resp.status_code == 404
    assert db.connect.call_count == 0


# ── teste: /invite/<token> armazena token na sessão ──────────────────────────

def test_invite_armazena_token_na_sessao(client, db):
    """/invite/<token> deve salvar o token em session['invite_token']."""
    from tests.conftest import TEXTS_ROW
    setup_db(db,
             qresult(fetchone=GUEST_ROW),
             qresult(fetchone=TEXTS_ROW))

    token = GUEST_ROW["token"]
    client.get(f"/invite/{token}")

    with client.session_transaction() as sess:
        assert sess.get("invite_token") == token
