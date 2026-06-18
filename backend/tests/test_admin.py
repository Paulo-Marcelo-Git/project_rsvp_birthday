from tests.conftest import (
    qresult, setup_db,
    GUEST_ROW, COUNT_ROW, STATS_ROW, EMPTY_SETTINGS,
)


def _respostas_db(db, guests=None):
    """Configura as 4 queries que respostas() sempre executa."""
    return setup_db(
        db,
        qresult(all_rows=guests or []),   # SELECT convidados
        qresult(fetchone=COUNT_ROW),       # SELECT COUNT(*)
        qresult(fetchone=STATS_ROW),       # SELECT SUM(...)
        qresult(all_rows=EMPTY_SETTINGS),  # SELECT settings
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


# ── adicionar convidado ───────────────────────────────────────────────────────

def test_add_convidado_cria_registro(admin_client, db):
    conn = setup_db(db, qresult())

    resp = admin_client.post('/admin/convidados/add', data={
        'name': 'Pedro Oliveira',
        'email': 'pedro@email.com',
        'phone': '',
    })

    assert resp.status_code == 302
    conn.execute.assert_called_once()
    conn.commit.assert_called_once()


def test_add_convidado_sem_nome_nao_salva(admin_client, db):
    resp = admin_client.post('/admin/convidados/add', data={'name': ''})

    # Nenhuma conexão com o banco deve ser feita
    assert db.connect.call_count == 0
    assert resp.status_code == 302


# ── excluir convidado ─────────────────────────────────────────────────────────

def test_delete_convidado_remove_registro(admin_client, db):
    guest = {'name': 'Ana', 'media_file': None, 'user_id': None}
    setup_db(db,
             qresult(fetchone=guest),  # SELECT (ownership check)
             qresult())                 # DELETE

    resp = admin_client.post('/admin/convidados/1/delete')

    assert resp.status_code == 302


def test_delete_convidado_inexistente_retorna_404(admin_client, db):
    setup_db(db, qresult(fetchone=None))

    resp = admin_client.post('/admin/convidados/999/delete')

    assert resp.status_code == 404


# ── editar convidado ──────────────────────────────────────────────────────────

def test_edit_convidado_atualiza_registro(admin_client, db):
    guest = {'user_id': None}
    conn = setup_db(db,
                    qresult(fetchone=guest),  # SELECT (ownership check)
                    qresult())                 # UPDATE

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


# ── exportar xlsx ─────────────────────────────────────────────────────────────

def test_exportar_xlsx_retorna_arquivo(admin_client, db):
    setup_db(db, qresult(all_rows=[]))

    resp = admin_client.get('/admin/exportar_xlsx')

    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.content_type
