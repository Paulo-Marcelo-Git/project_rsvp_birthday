"""Task 18 — tenant sem evento é conduzido a /admin/primeiro-evento."""
import io

import app as app_module
from tests.conftest import setup_db, qresult, JPEG_BYTES, LIMITS_NONE


def test_respostas_admin_sem_evento_redireciona_para_primeiro_evento(admin_client, db):
    setup_db(db, qresult(all_rows=[]))   # list_events vazio
    resp = admin_client.get('/admin/respostas')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/primeiro-evento')


def test_respostas_member_sem_evento_nao_redireciona(member_client, db):
    setup_db(db, qresult(all_rows=[]))
    resp = member_client.get('/admin/respostas')
    assert resp.status_code == 200
    assert 'Nenhum evento atribuído a você' in resp.data.decode('utf-8')


def test_admin_eventos_sem_evento_redireciona(admin_client, db):
    setup_db(db, qresult(all_rows=[]), qresult(fetchone=LIMITS_NONE), qresult(all_rows=[]))
    resp = admin_client.get('/admin/eventos')
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/primeiro-evento')


def test_add_convidado_sem_evento_redireciona(admin_client, db):
    setup_db(db, qresult(), qresult(fetchone=None))   # lock + get_default_event_id → None
    resp = admin_client.post('/admin/convidados/add', data={'name': 'Ana'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/primeiro-evento')


def test_primeiro_evento_get_mostra_formulario(admin_client, db):
    setup_db(db, qresult(fetchone={'n': 0}))   # count_events_for_tenant
    body = admin_client.get('/admin/primeiro-evento').data.decode('utf-8')
    assert 'Crie seu primeiro evento' in body
    assert 'name="media_file"' in body and 'required' in body


def test_primeiro_evento_com_evento_existente_redireciona(admin_client, db):
    setup_db(db, qresult(fetchone={'n': 1}))
    resp = admin_client.get('/admin/primeiro-evento')
    assert resp.status_code == 302
    assert '/admin/respostas' in resp.headers['Location']


def test_primeiro_evento_post_cria_e_vai_para_respostas(admin_client, db, upload_dir, monkeypatch):
    setup_db(db, qresult(fetchone={'n': 0}))
    monkeypatch.setattr(app_module, '_create_event_with_media', lambda title, f: (55, None))
    resp = admin_client.post('/admin/primeiro-evento',
                             data={'title': 'Festa', 'media_file': (io.BytesIO(JPEG_BYTES), 'c.jpg')},
                             content_type='multipart/form-data')
    assert resp.status_code == 302
    assert 'event_id=55' in resp.headers['Location']


def test_primeiro_evento_post_sem_imagem_reexibe_com_erro(admin_client, db, monkeypatch):
    setup_db(db, qresult(fetchone={'n': 0}))
    monkeypatch.setattr(app_module, '_create_event_with_media',
                        lambda title, f: (None, 'A imagem do convite é obrigatória.'))
    resp = admin_client.post('/admin/primeiro-evento', data={'title': 'Festa'})
    assert resp.status_code == 200
    body = resp.data.decode('utf-8')
    assert 'A imagem do convite é obrigatória.' in body
    assert 'value="Festa"' in body


def test_primeiro_evento_member_403(member_client, db):
    assert member_client.get('/admin/primeiro-evento').status_code == 403


# ── guarda de 50MB no navegador (nginx devolve 413 cru acima de 55MB) ─────────

_UPLOAD_GUARD_MARKER = 'data-max-upload-bytes="52428800"'


def test_upload_guard_presente_em_primeiro_evento(admin_client, db):
    setup_db(db, qresult(fetchone={'n': 0}))
    body = admin_client.get('/admin/primeiro-evento').data.decode('utf-8')
    assert _UPLOAD_GUARD_MARKER in body
    assert 'Arquivo muito grande. O limite é 50MB.' in body


def test_upload_guard_presente_em_admin_eventos(admin_client, db):
    from tests.test_routes_eventos import _eventos_db
    _eventos_db(db)
    body = admin_client.get('/admin/eventos').data.decode('utf-8')
    assert _UPLOAD_GUARD_MARKER in body


def test_upload_guard_presente_em_respostas(admin_client, db):
    from tests.conftest import respostas_db
    respostas_db(db)
    body = admin_client.get('/admin/respostas?event_id=1').data.decode('utf-8')
    assert _UPLOAD_GUARD_MARKER in body
