from tests.conftest import setup_db, qresult, USER_ROW_FULL
from unittest.mock import MagicMock


def test_add_usuario_sem_email_retorna_erro(admin_client, db):
    resp = admin_client.post('/admin/usuarios/add',
                             data={'username': 'novo'},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert 'email' in resp.data.decode().lower() or 'obrigatório' in resp.data.decode().lower()


def test_add_usuario_com_email_cria_com_sucesso(admin_client, db):
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    db.connect.return_value.__enter__.return_value = conn

    resp = admin_client.post('/admin/usuarios/add',
                             data={'username': 'novo', 'email': 'novo@test.com',
                                   'whatsapp': ''},
                             follow_redirects=True)
    assert resp.status_code == 200
    assert conn.execute.called


def test_edit_usuario_sem_email_retorna_erro(admin_client, db):
    resp = admin_client.post('/admin/usuarios/1/edit',
                             data={'username': 'op', 'email': ''},
                             follow_redirects=False)
    # Validation rejects before hitting DB — should redirect back to admin_usuarios
    assert resp.status_code == 302
    assert '/admin/usuarios' in resp.headers.get('Location', '')


def test_listagem_usuarios_exibe_email(admin_client, db):
    users_rows = [USER_ROW_FULL]
    counts_rows = []
    conn = MagicMock()
    result1 = MagicMock()
    m1 = MagicMock()
    m1.all.return_value = users_rows
    result1.mappings.return_value = m1
    result2 = MagicMock()
    m2 = MagicMock()
    m2.all.return_value = counts_rows
    result2.mappings.return_value = m2
    conn.execute.side_effect = [result1, result2]
    db.connect.return_value.__enter__.return_value = conn

    resp = admin_client.get('/admin/usuarios')
    assert resp.status_code == 200
    assert 'operador@test.com' in resp.data.decode()
