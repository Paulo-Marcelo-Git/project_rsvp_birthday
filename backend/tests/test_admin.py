from tests.conftest import (
    qresult, setup_db,
    GUEST_ROW, STATS_ROW, DEFAULT_EVENT_ROW, TEXTS_ROW,
)

_LIMITS_FREE = {'max_events': 2, 'max_invitees': 50, 'max_members': 1}
_LIMITS_NONE = {'max_events': None, 'max_invitees': None, 'max_members': None}
_COUNT_ZERO  = {'n': 0}
_COUNT_49    = {'n': 49}
_COUNT_50    = {'n': 50}   # at max_invitees for free plan
_COUNT_ONE   = {'n': 1}    # at max_members for free plan


def _respostas_db(db, guests=None, limits=None):
    """Configura as 5 queries que respostas() executa via repo."""
    return setup_db(
        db,
        qresult(all_rows=guests or []),                    # repo.get_invitees
        qresult(fetchone=STATS_ROW),                        # repo.count_invitees_by_response
        qresult(fetchone=DEFAULT_EVENT_ROW),                # repo.get_default_event_id
        qresult(fetchone=TEXTS_ROW),                        # repo.get_event_texts
        qresult(fetchone=limits or _LIMITS_NONE),           # repo.get_plan_limits
    )


# ── respostas ─────────────────────────────────────────────────────────────────

