# backend/gunicorn.conf.py
"""
Configuração do gunicorn — carregada pelo entrypoint.sh com
`gunicorn -c gunicorn.conf.py app:app`.

Reproduz exatamente os args que antes ficavam na env do Dockerfile e troca o
logger por um que mascara tokens (PR-0, LGPD): /invite/<t>, /verify-email/<t>
e /reset_password/<t> viram /<rota>/*** em todos os campos do access log
(caminho, request line, Referer, headers) e o error log do gunicorn passa
pelo RedactingFormatter.

ATENÇÃO: a env de args do gunicorn, se existir no ambiente, sobrescreve
estes valores (ordem do gunicorn: arquivo < env < linha de comando).
"""
from gunicorn.glogging import Logger

from log_utils import RedactingFormatter, mask_token_paths

workers = 2
threads = 4
worker_class = "gthread"
bind = "0.0.0.0:8000"
timeout = 120
graceful_timeout = 30
keepalive = 5
accesslog = "-"
access_log_format = (
    "%(t)s | %(p)s | %(m)s %(U)s | status=%(s)s | resp_time=%(L)s sec | size=%(B)s bytes"
)


class TokenMaskingLogger(Logger):
    """Logger do gunicorn que nunca escreve token de URL no log."""

    def setup(self, cfg):
        super().setup(cfg)
        for handler in self.error_log.handlers:
            handler.setFormatter(RedactingFormatter(self.error_fmt, self.datefmt))

    def atoms(self, resp, req, environ, request_time):
        atoms = super().atoms(resp, req, environ, request_time)
        return {
            key: mask_token_paths(value) if isinstance(value, str) else value
            for key, value in atoms.items()
        }


logger_class = TokenMaskingLogger
