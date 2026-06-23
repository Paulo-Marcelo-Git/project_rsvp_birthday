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


# ── queue_utils.py: helper de enfileiramento ──────────────────────────────────

def test_enqueue_email_usa_queue_quando_disponivel(monkeypatch):
    """enqueue_email chama q.enqueue() com func e args corretos."""
    import queue_utils
    import tasks
    from rq import Retry

    mock_queue = MagicMock()
    monkeypatch.setattr(queue_utils, "_get_queue", lambda: mock_queue)

    queue_utils.enqueue_email(tasks.send_reset_email, "to@t.com", "user", "http://x/r/tok")

    mock_queue.enqueue.assert_called_once()
    call_args = mock_queue.enqueue.call_args
    assert call_args[0][0] is tasks.send_reset_email
    assert call_args[0][1] == "to@t.com"
    assert call_args[0][2] == "user"
    assert call_args[0][3] == "http://x/r/tok"
    retry_arg = call_args[1]["retry"]
    assert isinstance(retry_arg, Retry)
    assert retry_arg.max == 3
    assert retry_arg.intervals == [10, 30, 60]
    assert "on_failure" in call_args[1]


def test_enqueue_email_sem_redis_url_executa_sincronamente(monkeypatch):
    """REDIS_URL ausente → dev mode → executa sync com warning no log."""
    import queue_utils

    monkeypatch.setattr(queue_utils, "_get_queue", lambda: None)
    monkeypatch.delenv("REDIS_URL", raising=False)

    called_with = []

    def fake_func(a, b):
        called_with.append((a, b))

    queue_utils.enqueue_email(fake_func, "arg1", "arg2")
    assert called_with == [("arg1", "arg2")]


def test_enqueue_email_redis_url_presente_mas_indisponivel_nao_executa_sync(
    monkeypatch, caplog
):
    """REDIS_URL presente mas Redis down → loga erro, NÃO executa sync.

    Prod com Redis fora do ar não deve degradar para SMTP síncrono no request
    — exatamente o problema que a 3C resolve.
    """
    import queue_utils
    import logging

    monkeypatch.setattr(queue_utils, "_get_queue", lambda: None)
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    called = []

    def fake_func():
        called.append(True)

    with caplog.at_level(logging.ERROR, logger="queue_utils"):
        queue_utils.enqueue_email(fake_func)

    assert not called, "Não deve executar sync quando REDIS_URL está presente"
    assert any("Redis" in r.message for r in caplog.records)


def test_on_email_failure_loga_erro(caplog):
    """_on_email_failure deve logar um erro com job id e nome da função."""
    import queue_utils
    import logging

    mock_job = MagicMock()
    mock_job.id = "job-abc-123"
    mock_job.func_name = "tasks.send_reset_email"

    with caplog.at_level(logging.ERROR, logger="queue_utils"):
        queue_utils._on_email_failure(
            mock_job, MagicMock(), Exception, ValueError("SMTP timeout"), None
        )

    assert any(
        "job-abc-123" in r.message and "definitivamente" in r.message
        for r in caplog.records
    )


# ── app.py wiring ─────────────────────────────────────────────────────────────

def test_forgot_password_enfileira_reset_email(client, db):
    """POST /forgot_password deve chamar enqueue_email com tasks.send_reset_email."""
    from tests.conftest import qresult
    import tasks

    user_row = {
        "id": 2, "username": "joao", "password_hash": "x",
        "must_change_password": False, "email": "joao@test.com",
        "tenant_id": 1, "role": "member", "is_active": 1,
    }
    conn = MagicMock()
    conn.execute.side_effect = [qresult(fetchone=user_row), MagicMock()]
    db.connect.return_value.__enter__.return_value = conn

    with patch("app.enqueue_email") as mock_enqueue:
        resp = client.post("/forgot_password", data={"email": "joao@test.com"})

    assert resp.status_code == 302
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] is tasks.send_reset_email
    assert mock_enqueue.call_args[0][1] == "joao@test.com"
    assert mock_enqueue.call_args[0][2] == "joao"
    assert "/reset_password/" in mock_enqueue.call_args[0][3]


def test_resend_verification_enfileira_email(client, db):
    """POST /resend-verification deve chamar enqueue_email com tasks.send_verification_email."""
    from tests.conftest import qresult
    import tasks

    user_row = {
        "id": 3, "username": "ana", "email": "ana@test.com",
        "is_active": 0, "tenant_id": 1, "role": "tenant_admin",
        "password_hash": "x", "must_change_password": False,
    }
    conn = MagicMock()
    conn.execute.side_effect = [
        qresult(fetchone=user_row),
        MagicMock(),
        qresult(fetchone={"token": "newtok123"}),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch("app.enqueue_email") as mock_enqueue:
        client.post("/resend-verification", data={"email": "ana@test.com"})

    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args[0][0] is tasks.send_verification_email


def test_skip_verification_nao_chama_enqueue_email(client, db, monkeypatch):
    """SKIP_EMAIL_VERIFICATION=1 → signup não deve chamar enqueue_email."""
    from tests.conftest import qresult
    monkeypatch.setenv("SKIP_EMAIL_VERIFICATION", "1")

    conn = MagicMock()
    # get_user_by_email_global → None (usuário novo)
    # create_tenant retorna id via LAST_INSERT_ID
    # create_tenant_admin_user
    # create_default_event
    # UPDATE is_active=1
    conn.execute.side_effect = [
        qresult(fetchone=None),
        qresult(fetchone={"id": 99}),
        qresult(fetchone={"id": 10}),
        MagicMock(),
        MagicMock(),
    ]
    db.connect.return_value.__enter__.return_value = conn

    with patch("app.enqueue_email") as mock_enqueue:
        client.post("/signup", data={
            "nome_anfitriao": "Joao Teste",
            "email": "novo@test.com",
            "password": "Test@1234",
            "confirm_password": "Test@1234",
        })

    assert not mock_enqueue.called, "SKIP_EMAIL_VERIFICATION não deve enfileirar email"
