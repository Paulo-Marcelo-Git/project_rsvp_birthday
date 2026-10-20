"""Testes dos helpers de log sem dado pessoal (backend/log_utils.py — PR-0)."""
import logging
import sys
import threading
from datetime import date

import pymysql
import pytest
from sqlalchemy.exc import IntegrityError

from log_utils import (
    LOG_FORMAT,
    DailyFileHandler,
    RedactingFormatter,
    build_log_handlers,
    exc_label,
    mask_email,
    mask_emails_in_text,
    mask_token_paths,
    mask_url,
    redact_text,
)


# ── mask_email ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, esperado", [
    ("joao@exemplo.com", "j***@exemplo.com"),
    ("Joao.Silva@Exemplo.COM", "J***@Exemplo.COM"),
    ("ção.conceição@exemplo.com.br", "ç***@exemplo.com.br"),
    ("a@b.co", "a***@b.co"),
    ("a@b@c.com", "a***@c.com"),
    ("@dominio.com", "***@dominio.com"),
    ("usuario@", "***"),
    ("senha-digitada-no-campo-errado", "***"),
    ("  maria@x.com  ", "m***@x.com"),
    ("   ", "-"),
    ("", "-"),
    (None, "-"),
])
def test_mask_email(raw, esperado):
    assert mask_email(raw) == esperado


# ── mask_emails_in_text / mask_token_paths / redact_text ─────────────────────

@pytest.mark.parametrize("raw, esperado", [
    ("Duplicate entry 'ana.maria@exemplo.com' for key 'users.email'",
     "Duplicate entry 'a***@exemplo.com' for key 'users.email'"),
    ("to=<joão@exemplo.com.br>", "to=<j***@exemplo.com.br>"),
    ("{'x@y.com': (550, b'5.1.1 user unknown')}", "{'x***@y.com': (550, b'5.1.1 user unknown')}"),
    ("a***@x.com", "a***@x.com"),
    ("redis://:senha@redis:6379/0", "redis://:senha@redis:6379/0"),
    ("sem e-mail aqui", "sem e-mail aqui"),
    ("", ""),
    (None, None),
])
def test_mask_emails_in_text(raw, esperado):
    assert mask_emails_in_text(raw) == esperado


@pytest.mark.parametrize("raw, esperado", [
    ("/invite/AbC_123-xyz", "/invite/***"),
    ("GET /verify-email/tok.en?x=1 HTTP/1.1", "GET /verify-email/***?x=1 HTTP/1.1"),
    ("https://zapbyte.com.br/reset_password/T0k3n", "https://zapbyte.com.br/reset_password/***"),
    ("Exception on /invite/TOKEN123 [POST]", "Exception on /invite/*** [POST]"),
    ("/admin/respostas?event_id=1", "/admin/respostas?event_id=1"),
    ("/uploads/abc123.jpg", "/uploads/abc123.jpg"),
    ("/invite/", "/invite/"),
    ("/invite/***", "/invite/***"),
    ("", ""),
    (None, None),
])
def test_mask_token_paths(raw, esperado):
    assert mask_token_paths(raw) == esperado


def test_redact_text_aplica_as_duas_mascaras():
    raw = "link https://x.com/reset_password/ABC enviado para maria@x.com"
    assert redact_text(raw) == "link https://x.com/reset_password/*** enviado para m***@x.com"


# ── mask_url ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw, esperado", [
    ("redis://redis:6379/0", "redis://redis:6379/0"),
    ("redis://:s3nha-fake@redis:6379/0", "redis://***@redis:6379/0"),
    ("redis://user:s3nha-fake@redis.local:6380/1", "redis://***@redis.local:6380/1"),
    ("mysql+pymysql://root:x@db/rsvp", "mysql+pymysql://***@db/rsvp"),
    ("redis://:p@host:naoeporta/0", "<url inválida>"),
    ("", "-"),
    (None, "-"),
])
def test_mask_url(raw, esperado):
    assert mask_url(raw) == esperado


# ── exc_label ─────────────────────────────────────────────────────────────────

def test_exc_label_integrity_error_traz_codigo_mysql_sem_mensagem():
    e = IntegrityError(
        "INSERT INTO users ...", {"email": "x@y.com"},
        pymysql.err.IntegrityError(1062, "Duplicate entry 'x@y.com' for key 'users.email'"),
    )
    assert exc_label(e) == "IntegrityError(mysql=1062)"


def test_exc_label_excecao_comum_so_tipo():
    assert exc_label(ValueError("x@y.com")) == "ValueError"


def test_exc_label_oserror_nao_vira_codigo_mysql():
    assert exc_label(PermissionError(13, "Permission denied: '/app/uploads/x.jpg'")) == "PermissionError"


# ── RedactingFormatter ────────────────────────────────────────────────────────

