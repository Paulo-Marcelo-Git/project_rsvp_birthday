"""
Testes de rota para /admin/eventos e /admin/eventos/criar,
e para a modificação de /admin/respostas com ?event_id=.
Usa mocks de DB (sem MySQL real), seguindo o padrão de test_admin.py.
"""
import datetime

from tests.conftest import qresult, setup_db, STATS_ROW, TEXTS_ROW, DEFAULT_EVENT_ROW

_LIMITS_FREE = {'max_events': 2, 'max_invitees': 50, 'max_members': 1}
_LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}
_EVENT_ROW = {
    'id': 1,
    'title': 'Festa da Ana',
    'status': 'draft',
    'theme': 'default',
    'event_date': None,
    'created_at': datetime.datetime(2025, 1, 1),
    'total_invitees': 0,
    'tenant_id': 1,
}


def _eventos_db(db, events=None, limits=None):
    """Mock para admin_eventos: list_events + get_plan_limits."""
    setup_db(
        db,
        qresult(all_rows=events if events is not None else [_EVENT_ROW]),  # repo.list_events
        qresult(fetchone=limits or _LIMITS_NONE),                           # repo.get_plan_limits
    )


# ── /admin/eventos ──────────────────────────────────────────────────────────────

def test_admin_eventos_exige_login(client):
    resp = client.get('/admin/eventos')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_admin_eventos_lista_para_admin(admin_client, db):
    _eventos_db(db)
    resp = admin_client.get('/admin/eventos')
    assert resp.status_code == 200


def test_admin_eventos_lista_vazia(admin_client, db):
    _eventos_db(db, events=[])
    resp = admin_client.get('/admin/eventos')
    assert resp.status_code == 200


# ── /admin/eventos/criar ────────────────────────────────────────────────────────

