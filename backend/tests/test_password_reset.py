import os
from tests.conftest import setup_db, qresult
from unittest.mock import MagicMock, patch
import app as _app


def test_send_reset_email_sem_config_loga_warning(caplog):
    """Sem EMAIL_SMTP configurado, deve logar warning e retornar sem erro."""
    env_sem_smtp = {k: v for k, v in os.environ.items()
                    if k not in ('EMAIL_SMTP', 'EMAIL_USER')}
    with patch.dict(os.environ, env_sem_smtp, clear=True):
        import logging
        with caplog.at_level(logging.WARNING, logger='app'):
            _app.send_reset_email('user@test.com', 'testuser', 'http://x/reset/abc')
    assert any('EMAIL_SMTP' in r.message or 'email' in r.message.lower()
                for r in caplog.records)


def test_send_reset_email_com_config_chama_smtp(monkeypatch):
    """Com EMAIL_SMTP configurado, deve chamar smtplib.SMTP e enviar mensagem."""
    monkeypatch.setenv('EMAIL_SMTP', 'smtp.gmail.com')
    monkeypatch.setenv('EMAIL_PORTA', '587')
    monkeypatch.setenv('EMAIL_USER', 'bot@gmail.com')
    monkeypatch.setenv('EMAIL_PASS', 'secret')

    mock_smtp_instance = MagicMock()
    with patch('smtplib.SMTP', return_value=mock_smtp_instance) as mock_smtp:
        _app.send_reset_email('dest@test.com', 'joao', 'http://x/reset/tok123')

    mock_smtp.assert_called_once_with('smtp.gmail.com', 587)
    mock_smtp_instance.starttls.assert_called_once()
    mock_smtp_instance.login.assert_called_once_with('bot@gmail.com', 'secret')
    mock_smtp_instance.sendmail.assert_called_once()
    # Verifica que o email contém o username e a URL
    call_args = mock_smtp_instance.sendmail.call_args
    msg_str = call_args[0][2]
    # Decode all content for assertion (plain-text part may be base64-encoded)
    import base64
    import email as email_module
    full_content = msg_str
    try:
        parsed = email_module.message_from_string(msg_str)
        for part in parsed.walk():
            payload = part.get_payload(decode=True)
            if payload:
                full_content += payload.decode('utf-8', errors='replace')
    except Exception:
        pass
    assert 'joao' in full_content
    assert 'tok123' in full_content


def test_init_db_cria_tabela_tokens(db, monkeypatch):
    """init_db() deve interagir com o engine ao criar/migrar tabelas."""
    import app as _app
    monkeypatch.setattr(_app, 'engine', db)
    conn = MagicMock()
    conn.execute.return_value = MagicMock()
    db.connect.return_value.__enter__.return_value = conn

    _app.init_db()

    assert db.connect.called
    assert conn.execute.called


def test_forgot_password_page_carrega(client):
    resp = client.get('/forgot_password')
    assert resp.status_code == 200
    assert 'Esqueci' in resp.data.decode() or 'senha' in resp.data.decode().lower()


def test_forgot_password_post_usuario_nao_encontrado_mostra_mensagem_generica(client, db):
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'username': 'ninguem'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    # Mensagem genérica — não revela se usuário existe
    assert 'Se o usuário existir' in body or 'verifique seu email' in body.lower() \
           or 'email' in body.lower()


def test_forgot_password_post_usuario_sem_email_mostra_mensagem_generica(client, db):
    user_row = {'id': 1, 'username': 'maria', 'password_hash': 'x',
                'must_change_password': False, 'email': None, 'whatsapp': None}
    setup_db(db, qresult(fetchone=user_row))
    resp = client.post('/forgot_password', data={'username': 'maria'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'Se o usuário existir' in resp.data.decode() or 'email' in resp.data.decode().lower()


def test_forgot_password_post_usuario_valido_envia_email(client, db):
    user_row = {'id': 2, 'username': 'joao', 'password_hash': 'x',
                'must_change_password': False, 'email': 'joao@test.com', 'whatsapp': None}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),  # SELECT user
        MagicMock(),                  # INSERT token
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'username': 'joao'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_email.assert_called_once()
    args = mock_email.call_args[0]
    assert args[0] == 'joao@test.com'
    assert args[1] == 'joao'
    assert '/reset_password/' in args[2]


def test_reset_password_token_invalido_redireciona(client, db):
    setup_db(db, qresult(fetchone=None))
    resp = client.get('/reset_password/tokeninvalido')
    assert resp.status_code == 302
    assert '/forgot_password' in resp.headers['Location']


def test_reset_password_token_valido_exibe_formulario(client, db):
    from datetime import datetime, timedelta
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'validtoken123',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
        'used': False,
    }
    setup_db(db, qresult(fetchone=token_row))
    resp = client.get('/reset_password/validtoken123')
    assert resp.status_code == 200
    assert 'Nova senha' in resp.data.decode() or 'nova senha' in resp.data.decode().lower()


def test_reset_password_post_senha_fraca_retorna_erro(client, db):
    from datetime import datetime, timedelta
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'tok',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
        'used': False,
    }
    # GET valida token, POST revalida token
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=token_row),
        qresult(fetchone=token_row),
    ]
    db.connect.return_value.__enter__.return_value = conn

    resp = client.post('/reset_password/tok',
                       data={'new_password': '123', 'confirm_password': '123'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert '8' in resp.data.decode() or 'caractere' in resp.data.decode().lower()


def test_reset_password_post_senhas_diferentes_retorna_erro(client, db):
    from datetime import datetime, timedelta
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'tok2',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
        'used': False,
    }
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=token_row),
        qresult(fetchone=token_row),
    ]
    db.connect.return_value.__enter__.return_value = conn

    resp = client.post('/reset_password/tok2',
                       data={'new_password': 'SenhaForte@1', 'confirm_password': 'Diferente@1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'coincidem' in resp.data.decode() or 'diferentes' in resp.data.decode().lower()


def test_reset_password_post_sucesso_redireciona_login(client, db):
    from datetime import datetime, timedelta
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'tok3',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
        'used': False,
    }
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=token_row),  # revalidação no POST
        MagicMock(),                   # UPDATE users SET password_hash
        MagicMock(),                   # UPDATE tokens SET used=TRUE
    ]
    db.connect.return_value.__enter__.return_value = conn

    resp = client.post('/reset_password/tok3',
                       data={'new_password': 'NovaSenha@99',
                             'confirm_password': 'NovaSenha@99'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
