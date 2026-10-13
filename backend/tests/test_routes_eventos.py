"""
Testes de rota para /admin/eventos e /admin/eventos/criar,
e para a modificação de /admin/respostas com ?event_id=.
Usa mocks de DB (sem MySQL real), seguindo o padrão de test_admin.py.
"""
import datetime
import io

from tests.conftest import JPEG_BYTES, qresult, setup_db, STATS_ROW, TEXTS_ROW, DEFAULT_EVENT_ROW, EVENT_ROW, respostas_db

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


def _eventos_db(db, events=None, limits=None, users=None):
    """Mock para admin_eventos (admin): list_events + get_plan_limits + get_assignable_users."""
    setup_db(
        db,
        qresult(all_rows=events if events is not None else [_EVENT_ROW]),
        qresult(fetchone=limits or _LIMITS_NONE),
        qresult(all_rows=users or []),
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
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/primeiro-evento')


# ── /admin/eventos/criar ────────────────────────────────────────────────────────

def test_criar_evento_exige_login(client):
    resp = client.post('/admin/eventos/criar', data={'title': 'Festa'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_criar_evento_sucesso(admin_client, db, upload_dir):
    """Admin pode criar evento quando abaixo do limite."""
    setup_db(
        db,
        qresult(),                             # lock_tenant_for_update FOR UPDATE
        qresult(fetchone=_LIMITS_NONE),      # get_plan_limits (sem limite)
        qresult(fetchone={'n': 1}),           # count_events_for_tenant
        qresult(),                             # INSERT events
        qresult(fetchone={'id': 99}),          # SELECT LAST_INSERT_ID()
    )
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Nova Festa', 'media_file': (io.BytesIO(JPEG_BYTES), 'convite.jpg')},
                             content_type='multipart/form-data')
    # Deve redirecionar para respostas com event_id=99
    assert resp.status_code == 302
    assert 'event_id=99' in resp.headers['Location']


def test_criar_evento_trava_tenant_antes_do_count(admin_client, db, upload_dir):
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
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Nova Festa', 'media_file': (io.BytesIO(JPEG_BYTES), 'convite.jpg')},
                             content_type='multipart/form-data')
    assert resp.status_code == 302
    first_sql = str(conn.execute.call_args_list[0][0][0])
    assert "FOR UPDATE" in first_sql


def test_criar_evento_bloqueia_limite_plano(admin_client, db, upload_dir):
    """Free plan: max_events=2, já tem 2 → bloqueado com mensagem de plano/limite."""
    setup_db(
        db,
        qresult(),                             # lock_tenant_for_update FOR UPDATE
        qresult(fetchone=_LIMITS_FREE),       # get_plan_limits (max_events=2)
        qresult(fetchone={'n': 2}),            # count_events_for_tenant (já no limite)
        # Redirect para admin_eventos — 2 queries extras:
        qresult(all_rows=[_EVENT_ROW]),        # admin_eventos: list_events
        qresult(fetchone=_LIMITS_FREE),        # admin_eventos: get_plan_limits
        qresult(all_rows=[]),                  # admin_eventos: get_assignable_users
    )
    resp = admin_client.post(
        '/admin/eventos/criar',
        data={'title': 'Extra', 'media_file': (io.BytesIO(JPEG_BYTES), 'convite.jpg')},
        content_type='multipart/form-data',
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
        qresult(all_rows=[_EVENT_ROW]),        # admin_eventos: list_events
        qresult(fetchone=_LIMITS_NONE),        # admin_eventos: get_plan_limits
        qresult(all_rows=[]),                  # admin_eventos: get_assignable_users
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


# ── Task 5: textos no evento selecionado ────────────────────────────────────────

def test_update_textos_grava_no_evento_informado(admin_client, db):
    conn = setup_db(
        db,
        qresult(fetchone={**EVENT_ROW, 'id': 5}),   # repo.get_event
        qresult(fetchone={'extra_texts': None}),     # update_event_texts: SELECT extra_texts
        qresult(),                                   # UPDATE events
    )
    resp = admin_client.post('/admin/textos', data={'event_id': '5', 'question_text': 'Vem?'})
    assert resp.status_code == 302
    assert 'event_id=5' in resp.headers['Location']
    update_params = conn.execute.call_args_list[-1][0][1]
    assert update_params['eid'] == 5
    assert update_params['question_text'] == 'Vem?'
    for call in conn.execute.call_args_list:
        assert 'ORDER BY id DESC' not in str(call[0][0])   # não usa mais get_default_event_id


def test_update_textos_evento_invalido_nao_grava(admin_client, db):
    conn = setup_db(db, qresult(fetchone=None))   # repo.get_event → None
    resp = admin_client.post('/admin/textos', data={'event_id': '999', 'question_text': 'X'})
    assert resp.status_code == 302
    assert conn.execute.call_count == 1
    conn.commit.assert_not_called()


# ── Fix CP3: erros antecipados do add_convidado preservam o evento ─────────────

def test_add_convidado_sem_nome_volta_no_evento_do_form(admin_client, db):
    setup_db(db)
    resp = admin_client.post('/admin/convidados/add', data={'name': '', 'event_id': '4'})
    assert resp.status_code == 302
    assert 'event_id=4' in resp.headers['Location']


def test_add_convidado_arquivo_invalido_volta_no_evento_do_form(admin_client, db, upload_dir):
    import io
    setup_db(db)
    resp = admin_client.post(
        '/admin/convidados/add',
        data={'name': 'Ana', 'event_id': '4',
              'media_file': (io.BytesIO(b'nao sou imagem'), 'falso.jpg')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 302
    assert 'event_id=4' in resp.headers['Location']
    assert list(upload_dir.iterdir()) == []


def test_add_convidado_event_id_invalido_no_erro_nao_quebra(admin_client, db):
    setup_db(db)
    resp = admin_client.post('/admin/convidados/add', data={'name': '', 'event_id': 'abc'})
    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/respostas')


# ── Task 12: imagem obrigatória na criação ──────────────────────────────────────

import app as app_module


def test_criar_evento_sem_imagem_recusa(admin_client, db, upload_dir):
    # redirect → admin_eventos (list_events não-vazio: com lista vazia, a Task 18 redireciona de novo)
    conn = setup_db(db, qresult(all_rows=[_EVENT_ROW]), qresult(fetchone=_LIMITS_NONE), qresult(all_rows=[]))
    resp = admin_client.post('/admin/eventos/criar', data={'title': 'Sem Foto'},
                             follow_redirects=True)
    assert 'A imagem do convite é obrigatória.' in resp.data.decode('utf-8')
    assert not any('INSERT INTO events' in str(c[0][0]) for c in conn.execute.call_args_list)


def test_criar_evento_com_conteudo_invalido_recusa(admin_client, db, upload_dir):
    conn = setup_db(db, qresult(all_rows=[]), qresult(fetchone=_LIMITS_NONE), qresult(all_rows=[]))
    admin_client.post('/admin/eventos/criar',
                      data={'title': 'X', 'media_file': (io.BytesIO(b'<html>'), 'x.jpg')},
                      content_type='multipart/form-data')
    assert not any('INSERT INTO events' in str(c[0][0]) for c in conn.execute.call_args_list)
    assert list(upload_dir.iterdir()) == []


def test_criar_evento_grava_media_url_no_insert(admin_client, db, upload_dir):
    conn = setup_db(db, qresult(), qresult(fetchone=_LIMITS_NONE), qresult(fetchone={'n': 0}),
                    qresult(), qresult(fetchone={'id': 42}))
    admin_client.post('/admin/eventos/criar',
                      data={'title': 'Com Foto', 'media_file': (io.BytesIO(JPEG_BYTES), 'c.jpg')},
                      content_type='multipart/form-data')
    insert_params = conn.execute.call_args_list[3][0][1]
    saved = [p.name for p in upload_dir.iterdir()]
    assert insert_params['media_url'] == saved[0]


def test_criar_evento_falha_no_insert_remove_arquivo(admin_client, db, upload_dir, monkeypatch):
    setup_db(db, qresult(), qresult(fetchone=_LIMITS_NONE), qresult(fetchone={'n': 0}))
    def boom(*a, **k):
        raise RuntimeError('db caiu')
    monkeypatch.setattr(app_module.repo, 'create_event', boom)
    import pytest
    with pytest.raises(RuntimeError):
        admin_client.post('/admin/eventos/criar',
                          data={'title': 'X', 'media_file': (io.BytesIO(JPEG_BYTES), 'c.jpg')},
                          content_type='multipart/form-data')
    assert list(upload_dir.iterdir()) == []


def test_criar_evento_no_limite_nao_salva_arquivo(admin_client, db, upload_dir):
    setup_db(db, qresult(), qresult(fetchone=_LIMITS_FREE), qresult(fetchone={'n': 2}),
             qresult(all_rows=[]), qresult(fetchone=_LIMITS_FREE))
    admin_client.post('/admin/eventos/criar',
                      data={'title': 'X', 'media_file': (io.BytesIO(JPEG_BYTES), 'c.jpg')},
                      content_type='multipart/form-data')
    assert list(upload_dir.iterdir()) == []


# ── Task 15: responsável por evento ─────────────────────────────────────────────

def test_admin_eventos_admin_ve_select_de_responsavel(admin_client, db):
    _eventos_db(db, events=[{**_EVENT_ROW, 'owner_user_id': 1}],
                users=[{'id': 1, 'username': 'testadmin', 'email': 'a@x.com', 'role': 'tenant_admin'},
                       {'id': 2, 'username': 'membertest', 'email': 'm@x.com', 'role': 'member'}])
    body = admin_client.get('/admin/eventos').data.decode('utf-8')
    assert '/admin/eventos/1/responsavel' in body
    assert 'membertest' in body


def test_admin_eventos_member_ve_so_atribuidos_sem_criar(member_client, db):
    conn = setup_db(db, qresult(all_rows=[{**_EVENT_ROW, 'owner_user_id': 2}]),
                    qresult(fetchone=_LIMITS_NONE))
    body = member_client.get('/admin/eventos').data.decode('utf-8')
    assert conn.execute.call_args_list[0][0][1]['owner'] == 2
    assert '#modalCriar' not in body
    assert '/responsavel' not in body


def test_definir_responsavel_sucesso(admin_client, db, monkeypatch):
    import app as app_module
    setup_db(db)
    calls = []
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: _EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'set_event_owner', lambda c, t, e, u: calls.append((t, e, u)) or True)
    resp = admin_client.post('/admin/eventos/1/responsavel', data={'owner_user_id': '2'})
    assert resp.status_code == 302
    assert calls == [(1, 1, 2)]


def test_definir_responsavel_usuario_invalido_nao_comita(admin_client, db, monkeypatch):
    import app as app_module
    conn = setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: _EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'set_event_owner', lambda *a: False)
    resp = admin_client.post('/admin/eventos/1/responsavel', data={'owner_user_id': '999'})
    assert resp.status_code == 302
    conn.commit.assert_not_called()


def test_definir_responsavel_evento_de_outro_tenant_404(admin_client, db, monkeypatch):
    import app as app_module
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: None)
    assert admin_client.post('/admin/eventos/9/responsavel', data={'owner_user_id': '2'}).status_code == 404


def test_definir_responsavel_member_403(member_client, db):
    assert member_client.post('/admin/eventos/1/responsavel', data={'owner_user_id': '2'}).status_code == 403


def test_member_nao_cria_evento(member_client, db):
    assert member_client.post('/admin/eventos/criar', data={'title': 'X'}).status_code == 403
