"""Testes do backend/gunicorn.conf.py (PR-0, L9): mesmos args de antes +
logger que mascara tokens no access log e no error log."""
import importlib.util
import logging
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from gunicorn.config import Config

from log_utils import RedactingFormatter

BACKEND_DIR = Path(__file__).resolve().parents[1]

ACCESS_FORMAT_ANTIGO = (
    "%(t)s | %(p)s | %(m)s %(U)s | status=%(s)s | resp_time=%(L)s sec | size=%(B)s bytes"
)


def _load_conf():
    spec = importlib.util.spec_from_file_location(
        "gunicorn_conf_sob_teste", BACKEND_DIR / "gunicorn.conf.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _logger(conf, fmt=None):
    cfg = Config()
    cfg.set("accesslog", "-")
    cfg.set("access_log_format", fmt or conf.access_log_format)
    return conf.TokenMaskingLogger(cfg)


class _ListHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())


def _access_line(path, query="", referer="-", fmt=None):
    conf = _load_conf()
    lg = _logger(conf, fmt)
    h = _ListHandler()
    lg.access_log.addHandler(h)
    try:
        environ = {
            "REQUEST_METHOD": "GET",
            "RAW_URI": path + (f"?{query}" if query else ""),
            "SERVER_PROTOCOL": "HTTP/1.1",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "HTTP_REFERER": referer,
            "REMOTE_ADDR": "127.0.0.1",
        }
        resp = SimpleNamespace(status="200 OK", headers=[("Content-Type", "text/html")], sent=321)
        req = SimpleNamespace(headers=[("REFERER", referer)])
        lg.access(resp, req, environ, timedelta(microseconds=1500))
    finally:
        lg.access_log.removeHandler(h)
    assert h.lines, "access log não emitiu linha"
    return h.lines[-1]


def test_conf_reproduz_os_args_do_dockerfile_antigo():
    conf = _load_conf()
    assert conf.workers == 2
    assert conf.threads == 4
    assert conf.worker_class == "gthread"
    assert conf.bind == "0.0.0.0:8000"
    assert conf.timeout == 120
    assert conf.graceful_timeout == 30
    assert conf.keepalive == 5
    assert conf.accesslog == "-"
    assert conf.access_log_format == ACCESS_FORMAT_ANTIGO
    assert conf.logger_class is conf.TokenMaskingLogger


def test_conf_e_aceita_pelo_config_do_gunicorn():
    conf = _load_conf()
    cfg = Config()
    for name in ("workers", "threads", "worker_class", "bind", "timeout",
                 "graceful_timeout", "keepalive", "accesslog",
                 "access_log_format", "logger_class"):
        assert name in cfg.settings, name
        cfg.set(name, getattr(conf, name))
    assert cfg.logger_class is conf.TokenMaskingLogger
    assert cfg.workers == 2 and cfg.threads == 4


@pytest.mark.parametrize("path, token, mascarado", [
    ("/invite/TOKCONVITE123", "TOKCONVITE123", "/invite/***"),
    ("/verify-email/TOKVERIF456", "TOKVERIF456", "/verify-email/***"),
    ("/reset_password/TOKRESET789", "TOKRESET789", "/reset_password/***"),
])
def test_access_log_mascara_token_no_caminho(path, token, mascarado):
    line = _access_line(path)
    assert token not in line
    assert f"GET {mascarado} | status=200" in line


def test_access_log_mantem_rota_sem_token():
    line = _access_line("/admin/respostas", query="event_id=3")
    assert "GET /admin/respostas | status=200" in line


def test_access_log_mascara_token_em_todos_os_campos():
    """Referer (página do convite pedindo /uploads/...), request line com
    query e variáveis de ambiente — nenhum campo pode vazar o token."""
    fmt = "%(r)s | %(f)s | %({referer}i)s | %({raw_uri}e)s | %(q)s"
    line = _access_line(
        "/reset_password/TOKA1", query="next=/invite/TOKB2",
        referer="https://zapbyte.com.br/invite/TOKC3", fmt=fmt,
    )
    for token in ("TOKA1", "TOKB2", "TOKC3"):
        assert token not in line
    assert "/reset_password/***" in line and "/invite/***" in line


def test_error_log_do_gunicorn_usa_formatter_com_redacao():
    conf = _load_conf()
    lg = _logger(conf)
    assert lg.error_log.handlers
    rec = logging.LogRecord(
        "gunicorn.error", logging.ERROR, __file__, 1,
        "Error handling request %s", ("/reset_password/TOKERRO999",), None,
    )
    for h in lg.error_log.handlers:
        assert isinstance(h.formatter, RedactingFormatter)
        out = h.formatter.format(rec)
        assert "TOKERRO999" not in out
        assert "/reset_password/***" in out


def test_entrypoint_inicia_gunicorn_com_o_arquivo_de_config():
    sh = (BACKEND_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    assert 'exec gunicorn -c gunicorn.conf.py app:app "$@"' in sh


def test_dockerfile_nao_define_mais_gunicorn_cmd_args():
    """GUNICORN_CMD_ARGS sobrescreveria o gunicorn.conf.py — fonte única é o arquivo."""
    assert "GUNICORN_CMD_ARGS" not in (BACKEND_DIR / "Dockerfile").read_text(encoding="utf-8")
