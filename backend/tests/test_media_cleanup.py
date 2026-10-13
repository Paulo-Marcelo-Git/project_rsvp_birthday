"""Task 7 — arquivos de upload não podem ficar órfãos nem ser apagados enquanto referenciados."""
import io

import pytest

import app as app_module
from tests.conftest import setup_db, GUEST_ROW, EVENT_ROW, JPEG_BYTES


def _jpeg(name='nova.jpg'):
    return (io.BytesIO(JPEG_BYTES), name)


def test_edit_com_imagem_nova_remove_a_antiga(admin_client, db, upload_dir, monkeypatch):
    (upload_dir / 'antiga.jpg').write_bytes(JPEG_BYTES)
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_invitee', lambda c, t, i: {**GUEST_ROW, 'media_url': 'antiga.jpg'})
    monkeypatch.setattr(app_module.repo, 'update_invitee', lambda *a, **k: True)
    monkeypatch.setattr(app_module.repo, 'count_media_references', lambda c, fn: 0)

    resp = admin_client.post('/admin/convidados/1/edit',
                             data={'name': 'Maria', 'response': '', 'media_file': _jpeg()},
                             content_type='multipart/form-data')

    assert resp.status_code == 302
    files = [p.name for p in upload_dir.iterdir()]
    assert 'antiga.jpg' not in files
    assert len(files) == 1   # só a nova


def test_edit_mantem_antiga_se_ainda_referenciada(admin_client, db, upload_dir, monkeypatch):
    (upload_dir / 'antiga.jpg').write_bytes(JPEG_BYTES)
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_invitee', lambda c, t, i: {**GUEST_ROW, 'media_url': 'antiga.jpg'})
    monkeypatch.setattr(app_module.repo, 'update_invitee', lambda *a, **k: True)
    monkeypatch.setattr(app_module.repo, 'count_media_references', lambda c, fn: 1)

    admin_client.post('/admin/convidados/1/edit',
                      data={'name': 'Maria', 'response': '', 'media_file': _jpeg()},
                      content_type='multipart/form-data')

    assert (upload_dir / 'antiga.jpg').exists()


@pytest.mark.parametrize('refs,should_exist', [(0, False), (1, True)])
def test_delete_so_apaga_arquivo_sem_referencia(admin_client, db, upload_dir, monkeypatch, refs, should_exist):
    (upload_dir / 'm.jpg').write_bytes(JPEG_BYTES)
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'get_invitee', lambda c, t, i: {**GUEST_ROW, 'media_url': 'm.jpg'})
    monkeypatch.setattr(app_module.repo, 'delete_invitee', lambda *a, **k: True)
    monkeypatch.setattr(app_module.repo, 'count_media_references', lambda c, fn: refs)

    admin_client.post('/admin/convidados/1/delete')

    assert (upload_dir / 'm.jpg').exists() is should_exist


def test_add_no_limite_do_plano_nao_deixa_arquivo(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'lock_tenant_for_update', lambda c, t: None)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'get_plan_limits', lambda c, t: {'max_invitees': 1, 'max_events': None, 'max_members': None})
    monkeypatch.setattr(app_module.repo, 'count_invitees_for_event', lambda c, t, e: 1)

    resp = admin_client.post('/admin/convidados/add',
                             data={'name': 'Ana', 'event_id': '1', 'media_file': _jpeg()},
                             content_type='multipart/form-data')

    assert resp.status_code == 302
    assert list(upload_dir.iterdir()) == []


def test_add_com_falha_no_insert_remove_arquivo(admin_client, db, upload_dir, monkeypatch):
    setup_db(db)
    monkeypatch.setattr(app_module.repo, 'lock_tenant_for_update', lambda c, t: None)
    monkeypatch.setattr(app_module.repo, 'get_event', lambda c, t, e: EVENT_ROW)
    monkeypatch.setattr(app_module.repo, 'get_plan_limits', lambda c, t: {'max_invitees': None, 'max_events': None, 'max_members': None})
    monkeypatch.setattr(app_module.repo, 'count_invitees_for_event', lambda c, t, e: 0)

    def boom(*a, **k):
        raise RuntimeError('db caiu')
    monkeypatch.setattr(app_module.repo, 'add_invitee', boom)

    with pytest.raises(RuntimeError):
        admin_client.post('/admin/convidados/add',
                          data={'name': 'Ana', 'event_id': '1', 'media_file': _jpeg()},
                          content_type='multipart/form-data')

    assert list(upload_dir.iterdir()) == []
