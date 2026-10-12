from tests.conftest import qresult, setup_db, GUEST_ROW, TEXTS_ROW

TOKEN = GUEST_ROW['token']


def test_convite_token_valido_exibe_pagina(client, db):
    # GET: repo.get_invitee_by_token + repo.get_event_texts + repo.get_event_theme
    setup_db(db,
             qresult(fetchone=GUEST_ROW),
             qresult(fetchone=TEXTS_ROW),
             qresult(fetchone={'theme': 'default'}))

    resp = client.get(f'/invite/{TOKEN}')

    assert resp.status_code == 200
    assert 'Você vai comparecer?'.encode() in resp.data


def test_convite_token_invalido_retorna_404(client, db):
    setup_db(db, qresult(fetchone=None))

    resp = client.get('/invite/tokeninexistente')

    assert resp.status_code == 404


def test_convite_post_sim_registra_resposta(client, db):
    # POST: repo.get_invitee_by_token (pending) + repo.update_invitee
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


# ── Task 11: precedência de mídia ─────────────────────────────────────────────

from tests.conftest import qresult, setup_db, GUEST_ROW, TEXTS_ROW


def _invite(client, db, **media):
    setup_db(db,
             qresult(fetchone={**GUEST_ROW, **media}),
             qresult(fetchone=TEXTS_ROW),
             qresult(fetchone={'theme': 'default'}))
    return client.get(f"/invite/{GUEST_ROW['token']}").data.decode('utf-8')


def test_convite_usa_imagem_propria_do_convidado(client, db):
    body = _invite(client, db, media_url='propria.jpg', event_media_url='evento.jpg')
    assert '/uploads/propria.jpg' in body
    assert '/uploads/evento.jpg' not in body


def test_convite_sem_imagem_propria_usa_a_do_evento(client, db):
    body = _invite(client, db, media_url=None, event_media_url='evento.jpg')
    assert '/uploads/evento.jpg' in body


def test_convite_video_do_evento_renderiza_video(client, db):
    body = _invite(client, db, media_url=None, event_media_url='evento.mp4')
    assert '<video id="inviteVideo"' in body


def test_convite_sem_nenhuma_imagem_abre_so_com_texto(client, db):
    body = _invite(client, db, media_url=None, event_media_url=None)
    assert 'class="media-box"' not in body
    assert 'imagen.jpg' not in body
    assert TEXTS_ROW['question_text'] in body
