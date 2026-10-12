from tests.conftest import (
    qresult, setup_db,
    GUEST_ROW, STATS_ROW, DEFAULT_EVENT_ROW, TEXTS_ROW,
    respostas_db,
)


_LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}


def _respostas_db(db, guests=None):
    return respostas_db(db, guests=guests)


# ── Fix: page=abc não deve crashar (ValueError) ───────────────────────────────

def test_page_invalido_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?event_id=1&page=abc')

    assert resp.status_code == 200


def test_page_negativo_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?event_id=1&page=-10')

    assert resp.status_code == 200


def test_page_float_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?event_id=1&page=1.5')

    assert resp.status_code == 200


# ── Fix: XSS — nomes não devem aparecer crus em contexto JavaScript ───────────

def test_xss_script_tag_no_nome_e_escapado(admin_client, db):
    guest_xss = {**GUEST_ROW, 'name': '<script>alert(1)</script>'}
    _respostas_db(db, guests=[guest_xss])

    resp = admin_client.get('/admin/respostas?event_id=1')
    body = resp.data.decode()

    assert '<script>alert(1)</script>' not in body
    assert '&lt;script&gt;' in body


def test_xss_aspas_simples_no_nome_nao_quebra_js(admin_client, db):
    """Nome com aspas simples não deve aparecer em onsubmit inline."""
    guest_xss = {**GUEST_ROW, 'name': "'); alert(document.cookie); ('"}
    _respostas_db(db, guests=[guest_xss])

    resp = admin_client.get('/admin/respostas?event_id=1')
    body = resp.data.decode()

    # A correção usa data-name= em vez de onsubmit inline
    assert "onsubmit=\"return confirm('Excluir" not in body
    assert 'delete-guest-form' in body


def test_formulario_exclusao_usa_data_attribute(admin_client, db):
    """Formulário de exclusão deve usar classe e data-name, não onsubmit inline."""
    _respostas_db(db, guests=[GUEST_ROW])

    resp = admin_client.get('/admin/respostas?event_id=1')
    body = resp.data.decode()

    assert 'delete-guest-form' in body
    assert 'data-name=' in body
    assert "onsubmit=\"return confirm('Excluir" not in body


# ── Task 5: 413 amigável e sem open redirect ──────────────────────────────────

import pytest
from tests.conftest import flask_app


@pytest.fixture
def tiny_upload_limit(monkeypatch):
    monkeypatch.setitem(flask_app.config, 'MAX_CONTENT_LENGTH', 10)


def test_413_volta_para_pagina_de_origem_com_flash(admin_client, tiny_upload_limit):
    resp = admin_client.post(
        '/admin/convidados/add', data={'name': 'x' * 200},
        headers={'Referer': 'http://localhost/admin/respostas?event_id=1'},
    )
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/respostas?event_id=1')
    with admin_client.session_transaction() as sess:
        assert any('50MB' in msg for _, msg in sess.get('_flashes', []))


@pytest.mark.parametrize('referer', [
    'http://evil.com/admin/respostas',
    'http://localhost//evil.com/x',
    'javascript:alert(1)',
    'http://localhost/\\evil.com',
    'http://localhost/a\x01b',
])
def test_413_nao_redireciona_para_fora(admin_client, tiny_upload_limit, referer):
    resp = admin_client.post('/admin/convidados/add', data={'name': 'x' * 200},
                             headers={'Referer': referer})
    assert resp.status_code == 302
    loc = resp.headers['Location']
    assert 'evil.com' not in loc and 'javascript' not in loc
    assert loc.endswith('/admin/respostas')


def test_mensagem_de_arquivo_invalido_diz_50mb(admin_client, db, upload_dir):
    import io
    resp = admin_client.post(
        '/admin/convidados/add',
        data={'name': 'Ana', 'media_file': (io.BytesIO(b'GIF89a'), 'x.gif')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302
    with admin_client.session_transaction() as sess:
        msgs = [m for _, m in sess.get('_flashes', [])]
    assert 'Arquivo inválido. Use .jpg/.jpeg/.png ou .mp4 (até 50MB).' in msgs
