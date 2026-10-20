# backend/log_utils.py
"""
Helpers de log sem dado pessoal (PR-0 — LGPD).

Módulo puro: sem Flask nem SQLAlchemy. É importado pelo app.py, pelo worker
RQ (via tasks.py/queue_utils.py) e pelo gunicorn.conf.py.

Regra: log identifica por ID (user_id, tenant_id, event_id, invitee_id).
E-mail só mascarado (mask_email), exceção só pelo tipo (exc_label), URL sem
credencial (mask_url), token fora do caminho (mask_token_paths).
O RedactingFormatter é a rede de segurança para o texto que o nosso código não
controla (traceback, mensagem de exceção de terceiros, log do Flask com
request.path): mascara e-mails e tokens no texto final de cada linha.
"""
import logging
import os
import re
from datetime import date
from urllib.parse import urlsplit, urlunsplit

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"

# Rotas cujo último segmento é um token secreto.
_TOKEN_PATH_RE = re.compile(r"(/(?:invite|verify-email|reset_password)/)[^/?#\s\"'<>]+")

# Caracteres que não fazem parte de um endereço de e-mail "solto" em texto.
_EMAIL_RE = re.compile(
    r"([^\s@'\"<>()\[\],;:/=\\]+)@([^\s@'\"<>()\[\],;:/=\\]+\.[^\s@'\"<>()\[\],;:/=\\]+)"
)


def mask_email(email: str | None) -> str:
    """'joao@exemplo.com' -> 'j***@exemplo.com'. Sem '@' válido -> '***'.
    Vazio/None -> '-'."""
    if not email:
        return "-"
    email = str(email).strip()
    if not email:
        return "-"
    local, sep, domain = email.rpartition("@")
    if not sep or not domain:
        return "***"
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def mask_emails_in_text(text: str | None) -> str | None:
    """Mascara todo e-mail encontrado em texto livre (idempotente)."""
    if not text:
        return text
    return _EMAIL_RE.sub(lambda m: f"{m.group(1)[0]}***@{m.group(2)}", text)


def mask_token_paths(text: str | None) -> str | None:
    """'/invite/AbC123' -> '/invite/***' (idem /verify-email/ e /reset_password/),
    em qualquer posição do texto (caminho, URL completa, linha de request)."""
    if not text:
        return text
    return _TOKEN_PATH_RE.sub(r"\1***", text)


def redact_text(text: str | None) -> str | None:
    """Aplica as duas máscaras de texto livre (e-mail e token)."""
    return mask_token_paths(mask_emails_in_text(text))


def mask_url(url: str | None) -> str:
    """Remove usuário/senha de uma URL: 'redis://:x@redis:6379/0' ->
    'redis://***@redis:6379/0'. URL sem credencial volta igual."""
    if not url:
        return "-"
    try:
        parts = urlsplit(url)
        if parts.username is None and parts.password is None:
            return url
        host = parts.hostname or ""
        if parts.port is not None:
            host = f"{host}:{parts.port}"
        return urlunsplit((parts.scheme, f"***@{host}", parts.path, parts.query, parts.fragment))
    except ValueError:
        return "<url inválida>"


def exc_label(exc: BaseException) -> str:
    """Nome do tipo da exceção, sem a mensagem (que pode conter e-mail).
    Erro do banco embrulhado pelo SQLAlchemy (tem `.orig`) ganha o código
    numérico do MySQL: 'IntegrityError(mysql=1062)'."""
    name = type(exc).__name__
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None)
    if args and isinstance(args[0], int) and not isinstance(args[0], bool):
        return f"{name}(mysql={args[0]})"
    return name


class RedactingFormatter(logging.Formatter):
    """Formatter que mascara e-mails e tokens no texto final (mensagem +
    traceback). Rede de segurança — o código continua obrigado a logar só IDs."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


class DailyFileHandler(logging.FileHandler):
    """Grava em <directory>/<prefix>-AAAA-MM-DD.log e passa para o arquivo do
    dia seguinte quando a data muda. Só acrescenta (modo 'a'): cada processo
    do gunicorn tem o seu handler e nenhum renomeia/apaga arquivo, então é
    seguro com vários workers. A limpeza é do purge-logs.sh (container backup).
    A data é a do relógio do container (UTC, salvo TZ definido)."""

    def __init__(self, directory: str, prefix: str = "app", encoding: str = "utf-8", clock=None):
        self.directory = directory
        self.prefix = prefix
        self._clock = clock or date.today
        self._current_day = self._clock()
        os.makedirs(directory, exist_ok=True)
        super().__init__(self._path_for(self._current_day), mode="a", encoding=encoding, delay=True)

    def _path_for(self, day: date) -> str:
        return os.path.join(self.directory, f"{self.prefix}-{day.isoformat()}.log")

    def emit(self, record: logging.LogRecord) -> None:
        day = self._clock()
        if day != self._current_day:
            self._current_day = day
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            self.baseFilename = os.path.abspath(self._path_for(day))
        super().emit(record)


def build_log_handlers(log_file: str) -> list[logging.Handler]:
    """Handlers do app: arquivo diário + stdout (docker logs), ambos com
    RedactingFormatter. `log_file` é o LOG_FILE de sempre ('logs/app.log'):
    o diretório e o nome-base viram 'logs/app-AAAA-MM-DD.log'."""
    directory = os.path.dirname(log_file) or "."
    prefix = os.path.splitext(os.path.basename(log_file))[0] or "app"
    handlers: list[logging.Handler] = [DailyFileHandler(directory, prefix=prefix), logging.StreamHandler()]
    for handler in handlers:
        handler.setFormatter(RedactingFormatter(LOG_FORMAT))
    return handlers
