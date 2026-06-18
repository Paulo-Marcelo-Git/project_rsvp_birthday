from tests.conftest import qresult, setup_db, GUEST_ROW

TOKEN = GUEST_ROW['token']

SETTINGS_ROWS = [
    {'key': 'question_text', 'value': 'Você vai comparecer?'},
    {'key': 'yes_text',      'value': 'Sim'},
    {'key': 'no_text',       'value': 'Não'},
    {'key': 'post_yes_text', 'value': 'Obrigado!'},
    {'key': 'post_no_text',  'value': 'Sentiremos sua falta!'},
]


def test_convite_token_valido_exibe_pagina(client, db):
    # GET: 1 SELECT invitee + 1 SELECT settings
    setup_db(db,
             qresult(fetchone=GUEST_ROW),
             qresult(all_rows=SETTINGS_ROWS))

    resp = client.get(f'/invite/{TOKEN}')

    assert resp.status_code == 200
    assert 'Você vai comparecer?'.encode() in resp.data


def test_convite_token_invalido_retorna_404(client, db):
    setup_db(db, qresult(fetchone=None))

    resp = client.get('/invite/tokeninexistente')

    assert resp.status_code == 404


def test_convite_post_sim_registra_resposta(client, db):
    # POST: 1 SELECT invitee + 1 UPDATE
    conn = setup_db(db,
                    qresult(fetchone=GUEST_ROW),
                    qresult())

    resp = client.post(f'/invite/{TOKEN}', data={
        'response': 'yes',
        'observacao': 'Estarei lá!',
    })

    assert resp.status_code == 302
    assert conn.commit.called


def test_convite_post_nao_registra_resposta(client, db):
    conn = setup_db(db,
                    qresult(fetchone=GUEST_ROW),
                    qresult())

    resp = client.post(f'/invite/{TOKEN}', data={'response': 'no'})

    assert resp.status_code == 302
    assert conn.commit.called


def test_convite_ja_respondido_nao_atualiza(client, db):
    already_responded = {**GUEST_ROW, 'response': 'yes'}
    conn = setup_db(db, qresult(fetchone=already_responded))

    resp = client.post(f'/invite/{TOKEN}', data={'response': 'no'})

    # Apenas 1 execute (SELECT), sem UPDATE nem commit
    assert conn.execute.call_count == 1
    assert not conn.commit.called
    assert resp.status_code == 302


def test_convite_resposta_invalida_ignorada(client, db):
    conn = setup_db(db, qresult(fetchone=GUEST_ROW))

    resp = client.post(f'/invite/{TOKEN}', data={'response': 'maybe'})

    assert conn.execute.call_count == 1
    assert not conn.commit.called
    assert resp.status_code == 302
