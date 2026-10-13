"""Task 16 — member gerencia só eventos dos quais é responsável (db_id=2)."""
import io

import pytest

import app as app_module
from tests.conftest import setup_db, qresult, respostas_db, EVENT_ROW, GUEST_ROW, JPEG_BYTES

MEU = {**EVENT_ROW, 'id': 7, 'owner_user_id': 2}
ALHEIO = {**EVENT_ROW, 'id': 8, 'owner_user_id': 99}


def _stub_event(monkeypatch, ev):
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: ev)


def test_member_altera_tema_do_proprio_evento(member_client, db, monkeypatch):
    setup_db(db)
    _stub_event(monkeypatch, MEU)
    called = []
    monkeypatch.setattr(app_module.repo, 'set_event_theme', lambda c, t, e, th: called.append((e, th)))
    resp = member_client.post('/admin/set_tema', data={'theme': 'girl', 'event_id': '7'})
    assert resp.status_code == 302
    assert called == [(7, 'girl')]


def test_member_altera_textos_do_proprio_evento(member_client, db, monkeypatch):
    setup_db(db)
    _stub_event(monkeypatch, MEU)
    called = []
    monkeypatch.setattr(app_module.repo, 'update_event_texts', lambda c, t, e, **k: called.append(e))
    resp = member_client.post('/admin/textos', data={'event_id': '7', 'question_text': 'Vem?'})
    assert resp.status_code == 302
    assert called == [7]


# ── nenhuma rota altera evento alheio ────────────────────────────────────────

def test_member_tema_de_evento_alheio_404(member_client, db, monkeypatch):
    setup_db(db)
    _stub_event(monkeypatch, ALHEIO)
    monkeypatch.setattr(app_module.repo, 'set_event_theme', lambda *a: pytest.fail('alterou evento alheio'))
    assert member_client.post('/admin/set_tema', data={'theme': 'boy', 'event_id': '8'}).status_code == 404


def test_member_textos_de_evento_alheio_nao_grava(member_client, db, monkeypatch):
    conn = setup_db(db)
    _stub_event(monkeypatch, ALHEIO)
    monkeypatch.setattr(app_module.repo, 'update_event_texts', lambda *a, **k: pytest.fail('alterou evento alheio'))
    resp = member_client.post('/admin/textos', data={'event_id': '8', 'question_text': 'X'})
    assert resp.status_code == 302
    conn.commit.assert_not_called()


def test_member_imagem_de_evento_alheio_404(member_client, db, upload_dir, monkeypatch):
    setup_db(db)
    _stub_event(monkeypatch, ALHEIO)
    resp = member_client.post('/admin/eventos/8/imagem',
                              data={'media_file': (io.BytesIO(JPEG_BYTES), 'x.jpg')},
                              content_type='multipart/form-data')
    assert resp.status_code == 404


def test_member_edita_convidado_de_evento_alheio_403(member_client, db):
    setup_db(db, qresult(fetchone={**GUEST_ROW, 'event_owner_user_id': 99}))
    assert member_client.post('/admin/convidados/1/edit', data={'name': 'X'}).status_code == 403


def test_member_exclui_convidado_de_evento_alheio_403(member_client, db):
    setup_db(db, qresult(fetchone={**GUEST_ROW, 'event_owner_user_id': 99}))
    assert member_client.post('/admin/convidados/1/delete').status_code == 403


def test_member_exporta_evento_alheio_cai_no_filtro_proprio(member_client, db, monkeypatch):
    setup_db(db)
    _stub_event(monkeypatch, ALHEIO)
    seen = {}
    def fake_get_invitees(conn, tid, **kw):
        seen.update(kw)
        return []
    monkeypatch.setattr(app_module.repo, 'get_invitees', fake_get_invitees)
    member_client.get('/admin/exportar_xlsx?event_id=8')
    assert seen['event_id'] is None
    assert seen['owner_user_id'] == 2


def test_member_ve_controles_de_textos_e_tema_no_proprio_evento(member_client, db):
    respostas_db(db, events=[MEU])
    body = member_client.get('/admin/respostas?event_id=7').data.decode('utf-8')
    assert 'data-bs-target="#modalTextos"' in body
    assert 'name="theme"' in body
