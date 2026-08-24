from datetime import datetime
from unittest.mock import MagicMock
from tests.conftest import setup_db, qresult
import app as app_module

_VALID_INFO = {'status': 'active', 'plan': 'free', 'trial_ends_at': None,
               'trial_expired': False, 'trial_days_remaining': None, 'suspended_reason': None}

_TENANT_ROW = {
    'id': 1, 'name': 'Festa da Ana', 'plan': 'free', 'status': 'active',
    'created_at': None, 'trial_ends_at': None, 'suspended_reason': None,
    'admin_email': 'ana@test.com',
    'max_events': 2, 'max_invitees': 50, 'max_members': 1,
    'event_count': 1, 'invitee_count': 10, 'member_count': 1,
}


# ── acesso negado ──────────────────────────────────────────────────────────────

def test_superadmin_nao_autenticado_redireciona(client):
    resp = client.get('/superadmin')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_superadmin_role_tenant_admin_retorna_403(admin_client):
    """tenant_admin (role != super_admin) não acessa /superadmin → 403."""
    resp = admin_client.get('/superadmin')
    assert resp.status_code == 403


# ── acesso permitido ──────────────────────────────────────────────────────────

def test_superadmin_get_exibe_lista_tenants(superadmin_client, db):
    setup_db(db, qresult(all_rows=[_TENANT_ROW]))  # list_all_tenants

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert b'Festa da Ana' in resp.data


def test_superadmin_get_exibe_email_do_tenant_admin(superadmin_client, db):
    setup_db(db, qresult(all_rows=[_TENANT_ROW]))  # list_all_tenants

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert b'ana@test.com' in resp.data


def test_superadmin_exibe_motivo_trial_na_pill_de_suspenso(superadmin_client, db):
    row = dict(_TENANT_ROW, status='suspended', suspended_reason='trial_expired')
    setup_db(db, qresult(all_rows=[row]))

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert 'Suspenso' in resp.data.decode()
    assert '(trial)' in resp.data.decode()


def test_superadmin_exibe_motivo_manual_na_pill_de_suspenso(superadmin_client, db):
    row = dict(_TENANT_ROW, status='suspended', suspended_reason='manual')
    setup_db(db, qresult(all_rows=[row]))

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert '(manual)' in resp.data.decode()


def test_superadmin_exibe_ainda_nao_logou_para_trial_sem_trial_ends_at(superadmin_client, db):
    """Tenant trial que nunca logou (trial_ends_at NULL) mostra 'Ainda não logou'."""
    row = dict(_TENANT_ROW, status='trial', trial_ends_at=None)
    setup_db(db, qresult(all_rows=[row]))

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert 'Ainda não logou' in resp.data.decode()


def test_superadmin_exibe_data_de_expiracao_para_trial_com_trial_ends_at(superadmin_client, db):
    """Tenant trial que já logou (trial_ends_at setado) mostra a data."""
    row = dict(_TENANT_ROW, status='trial', trial_ends_at=datetime(2026, 9, 5, 12, 0, 0))
    setup_db(db, qresult(all_rows=[row]))

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert '05/09/2026' in resp.data.decode()


def test_superadmin_pro_com_status_trial_nao_exibe_data_nem_ainda_nao_logou(superadmin_client, db):
    """Plano pago (pro/business) com status='trial' nunca expira — painel mostra '-', não data nem 'Ainda não logou'."""
    row = dict(_TENANT_ROW, plan='business', status='trial', trial_ends_at=datetime(2026, 9, 5, 12, 0, 0))
    setup_db(db, qresult(all_rows=[row]))

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    body = resp.data.decode()
    assert '05/09/2026' not in body
    assert 'Ainda não logou' not in body


def test_superadmin_set_plan_redireciona(superadmin_client, db):
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id (99 != tenant alvo 1)
             qresult(fetchone={'status': 'active', 'plan': 'pro', 'trial_ends_at': None,
                                'trial_expired': False, 'trial_days_remaining': None, 'suspended_reason': None}),  # get_tenant_status_and_trial
             qresult())  # set_tenant_plan UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'pro'})

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_set_plan_pro_reativa_tenant_suspenso_por_trial(superadmin_client, db):
    """Promover pra pro/business um tenant suspenso POR TRIAL EXPIRADO reativa automaticamente."""
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone={'status': 'suspended', 'plan': 'pro', 'trial_ends_at': '2020-01-01',
                                'trial_expired': True, 'trial_days_remaining': -900,
                                'suspended_reason': 'trial_expired'}),  # get_tenant_status_and_trial
             qresult(),  # set_tenant_plan UPDATE
             qresult())  # set_tenant_status -> active

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'pro'})

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_set_plan_pro_nao_reativa_suspensao_manual(superadmin_client, db):
    """Promover pra pro/business um tenant suspenso MANUALMENTE (abuso/fraude) NÃO reativa
    automaticamente — exige clique explícito em 'Reativar' mesmo após o upgrade de plano."""
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone={'status': 'suspended', 'plan': 'pro', 'trial_ends_at': None,
                                'trial_expired': False, 'trial_days_remaining': None,
                                'suspended_reason': 'manual'}),  # get_tenant_status_and_trial
             qresult())  # set_tenant_plan UPDATE
             # sem UPDATE de status: suspensão manual não deve reativar

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'pro'})

    assert resp.status_code == 302


