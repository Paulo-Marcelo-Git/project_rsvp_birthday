"""PR-0 — configuração de log do app: arquivo diário + stdout com máscara,
SQLAlchemy sem parâmetros em exceção, e o log de exceção do próprio Flask
(que inclui request.path) sem token/e-mail no texto final."""
import inspect
import logging
import os
import re
import subprocess
import sys
from pathlib import Path

import pymysql
from sqlalchemy.exc import IntegrityError

import app as app_module
from log_utils import LOG_FORMAT, RedactingFormatter

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_import_do_app_configura_arquivo_diario_e_stdout(tmp_path):
    """Processo limpo (sem os handlers do pytest no root): o app grava em
    logs/app-AAAA-MM-DD.log e no stdout, e o logger do Flask não ganha
    handler próprio (tudo passa pelos handlers com máscara)."""
    env = dict(os.environ)
    env["LOG_FILE"] = str(tmp_path / "logs" / "app.log")
    env["UPLOAD_FOLDER"] = str(tmp_path / "uploads")
    code = (
        "import logging, app\n"
        "logging.getLogger('app').info('ping diario joao@exemplo.com /invite/TOKSUB1')\n"
        "print([type(h).__name__ for h in logging.getLogger().handlers])\n"
        "print('flask_handlers=%d' % len(app.app.logger.handlers))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert out.returncode == 0, out.stderr
    assert "['DailyFileHandler', 'StreamHandler']" in out.stdout
    assert "flask_handlers=0" in out.stdout
    files = list((tmp_path / "logs").glob("app-*.log"))
    assert len(files) == 1
    assert re.fullmatch(r"app-\d{4}-\d{2}-\d{2}\.log", files[0].name)
    content = files[0].read_text(encoding="utf-8")
    assert "ping diario j***@exemplo.com /invite/***" in content
    assert "joao@exemplo.com" not in content and "TOKSUB1" not in content
    assert "joao@exemplo.com" not in out.stderr and "TOKSUB1" not in out.stderr


def test_flask_limiter_nao_loga_ip_em_info():
    """O limite estourado é logado em INFO com a chave (IP); o logger fica em WARNING."""
    assert logging.getLogger("flask-limiter").getEffectiveLevel() == logging.WARNING


def test_engine_esconde_parametros_sql_em_excecoes():
    """create_engine(hide_parameters=True): IntegrityError/OperationalError do
    banco não carregam nome/e-mail/telefone/observação no texto."""
    src = inspect.getsource(app_module)
    engine_call = src[src.index("engine = create_engine("):]
    engine_call = engine_call[:engine_call.index("\n)\n")]
    assert "hide_parameters=True" in engine_call


def test_excecao_nao_tratada_do_flask_nao_vaza_token_nem_email(client, db, monkeypatch, caplog):
    """Flask loga 'Exception on /invite/<token> [POST]' + traceback. O texto
    final (formatter do app) não pode ter o token nem o e-mail da mensagem do
    MySQL; os parâmetros SQL já vêm ocultos (hide_parameters)."""
    token = "TokNaoTratada999"
    monkeypatch.setitem(app_module.app.config, "PROPAGATE_EXCEPTIONS", False)
    monkeypatch.setattr(app_module.repo, "get_invitee_by_token", lambda conn, t: {
        "id": 1, "event_id": 1, "tenant_id": 1, "name": "Ana Júlia", "token": token,
        "response": "pending", "custom_message": None, "response_date": None,
        "media_url": None, "phone": None, "email": None, "created_at": None,
        "event_media_url": "e.jpg",
    })

    def _falha(*args, **kwargs):
        raise IntegrityError(
            "UPDATE invitees SET ...", {"obs": "observação secreta"},
            pymysql.err.IntegrityError(1062, "Duplicate entry 'ana.julia@exemplo.com' for key 'x'"),
            hide_parameters=True,
        )

    monkeypatch.setattr(app_module.repo, "update_invitee", _falha)
    caplog.set_level(logging.DEBUG)
    resp = client.post(f"/invite/{token}", data={"response": "yes", "observacao": "observação secreta"})
    assert resp.status_code == 500

    fmt = RedactingFormatter(LOG_FORMAT)
    texto = "\n".join(fmt.format(r) for r in caplog.records)
    assert "Exception on /invite/*** [POST]" in texto
    assert token not in texto
    assert "ana.julia@exemplo.com" not in texto
    assert "observação secreta" not in texto
