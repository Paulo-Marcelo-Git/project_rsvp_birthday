"""Task 17 — signup não cria evento."""
import app as app_module
from tests.conftest import setup_db, qresult


def test_signup_nao_cria_evento(client, db, monkeypatch):
    monkeypatch.setenv('SKIP_EMAIL_VERIFICATION', 'true')
    conn = setup_db(db, qresult())   # UPDATE users SET is_active = 1
    monkeypatch.setattr(app_module.repo, 'get_user_by_email_global', lambda c, e: None)
    monkeypatch.setattr(app_module.repo, 'create_tenant', lambda c, n: 10)
    monkeypatch.setattr(app_module.repo, 'create_tenant_admin_user', lambda *a, **k: 20)

    resp = client.post('/signup', data={
        'nome_anfitriao': 'Ana', 'email': 'ana@example.com',
        'password': 'senha-forte-1', 'confirm_password': 'senha-forte-1', 'accept_terms': 'on',
    })

    assert resp.status_code == 302
    assert not hasattr(app_module.repo, 'create_default_event')
    for call in conn.execute.call_args_list:
        assert 'events' not in str(call[0][0]).lower()
    conn.commit.assert_called_once()