def test_criar_evento_exige_login(client):
    resp = client.post('/admin/eventos/criar', data={'title': 'Festa'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_criar_evento_sucesso(admin_client, db):
    """Admin pode criar evento quando abaixo do limite."""
    setup_db(
        db,
        qresult(fetchone=_LIMITS_NONE),      # get_plan_limits (sem limite)
        qresult(fetchone={'n': 1}),           # count_events_for_tenant
        qresult(),                             # INSERT events
        qresult(fetchone={'id': 99}),          # SELECT LAST_INSERT_ID()
    )
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Nova Festa'})
    # Deve redirecionar para respostas com event_id=99
    assert resp.status_code == 302
    assert 'event_id=99' in resp.headers['Location']


def test_criar_evento_bloqueia_limite_plano(admin_client, db):
    """Free plan: max_events=2, já tem 2 → bloqueado com mensagem de plano/limite."""
    setup_db(
        db,
        qresult(fetchone=_LIMITS_FREE),       # get_plan_limits (max_events=2)
        qresult(fetchone={'n': 2}),            # count_events_for_tenant (já no limite)
        # Redirect para admin_eventos — 2 queries extras:
        qresult(all_rows=[]),                  # admin_eventos: list_events
        qresult(fetchone=_LIMITS_FREE),        # admin_eventos: get_plan_limits
    )
    resp = admin_client.post(
        '/admin/eventos/criar',
        data={'title': 'Extra'},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    body = resp.data.decode('utf-8').lower()
    assert 'limite' in body or 'plano' in body


def test_criar_evento_titulo_vazio(admin_client, db):
    """Título vazio retorna redirect para admin_eventos com flash."""
    setup_db(
        db,
        # Redirect imediato antes de qualquer query de DB
        qresult(all_rows=[]),                  # admin_eventos: list_events
        qresult(fetchone=_LIMITS_NONE),        # admin_eventos: get_plan_limits
    )
    resp = admin_client.post(
        '/admin/eventos/criar',
        data={'title': ''},
        follow_redirects=True,
    )
    assert resp.status_code == 200


# ── /admin/respostas?event_id= ──────────────────────────────────────────────────

def test_respostas_com_event_id_param(admin_client, db):
    """respostas aceita ?event_id= válido e filtra por ele."""
    setup_db(
        db,
        qresult(fetchone={'id': 5}),           # validar event_id pertence ao tenant
        qresult(all_rows=[]),                   # repo.get_invitees (filtrado por event_id=5)
        qresult(fetchone=STATS_ROW),            # repo.count_invitees_by_response
        # event_id_param=5 → get_default_event_id NÃO é chamado
        qresult(fetchone={'theme': 'default'}), # repo.get_event_theme
        qresult(fetchone=TEXTS_ROW),            # repo.get_event_texts
        qresult(fetchone=_LIMITS_NONE),         # repo.get_plan_limits
        qresult(all_rows=[_EVENT_ROW]),         # repo.list_events
    )
    resp = admin_client.get('/admin/respostas?event_id=5')
    assert resp.status_code == 200


def test_respostas_event_id_invalido_e_ignorado(admin_client, db):
    """event_id que não pertence ao tenant é ignorado (fallback para default)."""
    setup_db(
        db,
        qresult(fetchone=None),                 # validar event_id → None (não pertence ao tenant)
        qresult(all_rows=[]),                   # repo.get_invitees (event_id_param=None)
        qresult(fetchone=STATS_ROW),            # repo.count_invitees_by_response
        qresult(fetchone=DEFAULT_EVENT_ROW),    # repo.get_default_event_id (fallback)
        qresult(fetchone={'theme': 'default'}), # repo.get_event_theme
        qresult(fetchone=TEXTS_ROW),            # repo.get_event_texts
        qresult(fetchone=_LIMITS_NONE),         # repo.get_plan_limits
        qresult(all_rows=[]),                   # repo.list_events
    )
    resp = admin_client.get('/admin/respostas?event_id=999')
    assert resp.status_code == 200


def test_respostas_event_id_nao_numerico_ignorado(admin_client, db):
    """event_id não numérico (ex: 'abc') é silenciosamente ignorado."""
    setup_db(
        db,
        # event_id_param=None (parse fallback) → sem query de validação
        qresult(all_rows=[]),                   # repo.get_invitees
        qresult(fetchone=STATS_ROW),            # repo.count_invitees_by_response
        qresult(fetchone=DEFAULT_EVENT_ROW),    # repo.get_default_event_id
        qresult(fetchone={'theme': 'default'}), # repo.get_event_theme
        qresult(fetchone=TEXTS_ROW),            # repo.get_event_texts
        qresult(fetchone=_LIMITS_NONE),         # repo.get_plan_limits
        qresult(all_rows=[]),                   # repo.list_events
    )
    resp = admin_client.get('/admin/respostas?event_id=abc')
    assert resp.status_code == 200


# ── /admin/set_tema ─────────────────────────────────────────────────────────────

def test_set_tema_exige_admin(admin_client, db):
    """set_tema returns redirect after setting theme."""
    from tests.conftest import qresult, setup_db
    setup_db(
        db,
        qresult(fetchone={'id': 1}),  # SELECT id FROM events (ownership check)
        qresult(),                     # UPDATE events SET theme
    )
    resp = admin_client.post('/admin/set_tema',
                             data={'theme': 'girl', 'event_id': '1'})
    assert resp.status_code == 302


def test_set_tema_rejeita_tema_invalido(admin_client, db):
    resp = admin_client.post('/admin/set_tema',
                             data={'theme': 'purple', 'event_id': '1'})
    assert resp.status_code == 400


# ── /admin/exportar_xlsx?event_id= ──────────────────────────────────────────────

def test_exportar_xlsx_com_event_id_valido_filtra(admin_client, db):
    """exportar_xlsx aceita ?event_id= válido e filtra por ele."""
    setup_db(
        db,
        qresult(fetchone={'id': 5}),  # validar event_id pertence ao tenant
        qresult(all_rows=[]),          # repo.get_invitees (filtrado por event_id=5)
    )
    resp = admin_client.get('/admin/exportar_xlsx?event_id=5')
    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.content_type


def test_exportar_xlsx_event_id_invalido_e_ignorado(admin_client, db):
    """event_id que não pertence ao tenant é ignorado (exporta sem filtro)."""
    setup_db(
        db,
        qresult(fetchone=None),  # validar event_id → não pertence ao tenant
        qresult(all_rows=[]),     # repo.get_invitees (event_id_param=None)
    )
    resp = admin_client.get('/admin/exportar_xlsx?event_id=999')
    assert resp.status_code == 200
