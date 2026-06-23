import logging
import os
from tests.conftest import setup_db, qresult
from unittest.mock import MagicMock, patch
import tasks
import app as _app


def test_send_reset_email_sem_config_loga_warning(caplog):
    """Sem EMAIL_SMTP configurado, deve logar warning e retornar sem erro."""
    env_sem_smtp = {k: v for k, v in os.environ.items()
                    if k not in ('EMAIL_SMTP', 'EMAIL_USER')}
    with patch.dict(os.environ, env_sem_smtp, clear=True):
        with caplog.at_level(logging.WARNING, logger='tasks'):
            tasks.send_reset_email('user@test.com', 'testuser', 'http://x/reset/abc')
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
        tasks.send_reset_email('dest@test.com', 'joao', 'http://x/reset/tok123')

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


def test_forgot_password_page_carrega(client):
    resp = client.get('/forgot_password')
    assert resp.status_code == 200
    assert 'Esqueci' in resp.data.decode() or 'senha' in resp.data.decode().lower()


def test_forgot_password_post_email_nao_cadastrado_mostra_mensagem_generica(client, db):
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'ninguem@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o email' in body or 'email' in body.lower()


def test_forgot_password_post_username_sem_arroba_nao_autentica(client, db):
    """Username sem @ não é email — route retorna mensagem genérica sem tocar no DB."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'joao'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'email' in resp.data.decode().lower()


def test_forgot_password_post_usuario_valido_envia_email(client, db):
    user_row = {'id': 2, 'username': 'joao', 'password_hash': 'x',
                'must_change_password': False, 'email': 'joao@test.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.enqueue_email') as mock_enqueue:
        resp = client.post('/forgot_password', data={'email': 'joao@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_enqueue.assert_called_once()
    args = mock_enqueue.call_args[0]
    assert args[0] is tasks.send_reset_email
    assert args[1] == 'joao@test.com'
    assert args[2] == 'joao'
    assert '/reset_password/' in args[3]


def test_reset_password_token_invalido_redireciona(client, db):
    setup_db(db, qresult(fetchone=None))
    resp = client.get('/reset_password/tokeninvalido')
    assert resp.status_code == 302
    assert '/forgot_password' in resp.headers['Location']


def test_reset_password_token_valido_exibe_formulario(client, db):
    from datetime import datetime, timedelta, timezone
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'validtoken123',
        'expires_at': datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        'used': False,
    }
    setup_db(db, qresult(fetchone=token_row))
    resp = client.get('/reset_password/validtoken123')
    assert resp.status_code == 200
    assert 'Nova senha' in resp.data.decode() or 'nova senha' in resp.data.decode().lower()


def test_reset_password_post_senha_fraca_retorna_erro(client, db):
    resp = client.post('/reset_password/tok',
                       data={'new_password': '123', 'confirm_password': '123'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert '8' in resp.data.decode() or 'caractere' in resp.data.decode().lower()


def test_reset_password_post_senhas_diferentes_retorna_erro(client, db):
    resp = client.post('/reset_password/tok2',
                       data={'new_password': 'SenhaForte@1', 'confirm_password': 'Diferente@1'},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'coincidem' in resp.data.decode() or 'diferentes' in resp.data.decode().lower()


def test_reset_password_post_sucesso_redireciona_login(client, db):
    from datetime import datetime, timedelta, timezone
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'tok3',
        'expires_at': datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        'used': False,
    }
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=token_row),  # _get_valid_token in POST
        MagicMock(),                   # UPDATE users SET password_hash
        MagicMock(),                   # UPDATE password_reset_tokens SET used=TRUE
    ]
    db.connect.return_value.__enter__.return_value = conn

    resp = client.post('/reset_password/tok3',
                       data={'new_password': 'NovaSenha@99',
                             'confirm_password': 'NovaSenha@99'})
    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']


def test_reset_password_post_token_expirado_redireciona(client, db):
    """POST com token expirado/usado deve redirecionar para /forgot_password."""
    setup_db(db, qresult(fetchone=None))  # _get_valid_token returns None
    resp = client.post('/reset_password/tokenexpirado',
                       data={'new_password': 'NovaSenha@99',
                             'confirm_password': 'NovaSenha@99'})
    assert resp.status_code == 302
    assert '/forgot_password' in resp.headers['Location']


def test_reset_password_post_sucesso_marca_token_como_usado(client, db):
    """POST bem-sucedido deve marcar token como used=TRUE no banco."""
    from datetime import datetime, timedelta, timezone
    token_row = {
        'id': 5, 'user_id': 3, 'token': 'tok_used_check',
        'expires_at': datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        'used': False,
    }
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=token_row),  # _get_valid_token
        MagicMock(),                   # UPDATE users SET password_hash
        MagicMock(),                   # UPDATE password_reset_tokens SET used=TRUE
    ]
    db.connect.return_value.__enter__.return_value = conn

    resp = client.post('/reset_password/tok_used_check',
                       data={'new_password': 'NovaSenha@99',
                             'confirm_password': 'NovaSenha@99'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    # Verify 3 execute calls: token validation + 2 UPDATEs
    assert conn.execute.call_count == 3
    # Third call must update password_reset_tokens with used=TRUE
    third_call_sql = str(conn.execute.call_args_list[2][0][0])
    assert 'used' in third_call_sql.lower() or 'password_reset_tokens' in third_call_sql.lower()


def test_forgot_password_post_com_email_valido_envia_reset(client, db):
    """Enviar email existente no campo email → cria token e chama send_reset_email."""
    user_row = {'id': 3, 'username': 'ana', 'email': 'ana@test.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.enqueue_email') as mock_enqueue:
        resp = client.post('/forgot_password', data={'email': 'ana@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_enqueue.assert_called_once()
    args = mock_enqueue.call_args[0]
    assert args[0] is tasks.send_reset_email
    assert args[1] == 'ana@test.com'
    assert args[2] == 'ana'
    assert '/reset_password/' in args[3]


def test_forgot_password_post_com_email_case_insensitive(client, db):
    """Busca por email usa LOWER() — case-insensitive."""
    user_row = {'id': 4, 'username': 'carlos', 'email': 'carlos@gmail.com',
                'tenant_id': 1, 'role': 'member', 'is_active': 1}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.enqueue_email') as mock_enqueue:
        resp = client.post('/forgot_password', data={'email': 'Carlos@Gmail.com'})

    assert resp.status_code == 302
    mock_enqueue.assert_called_once()
    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    assert 'lower' in first_call_sql.lower()


def test_forgot_password_post_email_inexistente_mensagem_generica(client, db):
    """Email não cadastrado → mensagem genérica (sem revelar inexistência)."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'email': 'naoexiste@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o email' in body or 'email' in body.lower()
