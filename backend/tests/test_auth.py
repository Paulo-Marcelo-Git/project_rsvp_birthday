from werkzeug.security import generate_password_hash
from tests.conftest import ADMIN_PASSWORD, qresult, setup_db


def test_login_page_loads(client):
    resp = client.get('/login')
    assert resp.status_code == 200


def test_login_credenciais_invalidas_exibe_erro(client, db):
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/login', data={
        'email': 'ninguem@test.com',
        'password': 'errada',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'inválidos' in resp.data.decode()


def test_login_dbuser_tenant_admin_redireciona_para_respostas(client, db):
    """DbUser com role='tenant_admin' e is_active=1 autentica e redireciona para respostas."""
    from werkzeug.security import generate_password_hash
    admin_pw = 'SenhaAdminFort@99'
    user_row = {
        'id': 1, 'username': 'landlord',
        'email': 'landlord@test.com',
        'password_hash': generate_password_hash(admin_pw),
        'must_change_password': False,
        'tenant_id': 1, 'role': 'tenant_admin',
        'is_active': 1,
    }
    setup_db(db, qresult(fetchone=user_row))

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': admin_pw,
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
        'email': 'operador@test.com',
        'password_hash': user_hash,
        'must_change_password': True,
        'tenant_id': 1,
        'role': 'member',
        'is_active': 1,
    }
    setup_db(db, qresult(fetchone=user_row))

    resp = client.post('/login', data={
        'email': 'operador@test.com',
        'password': 'Default@1234',
    })

    assert resp.status_code == 302


def test_login_por_username_falha_limpo(client, db):
    """Submeter username sem @ não autentica — get_user_by_email_global retorna None para string sem formato de email."""
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/login', data={
        'email': 'operador',
        'password': 'Default@1234',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'inválidos' in resp.data.decode()


def test_login_usuario_nao_verificado_exibe_mensagem_especifica(client, db):
    """Usuário com is_active=0 vê mensagem 'Confirme seu email', não a genérica de senha inválida."""
    user_row = {
        'id': 99, 'username': 'noverified',
        'email': 'noverified@test.com',
        'password_hash': generate_password_hash('senha123'),
        'must_change_password': False,
        'tenant_id': 1, 'role': 'member',
        'is_active': 0,
    }
    setup_db(db, qresult(fetchone=user_row))

    resp = client.post('/login', data={
        'email': 'noverified@test.com',
        'password': 'senha123',
    }, follow_redirects=True)

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Confirme seu email' in body
    assert 'inválidos' not in body
