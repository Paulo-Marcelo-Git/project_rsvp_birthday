from tests.conftest import (
    qresult, setup_db,
    GUEST_ROW, STATS_ROW, DEFAULT_EVENT_ROW, TEXTS_ROW,
)


def _respostas_db(db, guests=None):
    return setup_db(
        db,
        qresult(all_rows=guests or []),
        qresult(fetchone=STATS_ROW),
        qresult(fetchone=DEFAULT_EVENT_ROW),
        qresult(fetchone=TEXTS_ROW),
    )


# ── Fix: page=abc não deve crashar (ValueError) ───────────────────────────────

def test_page_invalido_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?page=abc')

    assert resp.status_code == 200


def test_page_negativo_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?page=-10')

    assert resp.status_code == 200


def test_page_float_retorna_200(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?page=1.5')

    assert resp.status_code == 200


# ── Fix: XSS — nomes não devem aparecer crus em contexto JavaScript ───────────

def test_xss_script_tag_no_nome_e_escapado(admin_client, db):
    guest_xss = {**GUEST_ROW, 'name': '<script>alert(1)</script>'}
    _respostas_db(db, guests=[guest_xss])

    resp = admin_client.get('/admin/respostas')
    body = resp.data.decode()

    assert '<script>alert(1)</script>' not in body
    assert '&lt;script&gt;' in body


def test_xss_aspas_simples_no_nome_nao_quebra_js(admin_client, db):
    """Nome com aspas simples não deve aparecer em onsubmit inline."""
    guest_xss = {**GUEST_ROW, 'name': "'); alert(document.cookie); ('"}
    _respostas_db(db, guests=[guest_xss])

    resp = admin_client.get('/admin/respostas')
    body = resp.data.decode()

    # A correção usa data-name= em vez de onsubmit inline
    assert "onsubmit=\"return confirm('Excluir" not in body
    assert 'delete-guest-form' in body


def test_formulario_exclusao_usa_data_attribute(admin_client, db):
    """Formulário de exclusão deve usar classe e data-name, não onsubmit inline."""
    _respostas_db(db, guests=[GUEST_ROW])

    resp = admin_client.get('/admin/respostas')
    body = resp.data.decode()

    assert 'delete-guest-form' in body
    assert 'data-name=' in body
    assert "onsubmit=\"return confirm('Excluir" not in body
