# backend/tests/test_swagger.py


def test_apidocs_redireciona_sem_autenticacao(client):
    resp = client.get('/apidocs/')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_apidocs_acessivel_para_super_admin(admin_client):
    resp = admin_client.get('/apidocs/')
    assert resp.status_code == 200


def test_apispec_json_redireciona_sem_autenticacao(client):
    resp = client.get('/apispec_1.json')
    assert resp.status_code == 302
