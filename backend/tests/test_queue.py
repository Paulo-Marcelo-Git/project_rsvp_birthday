"""
Testes para tasks.py (funções de email standalone) e queue_utils.py (fila RQ).
Nenhum teste requer Redis real — fila é mockada via monkeypatch.
"""
import logging
import os
from unittest.mock import MagicMock, patch


# ── tasks.py: funções de email ────────────────────────────────────────────────

def test_send_reset_email_sem_config_loga_warning(caplog):
    """Sem EMAIL_SMTP configurado, deve logar warning e retornar sem erro."""
    import tasks
    env = {k: v for k, v in os.environ.items() if k not in ('EMAIL_SMTP', 'EMAIL_USER')}
    with patch.dict(os.environ, env, clear=True):
        with caplog.at_level(logging.WARNING, logger='tasks'):
            tasks.send_reset_email('user@test.com', 'testuser', 'http://x/reset/abc')
    assert any('EMAIL_SMTP' in r.message or 'email' in r.message.lower()
                for r in caplog.records)


def test_send_reset_email_com_config_chama_smtp(monkeypatch):
    """Com EMAIL_SMTP configurado, deve chamar smtplib.SMTP e enviar mensagem."""
    import tasks
    monkeypatch.setenv('EMAIL_SMTP', 'smtp.gmail.com')
    monkeypatch.setenv('EMAIL_PORTA', '587')
    monkeypatch.setenv('EMAIL_USER', 'bot@gmail.com')
    monkeypatch.setenv('EMAIL_PASS', 'secret')

    mock_smtp = MagicMock()
    with patch('smtplib.SMTP', return_value=mock_smtp):
        tasks.send_reset_email('dest@test.com', 'joao', 'http://x/reset/tok123')

    mock_smtp.starttls.assert_called_once()
    mock_smtp.login.assert_called_once_with('bot@gmail.com', 'secret')
    mock_smtp.sendmail.assert_called_once()
    import base64, email as _email
    msg_str = mock_smtp.sendmail.call_args[0][2]
    decoded = msg_str
    try:
        parsed = _email.message_from_string(msg_str)
        for part in parsed.walk():
            payload = part.get_payload(decode=True)
            if payload:
                decoded += payload.decode('utf-8', errors='replace')
    except Exception:
        pass
    assert 'joao' in decoded and 'tok123' in decoded


def test_send_verification_email_sem_config_retorna_false(monkeypatch):
    """Sem EMAIL_SMTP, send_verification_email deve retornar False."""
    import tasks
    monkeypatch.delenv('EMAIL_SMTP', raising=False)
    monkeypatch.delenv('EMAIL_USER', raising=False)
    result = tasks.send_verification_email('u@test.com', 'http://x/verify/tok')
    assert result is False


def test_send_member_invite_email_chama_smtp(monkeypatch):
    """send_member_invite_email com SMTP configurado deve chamar sendmail."""
    import tasks
    monkeypatch.setenv('EMAIL_SMTP', 'smtp.gmail.com')
    monkeypatch.setenv('EMAIL_PORTA', '587')
    monkeypatch.setenv('EMAIL_USER', 'bot@gmail.com')
    monkeypatch.setenv('EMAIL_PASS', 'secret')

    mock_smtp = MagicMock()
    with patch('smtplib.SMTP', return_value=mock_smtp):
        result = tasks.send_member_invite_email('dest@test.com', 'maria', 'http://x/r/tok')

    assert result is True
    mock_smtp.sendmail.assert_called_once()
