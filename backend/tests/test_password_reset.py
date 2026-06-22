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
    resp = client.post('/forgot_password', data={'identifier': 'ninguem'},
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
    resp = client.post('/forgot_password', data={'identifier': 'maria'},
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
        resp = client.post('/forgot_password', data={'identifier': 'joao'})

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
    from datetime import datetime, timedelta
    token_row = {
        'id': 1, 'user_id': 2, 'token': 'tok3',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
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
    from datetime import datetime, timedelta
    token_row = {
        'id': 5, 'user_id': 3, 'token': 'tok_used_check',
        'expires_at': datetime.utcnow() + timedelta(hours=1),
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


def test_reset_password_post_senha_igual_padrao_retorna_erro(client, db):
    import os
    default_pw = os.environ.get('DEFAULT_PASSWORD', 'Default@1234')
    resp = client.post('/reset_password/tok4',
                       data={'new_password': default_pw, 'confirm_password': default_pw},
                       follow_redirects=True)
    assert resp.status_code == 200
    assert 'padrão' in resp.data.decode() or 'diferente' in resp.data.decode().lower()


def test_index_exists_retorna_true_quando_indice_existe():
    """_index_exists deve retornar True quando o índice existe no information_schema."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 1
    assert _app._index_exists(conn, 'users', 'idx_users_email_unique') is True


def test_index_exists_retorna_false_quando_indice_nao_existe():
    """_index_exists deve retornar False quando o índice não existe."""
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = 0
    assert _app._index_exists(conn, 'users', 'idx_users_email_unique') is False


def test_forgot_password_post_com_email_valido_envia_reset(client, db):
    """Enviar email existente no campo identifier → cria token e chama send_reset_email."""
    user_row = {'id': 3, 'username': 'ana', 'email': 'ana@test.com'}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),  # SELECT by email
        MagicMock(),                  # INSERT token
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'identifier': 'ana@test.com'})

    assert resp.status_code == 302
    assert '/login' in resp.headers['Location']
    mock_email.assert_called_once()
    args = mock_email.call_args[0]
    assert args[0] == 'ana@test.com'
    assert args[1] == 'ana'
    assert '/reset_password/' in args[2]


def test_forgot_password_post_com_email_case_insensitive(client, db):
    """Busca por email deve usar LOWER() — case-insensitive."""
    user_row = {'id': 4, 'username': 'carlos', 'email': 'carlos@gmail.com'}
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch('app.send_reset_email') as mock_email:
        resp = client.post('/forgot_password', data={'identifier': 'Carlos@Gmail.com'})

    assert resp.status_code == 302
    mock_email.assert_called_once()
    # Verifica que a SQL executada contém LOWER
    first_call_sql = str(conn.execute.call_args_list[0][0][0])
    assert 'lower' in first_call_sql.lower()


def test_forgot_password_post_email_inexistente_mensagem_generica(client, db):
    """Email não cadastrado → mesma mensagem genérica (sem revelar inexistência)."""
    setup_db(db, qresult(fetchone=None))
    resp = client.post('/forgot_password', data={'identifier': 'naoexiste@test.com'},
                       follow_redirects=True)
    assert resp.status_code == 200
    body = resp.data.decode()
    assert 'Se o usuário existir' in body or 'email' in body.lower()
