"""
Testes de rota para /admin/eventos e /admin/eventos/criar,
e para a modificação de /admin/respostas com ?event_id=.
Usa mocks de DB (sem MySQL real), seguindo o padrão de test_admin.py.
"""
import datetime

from tests.conftest import qresult, setup_db, STATS_ROW, TEXTS_ROW, DEFAULT_EVENT_ROW, EVENT_ROW, respostas_db

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
    assert b'app-navbar' in resp.data


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
        qresult(),                             # lock_tenant_for_update FOR UPDATE
        qresult(fetchone=_LIMITS_NONE),      # get_plan_limits (sem limite)
        qresult(fetchone={'n': 1}),           # count_events_for_tenant
        qresult(),                             # INSERT events
        qresult(fetchone={'id': 99}),          # SELECT LAST_INSERT_ID()
    )
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Nova Festa'})
    # Deve redirecionar para respostas com event_id=99
    assert resp.status_code == 302
    assert 'event_id=99' in resp.headers['Location']


def test_criar_evento_trava_tenant_antes_do_count(admin_client, db):
    """Item #6 (corrida TOCTOU): a primeira query da transação deve travar
    a linha do tenant (FOR UPDATE), antes do count+insert — serializa
    requisições concorrentes do mesmo tenant contra o limite do plano."""
    conn = setup_db(
        db,
        qresult(),                             # lock_tenant_for_update FOR UPDATE
        qresult(fetchone=_LIMITS_NONE),         # get_plan_limits
        qresult(fetchone={'n': 1}),             # count_events_for_tenant
        qresult(),                              # INSERT events
        qresult(fetchone={'id': 99}),           # SELECT LAST_INSERT_ID()
    )
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Nova Festa'})
    assert resp.status_code == 302
    first_sql = str(conn.execute.call_args_list[0][0][0])
    assert "FOR UPDATE" in first_sql


def test_criar_evento_bloqueia_limite_plano(admin_client, db):
    """Free plan: max_events=2, já tem 2 → bloqueado com mensagem de plano/limite."""
    setup_db(
        db,
        qresult(),                             # lock_tenant_for_update FOR UPDATE
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

def test_respostas_sem_event_id_redireciona_para_evento_mais_recente(admin_client, db):
    setup_db(db, qresult(all_rows=[{**EVENT_ROW, 'id': 7}, {**EVENT_ROW, 'id': 3}]))
    resp = admin_client.get('/admin/respostas')
    assert resp.status_code == 302
    assert 'event_id=7' in resp.headers['Location']


def test_respostas_event_id_de_outro_tenant_redireciona_para_evento_proprio(admin_client, db):
    setup_db(db, qresult(all_rows=[EVENT_ROW]))   # 999 não está na lista do tenant
    resp = admin_client.get('/admin/respostas?event_id=999')
    assert resp.status_code == 302
    assert 'event_id=1' in resp.headers['Location']


def test_respostas_event_id_nao_numerico_redireciona(admin_client, db):
    setup_db(db, qresult(all_rows=[EVENT_ROW]))
    resp = admin_client.get('/admin/respostas?event_id=abc')
    assert resp.status_code == 302
    assert 'event_id=1' in resp.headers['Location']


def test_respostas_redirect_preserva_busca_com_espaco(admin_client, db):
    setup_db(db, qresult(all_rows=[EVENT_ROW]))
    resp = admin_client.get('/admin/respostas?search=ana%20maria')
    loc = resp.headers['Location']
    assert resp.status_code == 302
    assert 'event_id=1' in loc
    assert 'search=ana+maria' in loc or 'search=ana%20maria' in loc


def test_respostas_com_event_id_valido_filtra_convidados_pelo_evento(admin_client, db):
    conn = respostas_db(db)
    resp = admin_client.get('/admin/respostas?event_id=1')
    assert resp.status_code == 200
    invitees_params = conn.execute.call_args_list[1][0][1]
    assert invitees_params['event_id'] == 1


def test_respostas_member_lista_so_eventos_proprios(member_client, db):
    conn = setup_db(db, qresult(all_rows=[]))
    member_client.get('/admin/respostas')
    assert conn.execute.call_args_list[0][0][1]['owner'] == 2


def test_respostas_sem_eventos_mostra_estado_vazio_para_member(member_client, db):
    setup_db(db, qresult(all_rows=[]))
    resp = member_client.get('/admin/respostas')
    assert resp.status_code == 200
    assert 'Nenhum evento atribuído a você' in resp.data.decode('utf-8')


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


# ── Task 3: SQL de events só via repo.get_event ─────────────────────────────────

def test_set_tema_evento_de_outro_tenant_retorna_404(admin_client, db):
    conn = setup_db(db, qresult(fetchone=None))   # repo.get_event → None
    resp = admin_client.post('/admin/set_tema', data={'theme': 'girl', 'event_id': '77'})
    assert resp.status_code == 404
    sql = str(conn.execute.call_args_list[0][0][0])
    assert 'owner_user_id' in sql   # assinatura do SELECT de repo.get_event
    assert conn.execute.call_count == 1  # nenhum UPDATE


def test_app_nao_monta_sql_de_events():
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent.joinpath('app.py').read_text(encoding='utf-8')
    assert 'FROM events' not in src
