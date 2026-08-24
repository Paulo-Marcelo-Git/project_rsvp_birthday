from datetime import datetime
from unittest.mock import MagicMock
from flask import get_flashed_messages
from werkzeug.security import generate_password_hash
from tests.conftest import qresult, setup_db
import app as app_module

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


def test_login_seta_email_no_dbuser_da_sessao(client, db):
    """Regressão: DbUser construído no login() deve carregar current_user.email."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),
             qresult(fetchone={'status': 'active', 'trial_ends_at': None, 'trial_expired': False}))

    client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })
    from flask_login import current_user
    assert current_user.email == 'landlord@test.com'


def test_login_dbuser_tenant_admin_redireciona_para_respostas(client, db):
    """DbUser com role='tenant_admin' e is_active=1 autentica e redireciona para respostas."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),           # get_user_by_email_global
             qresult(fetchone={'status': 'active', 'trial_ends_at': None, 'trial_expired': False}))   # get_tenant_status_and_trial

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
             qresult(fetchone={'status': 'active', 'trial_ends_at': None, 'trial_expired': False}))  # get_tenant_status_and_trial

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
             qresult(fetchone={'status': 'suspended', 'trial_ends_at': None, 'trial_expired': False}))      # get_tenant_status_and_trial

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'suspensa' in resp.data.decode().lower()
    assert '/admin/respostas' not in resp.headers.get('Location', '')


# ── expiração de trial (conta a partir do primeiro login) ────────────────────

def test_login_trial_primeiro_login_inicia_contagem(client, db):
    """trial_ends_at ainda NULL (nunca logou) → inicia o trial, deixa logar e
    mostra o pop-up (flash categoria trial_modal) com a data de expiração."""
    ends_at = datetime(2026, 9, 5, 12, 0, 0)
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': None,
                                'trial_expired': False, 'trial_days_remaining': None}),  # get_tenant_status_and_trial
             qresult(),                                          # start_tenant_trial UPDATE
             qresult(fetchone={'trial_ends_at': ends_at}))       # start_tenant_trial SELECT (valor final)

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    modal_msgs = [msg for cat, msg in flashes if cat == 'trial_modal']
    assert len(modal_msgs) == 1
    assert '14 dias' in modal_msgs[0]
    assert '05/09/2026' in modal_msgs[0]


def test_login_trial_expirado_bloqueia_e_suspende(client, db):
    """trial_ends_at no passado → bloqueia login e persiste status='suspended'."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': '2020-01-01',
                                'trial_expired': True, 'trial_days_remaining': -900}),  # get_tenant_status_and_trial
             qresult())                                          # set_tenant_status UPDATE

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'período de teste expirou' in resp.data.decode().lower()
    assert '/admin/respostas' not in resp.headers.get('Location', '')


def test_login_trial_valido_permite_login(client, db):
    """trial_ends_at no futuro e fora da janela de aviso → login normal, sem UPDATE extra, sem pop-up."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': '2099-01-01',
                                'trial_expired': False, 'trial_days_remaining': 60}))  # get_tenant_status_and_trial

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    assert not any(cat == 'trial_modal' for cat, _ in flashes)


def test_login_trial_aviso_3_dias_antes_mostra_popup(client, db):
    """trial_days_remaining dentro da janela de aviso (≤3) → mostra pop-up, sem bloquear nem alterar dados."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': datetime(2026, 9, 5),
                                'trial_expired': False, 'trial_days_remaining': 2}))  # get_tenant_status_and_trial
             # sem 3º qresult: aviso não deve gerar nenhum UPDATE

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    modal_msgs = [msg for cat, msg in flashes if cat == 'trial_modal']
    assert len(modal_msgs) == 1
    assert '05/09/2026' in modal_msgs[0]
    assert '2 dia' in modal_msgs[0]


# ── expiração de trial não se aplica a contas pagas (Pro/Business) ───────────

def test_login_trial_expirado_mas_plano_pro_nao_bloqueia(client, db):
    """status='trial' + trial_ends_at no passado, mas plan='pro' → nunca expira, login normal."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'pro', 'trial_ends_at': '2020-01-01',
                                'trial_expired': True, 'trial_days_remaining': -900}))  # get_tenant_status_and_trial
             # sem 3º qresult: não deve haver UPDATE nenhum (nem suspend, nem start_tenant_trial)

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    assert not any(cat == 'trial_modal' for cat, _ in flashes)