def test_superadmin_set_plan_pro_nao_toca_status_se_nao_suspenso(superadmin_client, db):
    """Promover pra pro um tenant que já está active não deve gerar UPDATE de status extra."""
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone={'status': 'active', 'plan': 'pro', 'trial_ends_at': None,
                                'trial_expired': False, 'trial_days_remaining': None,
                                'suspended_reason': None}),  # get_tenant_status_and_trial
             qresult())  # set_tenant_plan UPDATE
             # sem UPDATE de status extra

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'pro'})

    assert resp.status_code == 302


def test_superadmin_set_plan_free_ainda_valida_tenant(superadmin_client, db):
    """Definir plano free ainda valida que o tenant existe/não é o reservado,
    mas não altera status (só a checagem de reativação é exclusiva de pro/business)."""
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone=dict(_VALID_INFO)),  # get_tenant_status_and_trial
             qresult())  # set_tenant_plan UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'free'})

    assert resp.status_code == 302


def test_superadmin_suspend_redireciona(superadmin_client, db):
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone=dict(_VALID_INFO)),  # get_tenant_status_and_trial
             qresult())  # set_tenant_status UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/suspend')

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_reactivate_redireciona(superadmin_client, db):
    setup_db(db,
             qresult(fetchone={'id': 99}),  # get_system_tenant_id
             qresult(fetchone=dict(_VALID_INFO)),  # get_tenant_status_and_trial
             qresult())  # set_tenant_status UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/reactivate')

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_bloqueia_acesso_a_rota_de_tenant(superadmin_client):
    """Super-admin autenticado é redirecionado de volta pro painel ao tentar rota de tenant."""
    resp = superadmin_client.get('/admin/eventos')
    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_set_plan_realmente_executa_e_nao_e_bloqueado(superadmin_client, db):
    """Regressão: rotas superadmin_* não devem ser bloqueadas pelo before_request
    (diferente do teste de redirect, que não distingue bloqueado vs. executado —
    aqui confirmamos que a query real rodou, não só que a resposta foi um redirect)."""
    conn = setup_db(db,
                     qresult(fetchone={'id': 99}),  # get_system_tenant_id
                     qresult(fetchone=dict(_VALID_INFO)),  # get_tenant_status_and_trial
                     qresult())  # set_tenant_plan UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan', data={'plan': 'free'})

    assert resp.status_code == 302
    conn.execute.assert_called()


# ── validação do tenant alvo (spec pré-prod #3) ───────────────────────────────

def test_load_target_tenant_bloqueia_tenant_reservado():
    c = MagicMock()
    c.execute.return_value.mappings.return_value.fetchone.side_effect = [
        {'id': 1},  # get_system_tenant_id retorna o mesmo id do alvo
    ]
    with app_module.app.test_request_context():
        result = app_module._load_target_tenant_or_flash(c, 1)
        assert result is None


def test_load_target_tenant_bloqueia_tenant_inexistente():
    c = MagicMock()
    c.execute.return_value.mappings.return_value.fetchone.side_effect = [
        {'id': 99},  # get_system_tenant_id (diferente do alvo)
        None,        # get_tenant_status_and_trial: tenant não existe
    ]
    with app_module.app.test_request_context():
        result = app_module._load_target_tenant_or_flash(c, 12345)
        assert result is None


def test_load_target_tenant_retorna_info_se_valido():
    c = MagicMock()
    c.execute.return_value.mappings.return_value.fetchone.side_effect = [
        {'id': 99},              # get_system_tenant_id
        dict(_VALID_INFO),       # get_tenant_status_and_trial
    ]
    with app_module.app.test_request_context():
        result = app_module._load_target_tenant_or_flash(c, 1)
        assert result == _VALID_INFO


def test_superadmin_suspend_bloqueia_tenant_reservado(superadmin_client, db):
    """Não deve conseguir suspender o tenant reservado do sistema — evita
    autobloqueio do painel super-admin. Só 1 query (get_system_tenant_id):
    se o código seguisse pra suspender, faltaria mock e o teste quebraria."""
    setup_db(db, qresult(fetchone={'id': 20}))  # get_system_tenant_id == alvo

    resp = superadmin_client.post('/superadmin/tenant/20/suspend')

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']
    with superadmin_client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    assert any('reservado' in msg for _cat, msg in flashes)


def test_superadmin_set_plan_bloqueia_tenant_inexistente(superadmin_client, db):
    setup_db(db,
             qresult(fetchone={'id': 99}),   # get_system_tenant_id
             qresult(fetchone=None))          # get_tenant_status_and_trial: não existe

    resp = superadmin_client.post('/superadmin/tenant/12345/set_plan', data={'plan': 'pro'})

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_is_superadmin_panel_endpoint_reconhece_prefixo():
    import app as app_module
    assert app_module._is_superadmin_panel_endpoint('superadmin') is True
    assert app_module._is_superadmin_panel_endpoint('superadmin_set_plan') is True
    assert app_module._is_superadmin_panel_endpoint('superadmin_qualquer_rota_futura') is True
    assert app_module._is_superadmin_panel_endpoint('admin_eventos') is False
    assert app_module._is_superadmin_panel_endpoint(None) is False