def test_redacting_formatter_mascara_mensagem_e_traceback():
    fmt = RedactingFormatter(LOG_FORMAT)
    try:
        raise IntegrityError(
            "INSERT INTO users ...", None,
            pymysql.err.IntegrityError(1062, "Duplicate entry 'dono.festa@exemplo.com' for key 'users.email'"),
        )
    except IntegrityError:
        rec = logging.LogRecord(
            "app", logging.ERROR, __file__, 1, "Exception on %s [%s]",
            ("/invite/TOKSECRETO123", "POST"), sys.exc_info(),
        )
    out = fmt.format(rec)
    assert "TOKSECRETO123" not in out
    assert "dono.festa@exemplo.com" not in out
    assert "/invite/***" in out
    assert "d***@exemplo.com" in out
    assert "IntegrityError" in out


# ── DailyFileHandler ──────────────────────────────────────────────────────────

class _Clock:
    def __init__(self, d):
        self.d = d

    def __call__(self):
        return self.d


def _rec(msg):
    return logging.LogRecord("t", logging.INFO, __file__, 1, msg, None, None)


def _handler(directory, clock):
    h = DailyFileHandler(str(directory), prefix="app", clock=clock)
    h.setFormatter(logging.Formatter("%(message)s"))
    return h


def test_daily_handler_grava_no_arquivo_do_dia(tmp_path):
    h = _handler(tmp_path / "logs", _Clock(date(2026, 10, 19)))
    try:
        h.handle(_rec("linha 1"))
    finally:
        h.close()
    assert (tmp_path / "logs" / "app-2026-10-19.log").read_text(encoding="utf-8") == "linha 1\n"


def test_daily_handler_nao_cria_arquivo_sem_log(tmp_path):
    h = _handler(tmp_path, _Clock(date(2026, 10, 19)))
    h.close()
    assert list(tmp_path.iterdir()) == []


def test_daily_handler_troca_de_arquivo_quando_a_data_muda(tmp_path):
    clock = _Clock(date(2026, 10, 19))
    h = _handler(tmp_path, clock)
    try:
        h.handle(_rec("antes"))
        clock.d = date(2026, 10, 20)
        h.handle(_rec("depois"))
    finally:
        h.close()
    assert (tmp_path / "app-2026-10-19.log").read_text(encoding="utf-8") == "antes\n"
    assert (tmp_path / "app-2026-10-20.log").read_text(encoding="utf-8") == "depois\n"


def test_daily_handler_acrescenta_sem_truncar(tmp_path):
    existente = tmp_path / "app-2026-10-19.log"
    existente.write_text("existente\n", encoding="utf-8")
    h = _handler(tmp_path, _Clock(date(2026, 10, 19)))
    try:
        h.handle(_rec("nova"))
    finally:
        h.close()
    assert existente.read_text(encoding="utf-8") == "existente\nnova\n"


def test_daily_handler_utf8_acentos_e_emoji(tmp_path):
    h = _handler(tmp_path, _Clock(date(2026, 10, 19)))
    try:
        h.handle(_rec("Ação concluída 🎉"))
    finally:
        h.close()
    assert "Ação concluída 🎉" in (tmp_path / "app-2026-10-19.log").read_text(encoding="utf-8")


def test_dois_workers_e_threads_na_virada_do_dia_sem_perder_linha(tmp_path):
    """2 workers do gunicorn (2 handlers independentes no mesmo diretório),
    4 threads cada, com a data virando no meio: nenhuma linha perdida ou
    misturada, e cada linha no arquivo de algum dos dois dias."""
    clock = _Clock(date(2026, 10, 19))
    handlers = [_handler(tmp_path, clock) for _ in range(2)]
    barrier = threading.Barrier(8)

    def worker(h, n):
        barrier.wait()
        for i in range(200):
            if n == 0 and i == 100:
                clock.d = date(2026, 10, 20)
            h.handle(_rec(f"w{n}-{i}"))

    threads = [threading.Thread(target=worker, args=(handlers[n % 2], n)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    for h in handlers:
        h.close()

    files = sorted(tmp_path.glob("app-*.log"))
    assert [p.name for p in files] == ["app-2026-10-19.log", "app-2026-10-20.log"]
    lines = []
    for p in files:
        lines += p.read_text(encoding="utf-8").splitlines()
    assert sorted(lines) == sorted(f"w{n}-{i}" for n in range(8) for i in range(200))


# ── build_log_handlers ────────────────────────────────────────────────────────

def test_build_log_handlers_arquivo_diario_e_stdout_com_redacao(tmp_path):
    handlers = build_log_handlers(str(tmp_path / "logs" / "app.log"))
    try:
        assert [type(h) for h in handlers] == [DailyFileHandler, logging.StreamHandler]
        assert all(isinstance(h.formatter, RedactingFormatter) for h in handlers)
        assert handlers[0].directory == str(tmp_path / "logs")
        assert handlers[0].prefix == "app"
        assert (tmp_path / "logs").is_dir()
    finally:
        for h in handlers:
            h.close()


def test_build_log_handlers_log_file_sem_diretorio(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    handlers = build_log_handlers("meuapp.log")
    try:
        assert handlers[0].directory == "."
        assert handlers[0].prefix == "meuapp"
    finally:
        for h in handlers:
            h.close()