def test_login_trial_business_nunca_inicia_contagem(client, db):
    """status='trial' + trial_ends_at NULL, mas plan='business' → não inicia contagem, login normal."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),                     # get_user_by_email_global
             qresult(fetchone={'status': 'trial', 'plan': 'business', 'trial_ends_at': None,
                                'trial_expired': False, 'trial_days_remaining': None}))  # get_tenant_status_and_trial
             # sem 3º qresult: não deve chamar start_tenant_trial

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


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
    """Tenant com status='trial' e trial_ends_at no futuro: login deve funcionar."""
    setup_db(db,
             qresult(fetchone=_ACTIVE_ROW),
             qresult(fetchone={'status': 'trial', 'plan': 'free', 'trial_ends_at': '2099-01-01',
                                'trial_expired': False, 'trial_days_remaining': 60}))

    resp = client.post('/login', data={
        'email': 'landlord@test.com',
        'password': _PW,
    })

    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


# ── ProxyFix — rate limit atrás do nginx em produção (spec pré-prod #1) ──────

def test_proxyfix_esta_aplicado_ao_wsgi_app():
    from werkzeug.middleware.proxy_fix import ProxyFix
    assert isinstance(app_module.app.wsgi_app, ProxyFix)


def test_proxyfix_ajusta_remote_addr_via_x_forwarded_for():
    """Confirma que o REMOTE_ADDR visto pela app reflete o X-Forwarded-For
    do proxy, não o IP do socket (que em produção é sempre o loopback do
    nginx) — sem isso, o rate limiting cai todo no mesmo balde."""
    proxy = app_module.app.wsgi_app
    inner_app = proxy.app
    captured = {}

    def spy(environ, start_response):
        captured['remote_addr'] = environ.get('REMOTE_ADDR')
        return inner_app(environ, start_response)

    proxy.app = spy
    try:
        client = app_module.app.test_client()
        client.get('/login', headers={'X-Forwarded-For': '203.0.113.5'})
    finally:
        proxy.app = inner_app

    assert captured['remote_addr'] == '203.0.113.5'


# ── _build_password_reset_url isolado (dedup do item #8) ────────────────────

def test_build_password_reset_url_monta_url_com_token(monkeypatch):
    monkeypatch.setattr(app_module.repo, 'create_password_reset_token',
                         lambda conn, uid: 'TOKEN123')
    monkeypatch.setenv('APP_BASE_URL', 'https://comemore.example.com')
    with app_module.app.test_request_context():
        url = app_module._build_password_reset_url(MagicMock(), 42)
    assert url == 'https://comemore.example.com/reset_password/TOKEN123'


# ── _check_tenant_access isolado (helper extraído do login(), item #3/#4) ────
# Testa a máquina de estados do trial sem precisar passar pelo fluxo de
# login inteiro — mocka só repo.get_tenant_status_and_trial/start_tenant_trial/
# set_tenant_status via monkeypatch, não a conexão de baixo nível.

def test_check_tenant_access_suspenso_bloqueia(monkeypatch):
    monkeypatch.setattr(app_module.repo, 'get_tenant_status_and_trial',
                         lambda conn, tid: {'status': 'suspended', 'plan': 'free',
                                             'trial_ends_at': None, 'trial_expired': False,
                                             'trial_days_remaining': None, 'suspended_reason': 'manual'})
    with app_module.app.test_request_context():
        blocked = app_module._check_tenant_access(MagicMock(), 1, 'x@test.com')
        assert blocked is True


def test_check_tenant_access_trial_primeiro_login_nao_bloqueia(monkeypatch):
    ends_at = datetime(2026, 9, 5, 12, 0, 0)
    monkeypatch.setattr(app_module.repo, 'get_tenant_status_and_trial',
                         lambda conn, tid: {'status': 'trial', 'plan': 'free',
                                             'trial_ends_at': None, 'trial_expired': False,
                                             'trial_days_remaining': None, 'suspended_reason': None})
    monkeypatch.setattr(app_module.repo, 'start_tenant_trial', lambda conn, tid: ends_at)
    with app_module.app.test_request_context():
        blocked = app_module._check_tenant_access(MagicMock(), 1, 'x@test.com')
        assert blocked is False
        flashes = list(get_flashed_messages(category_filter=["trial_modal"]))
        assert any('14 dias' in m for m in flashes)


def test_check_tenant_access_trial_expirado_bloqueia(monkeypatch):
    monkeypatch.setattr(app_module.repo, 'get_tenant_status_and_trial',
                         lambda conn, tid: {'status': 'trial', 'plan': 'free',
                                             'trial_ends_at': datetime(2020, 1, 1), 'trial_expired': True,
                                             'trial_days_remaining': -900, 'suspended_reason': None})
    monkeypatch.setattr(app_module.repo, 'set_tenant_status', lambda *a, **kw: None)
    with app_module.app.test_request_context():
        blocked = app_module._check_tenant_access(MagicMock(), 1, 'x@test.com')
        assert blocked is True


def test_check_tenant_access_pro_nunca_bloqueia_mesmo_expirado(monkeypatch):
    monkeypatch.setattr(app_module.repo, 'get_tenant_status_and_trial',
                         lambda conn, tid: {'status': 'trial', 'plan': 'pro',
                                             'trial_ends_at': datetime(2020, 1, 1), 'trial_expired': True,
                                             'trial_days_remaining': -900, 'suspended_reason': None})
    with app_module.app.test_request_context():
        blocked = app_module._check_tenant_access(MagicMock(), 1, 'x@test.com')
        assert blocked is False
        flashes = list(get_flashed_messages(category_filter=["trial_modal"]))
        assert flashes == []


def test_check_tenant_access_ativo_nao_bloqueia(monkeypatch):
    monkeypatch.setattr(app_module.repo, 'get_tenant_status_and_trial',
                         lambda conn, tid: {'status': 'active', 'plan': 'free',
                                             'trial_ends_at': None, 'trial_expired': False,
                                             'trial_days_remaining': None, 'suspended_reason': None})
    with app_module.app.test_request_context():
        blocked = app_module._check_tenant_access(MagicMock(), 1, 'x@test.com')
        assert blocked is False


# ── pop-up (modal) de aviso de trial no template base ─────────────────────────

def test_base_html_abre_modal_quando_ha_flash_trial_modal(client):
    """Flash categoria trial_modal deve renderizar como modal Bootstrap, não como alert banner."""
    with client.session_transaction() as sess:
        sess['_flashes'] = [('trial_modal', 'Sua conta expira em 3 dia(s).')]

    resp = client.get('/termos')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'id="trialModal"' in body
    assert 'Sua conta expira em 3 dia(s).' in body
    assert 'new bootstrap.Modal' in body
    assert 'alert-trial_modal' not in body


def test_base_html_sem_flash_trial_modal_nao_renderiza_modal(client):
    """Sem flash trial_modal, o bloco de modal e o script de abertura não devem aparecer."""
    resp = client.get('/termos')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'id="trialModal"' not in body
    assert 'new bootstrap.Modal' not in body


_SUPER_ADMIN_ROW = {
    'id': 999, 'username': 'superadmin',
    'email': 'superadmin@test.com',
    'password_hash': generate_password_hash('Superpass@1'),
    'must_change_password': False,
    'tenant_id': 99, 'role': 'super_admin',
    'is_active': 1,
}


def test_login_super_admin_redireciona_para_superadmin(client, db):
    """DbUser com role='super_admin' é redirecionado direto para /superadmin."""
    setup_db(db,
             qresult(fetchone=_SUPER_ADMIN_ROW),
             qresult(fetchone={'status': 'active'}))

    resp = client.post('/login', data={
        'email': 'superadmin@test.com',
        'password': 'Superpass@1',
    })

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


# ── 5B-2: páginas públicas de termos e privacidade ────────────────────────────

def test_termos_retorna_200(client):
    """GET /termos deve retornar 200 sem autenticação."""
    resp = client.get('/termos')
    assert resp.status_code == 200


def test_privacidade_retorna_200(client):
    """GET /privacidade deve retornar 200 sem autenticação."""
    resp = client.get('/privacidade')
    assert resp.status_code == 200


# ── 5B-3: checkbox de aceite dos termos no signup ─────────────────────────────

def test_signup_checkbox_presente_no_template(client):
    """GET /signup deve conter campo accept_terms no HTML."""
    resp = client.get('/signup')
    assert resp.status_code == 200
    assert b'accept_terms' in resp.data, "Campo accept_terms ausente no formulário de signup"


def test_signup_sem_aceite_retorna_erro(client, db):
    """POST /signup sem accept_terms deve exibir flash de erro sobre os termos."""
    from tests.conftest import setup_db, qresult
    setup_db(db, qresult(fetchone=None))

    resp = client.post('/signup', data={
        'nome_anfitriao': 'Host Teste',
        'email': 'host@test.com',
        'password': 'Senha@1234',
        'confirm_password': 'Senha@1234',
        # 'accept_terms' ausente propositalmente
    }, follow_redirects=True)

    assert resp.status_code == 200
    # Verifica flash de erro específico sobre aceite dos termos
    assert b'aceitar os Termos de Uso' in resp.data, (
        "Flash de erro específico sobre aceite dos termos deve aparecer"
    )


def test_signup_com_aceite_grava_accepted_terms_at(client, db, monkeypatch):
    """POST /signup com accept_terms deve passar accepted_terms_at não-None para create_tenant_admin_user."""
    import app as app_module
    from unittest.mock import patch, MagicMock
    from tests.conftest import setup_db, qresult

    # Simula: email não existe, criação bem-sucedida
    setup_db(db, qresult(fetchone=None))

    captured = {}

    original_create = app_module.repo.create_tenant_admin_user

    def mock_create(conn, tenant_id, email, password_hash, accepted_terms_at=None):
        captured['accepted_terms_at'] = accepted_terms_at
        return 42  # user_id fake

    monkeypatch.setenv('SKIP_EMAIL_VERIFICATION', 'true')
    monkeypatch.setattr(app_module.repo, 'create_tenant_admin_user', mock_create)
    # Também patch create_tenant e create_default_event para não precisar de DB real
    monkeypatch.setattr(app_module.repo, 'create_tenant', lambda conn, nome: 1)
    monkeypatch.setattr(app_module.repo, 'create_default_event',
                        lambda conn, tid, nome, owner_user_id: None)
    monkeypatch.setattr(app_module, 'enqueue_email', lambda *a, **k: None)

    resp = client.post('/signup', data={
        'nome_anfitriao': 'Host Teste',
        'email': 'novo@test.com',
        'password': 'Senha@1234',
        'confirm_password': 'Senha@1234',
        'accept_terms': '1',
    }, follow_redirects=True)

    assert resp.status_code == 200
    assert 'accepted_terms_at' in captured, "create_tenant_admin_user não foi chamado"
    assert captured['accepted_terms_at'] is not None, (
        "accepted_terms_at deve ser um datetime quando accept_terms está presente"
    )
