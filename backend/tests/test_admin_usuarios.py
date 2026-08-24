from tests.conftest import setup_db, qresult, USER_ROW_FULL
from unittest.mock import MagicMock, patch

import tasks

_LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}
_LIMITS_FREE = {'max_events': 2, 'max_invitees': 50, 'max_members': 1}
_LIMITS_PRO2 = {'max_events': 10, 'max_invitees': 500, 'max_members': 2}


def _usuarios_db(db, limits=None, member_count=0, users=None):
    """Configura as queries do GET /admin/usuarios."""
    entries = [
        qresult(fetchone=limits or _LIMITS_NONE),      # get_plan_limits
        qresult(fetchone={'n': member_count}),           # count_members_for_tenant
        qresult(all_rows=users or []),                   # get_users
    ]
    for _ in (users or []):
        entries.append(qresult(fetchone={'total': 0}))  # count_invitees_for_user per user
    return setup_db(db, *entries)


def test_add_usuario_sem_email_retorna_erro(admin_client, db):
    _usuarios_db(db)  # mock needed for the redirect GET /admin/usuarios
    resp = admin_client.post('/admin/usuarios/add',
                             data={'username': 'novo'},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert 'email' in resp.data.decode().lower() or 'obrigatório' in resp.data.decode().lower()


def test_add_usuario_com_email_cria_com_sucesso(admin_client, db):
    conn = setup_db(db,
                    qresult(fetchone=_LIMITS_NONE),    # get_plan_limits (unlimited)
                    qresult(fetchone={'n': 0}),          # count_members_for_tenant
                    qresult(),                           # add_user INSERT
                    qresult(fetchone={'id': 99}))        # LAST_INSERT_ID

    resp = admin_client.post('/admin/usuarios/add',
                             data={'username': 'novo', 'email': 'novo@test.com',
                                   'whatsapp': ''})
    assert resp.status_code == 302
    conn.commit.assert_called()


def test_edit_usuario_sem_email_retorna_erro(admin_client, db):
    _usuarios_db(db)

    resp = admin_client.post('/admin/usuarios/1/edit',
                             data={'username': 'op', 'email': ''},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert 'Email é obrigatório' in resp.data.decode() or 'email' in resp.data.decode().lower()


def test_listagem_usuarios_exibe_email(admin_client, db):
    _usuarios_db(db, limits=_LIMITS_NONE, member_count=1, users=[USER_ROW_FULL])

    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert 'operador@test.com' in resp.data.decode()


def test_add_usuario_nao_exibe_senha_padrao_hardcoded(admin_client, db):
    """Página de usuários não deve exibir senhas hardcoded ('102030@' ou 'Default@1234')."""
    _usuarios_db(db)

    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert '102030@' not in body
    assert 'Default@1234' not in body


# ── 4C: contagem/limite de membros + visibilidade do botão ───────────────────

def test_admin_usuarios_mostra_contagem_quando_ha_limite(admin_client, db):
    """GET /admin/usuarios exibe 'X de Y' quando max_members não é None."""
    _usuarios_db(db, limits=_LIMITS_FREE, member_count=1)
    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert b'1 de 1' in resp.data


def test_admin_usuarios_esconde_botao_quando_no_limite(admin_client, db):
    """Quando member_count >= max_members, botão Novo Usuário não aparece."""
    _usuarios_db(db, limits=_LIMITS_FREE, member_count=1)  # 1/1 = at limit
    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert b'data-bs-target="#modalAddUser"' not in resp.data


def test_admin_usuarios_mostra_botao_quando_abaixo_do_limite(admin_client, db):
    """Quando member_count < max_members, botão Novo Usuário aparece."""
    _usuarios_db(db, limits=_LIMITS_PRO2, member_count=1)  # 1/2 = below limit
    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert b'data-bs-target="#modalAddUser"' in resp.data


def test_admin_usuarios_mostra_botao_quando_ilimitado(admin_client, db):
    """Quando max_members=None (business), botão Novo Usuário sempre aparece."""
    _usuarios_db(db, limits=_LIMITS_NONE, member_count=999)
    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert b'data-bs-target="#modalAddUser"' in resp.data


# ── reset de senha de sub-usuário ─────────────────────────────────────────────

def test_reset_senha_usuario_com_smtp_envia_convite(admin_client, db, monkeypatch):
    """Com SMTP configurado, AINDA ASSIM rotaciona a senha imediatamente (revoga
    acesso agora) além de mandar o link — regressão corrigida (spec pré-prod #2):
    a rotação imediata não é 'trabalho desperdiçado', é a revogação real."""
    monkeypatch.setenv('EMAIL_SMTP', 'smtp-relay.brevo.com')
    monkeypatch.setenv('EMAIL_USER', 'login@brevo.com')
    conn = setup_db(db,
                    qresult(fetchone={'username': 'op', 'email': 'op@test.com'}),  # get_user_by_id
                    qresult(),   # update_user (rotaciona a senha AGORA)
                    qresult())   # create_password_reset_token INSERT

    with patch('app.enqueue_email') as mock_enqueue:
        resp = admin_client.post('/admin/usuarios/5/reset_senha')

    assert resp.status_code == 302
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] is tasks.send_member_invite_email
    assert mock_enqueue.call_args[0][1] == 'op@test.com'
    assert mock_enqueue.call_args[0][2] == 'op'
    assert '/reset_password/' in mock_enqueue.call_args[0][3]
    conn.commit.assert_called()
    assert conn.execute.call_count == 3  # get_user_by_id + update_user + create_password_reset_token


def test_reset_senha_usuario_sem_smtp_gera_senha_temporaria(admin_client, db, monkeypatch):
    """Sem SMTP configurado, mantém o fallback: gera e grava senha temporária, mostra na flash."""
    monkeypatch.delenv('EMAIL_SMTP', raising=False)
    monkeypatch.delenv('EMAIL_USER', raising=False)
    conn = setup_db(db,
                    qresult(fetchone={'username': 'op', 'email': 'op@test.com'}),  # get_user_by_id
                    qresult())   # update_user (senha temporária)

    resp = admin_client.post('/admin/usuarios/5/reset_senha')

    assert resp.status_code == 302
    with admin_client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    assert any('Senha temporária' in msg for _cat, msg in flashes)
    conn.commit.assert_called()