def test_respostas_exige_login(client):
    resp = client.get('/admin/respostas')
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_respostas_carrega_para_admin(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas')

    assert resp.status_code == 200


def test_respostas_exibe_convidado(admin_client, db):
    _respostas_db(db, guests=[GUEST_ROW])

    resp = admin_client.get('/admin/respostas')

    assert resp.status_code == 200
    assert b'Maria Silva' in resp.data


def test_respostas_busca_por_nome(admin_client, db):
    _respostas_db(db)

    resp = admin_client.get('/admin/respostas?search=maria')

    assert resp.status_code == 200


def test_respostas_esconde_botao_usuarios_free(admin_client, db):
    """Free plan (max_members=1): botão Usuários NÃO aparece no painel principal."""
    _respostas_db(db, limits=_LIMITS_FREE)
    resp = admin_client.get('/admin/respostas')
    assert resp.status_code == 200
    assert b'/admin/usuarios' not in resp.data


def test_respostas_mostra_botao_usuarios_ilimitado(admin_client, db):
    """Business plan (max_members=None): botão Usuários aparece no painel principal."""
    _respostas_db(db, limits=_LIMITS_NONE)
    resp = admin_client.get('/admin/respostas')
    assert resp.status_code == 200
    assert b'/admin/usuarios' in resp.data


# ── adicionar convidado ───────────────────────────────────────────────────────

def test_add_convidado_cria_registro(admin_client, db):
    conn = setup_db(db,
                    qresult(fetchone=DEFAULT_EVENT_ROW),   # get_default_event_id
                    qresult(fetchone=_LIMITS_FREE),         # get_plan_limits
                    qresult(fetchone=_COUNT_ZERO),          # count_invitees_for_event
                    qresult())                              # add_invitee

    resp = admin_client.post('/admin/convidados/add', data={
        'name': 'Pedro Oliveira',
        'email': 'pedro@email.com',
        'phone': '',
    })

    assert resp.status_code == 302
    assert conn.execute.call_count == 4
    conn.commit.assert_called_once()


def test_add_convidado_no_limite_nao_cria(admin_client, db):
    """Quando count_invitees == max_invitees, deve redirecionar com flash e NÃO inserir."""
    conn = setup_db(db,
                    qresult(fetchone=DEFAULT_EVENT_ROW),  # get_default_event_id
                    qresult(fetchone=_LIMITS_FREE),        # get_plan_limits (max=50)
                    qresult(fetchone=_COUNT_50))           # count_invitees_for_event (=50)

    resp = admin_client.post('/admin/convidados/add', data={
        'name': 'Convidado Extra',
        'email': 'extra@email.com',
        'phone': '',
    })

    assert resp.status_code == 302
    assert conn.execute.call_count == 3   # event_id + limits + count; sem INSERT
    conn.commit.assert_not_called()


def test_add_convidado_ilimitado_cria(admin_client, db):
    """Com max_invitees=None (business), deve inserir mesmo com contagem alta."""
    conn = setup_db(db,
                    qresult(fetchone=DEFAULT_EVENT_ROW),  # get_default_event_id
                    qresult(fetchone=_LIMITS_NONE),        # get_plan_limits (unlimited)
                    qresult(fetchone={'n': 9999}),         # count_invitees_for_event
                    qresult())                             # add_invitee

    resp = admin_client.post('/admin/convidados/add', data={
        'name': 'VIP Sem Limite',
        'email': 'vip@email.com',
        'phone': '',
    })

    assert resp.status_code == 302
    assert conn.execute.call_count == 4
    conn.commit.assert_called_once()


def test_add_convidado_sem_nome_nao_salva(admin_client, db):
    resp = admin_client.post('/admin/convidados/add', data={'name': ''})

    # Nenhuma conexão com o banco deve ser feita
    assert db.connect.call_count == 0
    assert resp.status_code == 302


# ── excluir convidado ─────────────────────────────────────────────────────────

def test_delete_convidado_remove_registro(admin_client, db):
    guest = {'name': 'Ana', 'media_url': None, 'event_owner_user_id': None}
    setup_db(db,
             qresult(fetchone=guest),  # repo.get_invitee
             qresult())                 # repo.delete_invitee

    resp = admin_client.post('/admin/convidados/1/delete')

    assert resp.status_code == 302


def test_delete_convidado_inexistente_retorna_404(admin_client, db):
    setup_db(db, qresult(fetchone=None))

    resp = admin_client.post('/admin/convidados/999/delete')

    assert resp.status_code == 404


# ── editar convidado ──────────────────────────────────────────────────────────

def test_edit_convidado_atualiza_registro(admin_client, db):
    guest = {'event_owner_user_id': None}
    conn = setup_db(db,
                    qresult(fetchone=guest),  # repo.get_invitee
                    qresult())                 # repo.update_invitee

    resp = admin_client.post('/admin/convidados/1/edit', data={
        'name': 'Maria Atualizada',
        'email': '',
        'phone': '',
        'custom_message': '',
        'response': '',
    })

    assert resp.status_code == 302
    conn.commit.assert_called_once()


def test_edit_convidado_inexistente_retorna_404(admin_client, db):
    setup_db(db, qresult(fetchone=None))

    resp = admin_client.post('/admin/convidados/999/edit', data={'name': 'X'})

    assert resp.status_code == 404


# ── add_usuario com enforcement de limite ─────────────────────────────────────

def test_add_usuario_no_limite_nao_cria(admin_client, db):
    """Quando count_members == max_members, deve redirecionar com flash e NÃO inserir."""
    conn = setup_db(db,
                    qresult(fetchone=_LIMITS_FREE),  # get_plan_limits (max_members=1)
                    qresult(fetchone=_COUNT_ONE))     # count_members_for_tenant (=1)

    resp = admin_client.post('/admin/usuarios/add', data={
        'username': 'novo',
        'email': 'novo@email.com',
    })

    assert resp.status_code == 302
    assert conn.execute.call_count == 2   # limits + count; sem INSERT
    conn.commit.assert_not_called()


def test_add_usuario_abaixo_limite_cria(admin_client, db):
    """Com count_members < max_members, deve criar o usuário."""
    conn = setup_db(db,
                    qresult(fetchone=_LIMITS_FREE),     # get_plan_limits (max_members=1)
                    qresult(fetchone=_COUNT_ZERO),       # count_members_for_tenant (=0)
                    qresult(),                           # add_user INSERT
                    qresult(fetchone={'id': 99}))        # LAST_INSERT_ID

    resp = admin_client.post('/admin/usuarios/add', data={
        'username': 'novo',
        'email': 'novo@email.com',
    })

    assert resp.status_code == 302
    conn.commit.assert_called_once()


def test_add_usuario_ilimitado_cria(admin_client, db):
    """Com max_members=None (business), deve criar mesmo com contagem alta."""
    conn = setup_db(db,
                    qresult(fetchone=_LIMITS_NONE),     # get_plan_limits (unlimited)
                    qresult(fetchone={'n': 50}),         # count_members_for_tenant
                    qresult(),                           # add_user INSERT
                    qresult(fetchone={'id': 100}))       # LAST_INSERT_ID

    resp = admin_client.post('/admin/usuarios/add', data={
        'username': 'enterprise',
        'email': 'enterprise@empresa.com',
    })

    assert resp.status_code == 302
    conn.commit.assert_called_once()


# ── exportar xlsx ─────────────────────────────────────────────────────────────

def test_exportar_xlsx_retorna_arquivo(admin_client, db):
    setup_db(db, qresult(all_rows=[]))

    resp = admin_client.get('/admin/exportar_xlsx')

    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.content_type
