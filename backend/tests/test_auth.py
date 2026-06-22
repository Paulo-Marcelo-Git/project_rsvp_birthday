from werkzeug.security import generate_password_hash
from tests.conftest import ADMIN_PASSWORD, qresult, setup_db


def test_login_page_loads(client):
    resp = client.get('/login')
    assert resp.status_code == 200


def test_login_credenciais_invalidas_exibe_erro(client, db):
    # Nenhum usuário encontrado no banco
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/login', data={
        'username': 'ninguem',
        'password': 'errada',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'inválidos' in resp.data.decode()


def test_login_admin_valido_redireciona_para_respostas(client):
    resp = client.post('/login', data={
        'username': 'testadmin',
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
        'password_hash': user_hash,
        'must_change_password': True,
        'tenant_id': 1,
        'role': 'member',
        'is_active': 1,
    }
    setup_db(db, qresult(fetchone=user_row))

    resp = client.post('/login', data={
        'username': 'operador',
        'password': 'Default@1234',
    })

    # Login bem-sucedido — redireciona (before_request cuida do /change_password)
    assert resp.status_code == 302
