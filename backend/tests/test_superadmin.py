from tests.conftest import setup_db, qresult, SUPERADMIN_EMAIL

_TENANT_ROW = {
    'id': 1, 'name': 'Festa da Ana', 'plan': 'free', 'status': 'active',
    'created_at': None,
    'max_events': 2, 'max_invitees': 50, 'max_members': 1,
    'event_count': 1, 'invitee_count': 10, 'member_count': 1,
}


# ── acesso negado ──────────────────────────────────────────────────────────────

def test_superadmin_nao_autenticado_redireciona(client):
    resp = client.get('/superadmin')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_superadmin_sem_env_var_retorna_403(admin_client):
    """Sem SUPERADMIN_EMAIL configurado → 403 mesmo se estiver autenticado."""
    resp = admin_client.get('/superadmin')
    assert resp.status_code == 403


def test_superadmin_tenant_admin_normal_retorna_403(admin_client, monkeypatch):
    """Tenant admin com email diferente de SUPERADMIN_EMAIL → 403."""
    monkeypatch.setenv('SUPERADMIN_EMAIL', SUPERADMIN_EMAIL)
    resp = admin_client.get('/superadmin')
    assert resp.status_code == 403


# ── acesso permitido ──────────────────────────────────────────────────────────

def test_superadmin_get_exibe_lista_tenants(superadmin_client, db):
    setup_db(db, qresult(all_rows=[_TENANT_ROW]))  # list_all_tenants

    resp = superadmin_client.get('/superadmin')

    assert resp.status_code == 200
    assert b'Festa da Ana' in resp.data


def test_superadmin_set_plan_redireciona(superadmin_client, db):
    setup_db(db, qresult())  # set_tenant_plan UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/set_plan',
                                   data={'plan': 'pro'})

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_suspend_redireciona(superadmin_client, db):
    setup_db(db, qresult())  # set_tenant_status UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/suspend')

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']


def test_superadmin_reactivate_redireciona(superadmin_client, db):
    setup_db(db, qresult())  # set_tenant_status UPDATE

    resp = superadmin_client.post('/superadmin/tenant/1/reactivate')

    assert resp.status_code == 302
    assert '/superadmin' in resp.headers['Location']
