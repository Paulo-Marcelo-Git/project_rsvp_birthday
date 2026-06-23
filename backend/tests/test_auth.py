from werkzeug.security import generate_password_hash
from tests.conftest import qresult, setup_db

_ACTIVE_ROW = {
    'id': 1, 'username': 'landlord',
    'email': 'landlord@test.com',
    'password_hash': generate_password_hash('SenhaAdminFort@99'),
    'must_change_password': False,
    'tenant_id': 1, 'role': 'tenant_admin',
    'is_active': 1,
}
_PW = 'SenhaAdminFort@99'


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
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),           # get_user_by_email_global
             qresult(fetchone={'status': 'active'}))   # get_tenant_status

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
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
    setup_db(db,
             qresult(fetchone=user_row),
             qresult(fetchone={'status': 'active'}))  # get_tenant_status

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


# ── 4D-1: login bloqueado para tenants suspensos ──────────────────────────────

def test_login_tenant_suspenso_bloqueia(client, db):
    """Tenant suspenso: login com credenciais válidas deve ser bloqueado."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                 # get_user_by_email_global
             qresult(fetchone={'status': 'suspended'}))      # get_tenant_status

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'suspensa' in resp.data.decode().lower()
    assert '/admin/respostas' not in resp.headers.get('Location', '')


def test_login_tenant_ativo_permite(client, db):
    """Tenant com status='active': login normal deve funcionar."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),
             qresult(fetchone={'status': 'active'}))

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


def test_login_tenant_trial_permite(client, db):
    """Tenant com status='trial': login deve funcionar (trial não está suspenso)."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),
             qresult(fetchone={'status': 'trial'}))

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


# ── 5B-2: páginas públicas de termos e privacidade ────────────────────────────

def test_termos_retorna_200(client):
    """GET /termos deve retornar 200 sem autenticação."""
    resp = client.get('/termos')
    assert resp.status_code == 200


def test_privacidade_retorna_200(client):
    """GET /privacidade deve retornar 200 sem autenticação."""
    resp = client.get('/privacidade')
    assert resp.status_code == 200
