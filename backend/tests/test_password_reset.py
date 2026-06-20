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
    assert 'joao' in msg_str
    assert 'tok123' in msg_str


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
