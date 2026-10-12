"""Task 10 — upload/troca da imagem padrão do evento."""
import io

import pytest

import app as app_module
from tests.conftest import setup_db, respostas_db, EVENT_ROW, JPEG_BYTES, MP4_BYTES


def _post(client, event_id=1, data=JPEG_BYTES, name='convite.jpg'):
    return client.post(f'/admin/eventos/{event_id}/imagem',
                       data={'media_file': (io.BytesIO(data), name)},
                       content_type='multipart/form-data')


def test_upload_imagem_evento_grava_e_remove_anterior(admin_client, db, upload_dir, monkeypatch):
    (upload_dir / 'velha.jpg').write_bytes(JPEG_BYTES)
    setup_db(db)
    saved = {}
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: {**EVENT_ROW, 'media_url': 'velha.jpg'})
    def fake_set(c, t, e, fn):
        saved['fn'] = fn
        return 'velha.jpg'
    monkeypatch.setattr(app_module.repo, 'set_event_media', fake_set)
    monkeypatch.setattr(app_module.repo, 'count_media_references', lambda c, fn: 0)

    resp = _post(admin_client)

    assert resp.status_code == 302
    assert resp.headers['Location'].endswith('/admin/respostas?event_id=1')
    assert not (upload_dir / 'velha.jpg').exists()
    assert (upload_dir / saved['fn']).exists()


def test_upload_imagem_evento_aceita_mp4(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'set_event_media', lambda c, t, e, fn: None)
    resp = _post(admin_client, data=MP4_BYTES, name='convite.mp4')
    assert resp.status_code == 302
    assert len(list(upload_dir.iterdir())) == 1


def test_upload_imagem_evento_conteudo_invalido_nao_grava(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    called = []
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'set_event_media', lambda *a: called.append(a))
    resp = _post(admin_client, data=b'<html>', name='x.jpg')
    assert resp.status_code == 302
    assert called == []
    assert list(upload_dir.iterdir()) == []


def test_upload_imagem_evento_de_outro_tenant_404(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: None)
    resp = _post(admin_client, event_id=999)
    assert resp.status_code == 404
    assert list(upload_dir.iterdir()) == []


def test_upload_imagem_evento_member_nao_responsavel_404(member_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: {**EVENT_ROW, 'owner_user_id': 99})
    resp = _post(member_client)
    assert resp.status_code == 404
    assert list(upload_dir.iterdir()) == []


def test_upload_imagem_evento_falha_no_banco_remove_arquivo(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: EVENT_ROW)
    def boom(*a):
        raise RuntimeError('db caiu')
    monkeypatch.setattr(app_module.repo, 'set_event_media', boom)
    with pytest.raises(RuntimeError):
        _post(admin_client)
    assert list(upload_dir.iterdir()) == []


def test_respostas_mostra_bloco_imagem_com_miniatura(admin_client, db):
    respostas_db(db)
    body = admin_client.get('/admin/respostas?event_id=1').data.decode('utf-8')
    assert 'id="event-media-card"' in body
    assert '/uploads/evento.jpg' in body
    assert '/admin/eventos/1/imagem' in body


def test_respostas_bloco_imagem_sem_imagem_mostra_alerta(admin_client, db):
    respostas_db(db, events=[{**EVENT_ROW, 'media_url': None}])
    body = admin_client.get('/admin/respostas?event_id=1').data.decode('utf-8')
    assert 'Este evento ainda não tem imagem do convite.' in body
