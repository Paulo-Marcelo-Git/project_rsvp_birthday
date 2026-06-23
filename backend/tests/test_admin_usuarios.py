from tests.conftest import setup_db, qresult, USER_ROW_FULL
from unittest.mock import MagicMock

_LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}


def test_add_usuario_sem_email_retorna_erro(admin_client, db):
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
    from unittest.mock import MagicMock
    # Mock for the admin_usuarios page load after redirect (2 queries)
    users_result = MagicMock()
    users_m = MagicMock()
    users_m.all.return_value = []
    users_result.mappings.return_value = users_m
    counts_result = MagicMock()
    counts_m = MagicMock()
    counts_m.all.return_value = []
    counts_result.mappings.return_value = counts_m
    conn = MagicMock()
    conn.execute.side_effect = [users_result, counts_result]
    db.connect.return_value.__enter__.return_value = conn

    resp = admin_client.post('/admin/usuarios/1/edit',
                             data={'username': 'op', 'email': ''},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert 'Email é obrigatório' in resp.data.decode() or 'email' in resp.data.decode().lower()


def test_listagem_usuarios_exibe_email(admin_client, db):
    from tests.conftest import qresult, setup_db
    # repo.get_users → all_rows; repo.count_invitees_for_user → fetchone per user
    setup_db(db,
             qresult(all_rows=[USER_ROW_FULL]),   # get_users
             qresult(fetchone={'total': 0}))        # count_invitees_for_user (1 user)

    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert 'operador@test.com' in resp.data.decode()


def test_add_usuario_nao_exibe_senha_padrao_hardcoded(admin_client, db):
    """Página de usuários não deve exibir senhas hardcoded ('102030@' ou 'Default@1234')."""
    setup_db(db, qresult(all_rows=[]))  # get_users retorna lista vazia

    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    body = resp.data.decode()
    assert '102030@' not in body
    assert 'Default@1234' not in body
