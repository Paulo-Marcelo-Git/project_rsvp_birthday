# backend/queue_utils.py
"""
Conexão Redis lazy e helper enqueue_email.

Comportamento de fallback baseado na PRESENÇA de REDIS_URL, não em
disponibilidade em runtime:
  - REDIS_URL ausente  → dev intencional → executa sync com warning
  - REDIS_URL presente → prod → loga erro se Redis cair, NÃO executa sync
    (evita que queda de Redis force SMTP síncrono no worker Gunicorn)
"""
import logging
import os

from log_utils import mask_url

logger = logging.getLogger(__name__)

_queue = None

# Jobs de e-mail carregam e-mail + URL com token nos argumentos (PR-0, D9):
# - description = só o nome da função → o worker não loga os argumentos;
# - job que falhou fica no Redis no máximo 5 dias (padrão do RQ: 1 ano);
# - resultado (True/False) e o hash do job somem 60 s após o sucesso.
EMAIL_JOB_FAILURE_TTL = 5 * 24 * 60 * 60
EMAIL_JOB_RESULT_TTL = 60


def _get_queue():
    """Retorna a Queue RQ ou None. Cacheia na primeira chamada bem-sucedida."""
    global _queue
    if _queue is not None:
        return _queue
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return None
    try:
        from redis import Redis
        from rq import Queue
        _queue = Queue("default", connection=Redis.from_url(redis_url))
        logger.info(f"Fila RQ conectada: {mask_url(redis_url)}")
    except Exception as e:
        logger.error(f"Falha ao conectar ao Redis ({mask_url(redis_url)}): {type(e).__name__}")
    return _queue


def _on_email_failure(job, connection, type, value, traceback):
    # O parâmetro `type` (assinatura do RQ) esconde o builtin — por isso
    # value.__class__.__name__, e nunca {value} (a mensagem pode ter o e-mail).
    logger.error(
        f"[Email] Job '{job.id}' ({job.func_name}) falhou definitivamente "
        f"após todas as tentativas: {value.__class__.__name__}"
    )


def enqueue_email(func, *args):
    """
    Enfileira func(*args) na fila RQ 'default' com 3 tentativas e backoff.

    Fallback controlado por REDIS_URL:
      - Ausente  → dev → executa sync com warning
      - Presente → prod → loga erro se Redis indisponível; NÃO executa sync
    """
    q = _get_queue()
    if q is None:
        if os.getenv("REDIS_URL"):
            logger.error(
                f"[Email] Redis indisponível com REDIS_URL configurada — "
                f"{func.__name__} NÃO executado. Verifique a conexão Redis."
            )
            return
        logger.warning(
            f"REDIS_URL não configurada — executando {func.__name__} de forma síncrona."
        )
        func(*args)
        return
    from rq import Retry
    q.enqueue(
        func,
        *args,
        retry=Retry(max=3, interval=[10, 30, 60]),
        on_failure=_on_email_failure,
        description=func.__name__,
        failure_ttl=EMAIL_JOB_FAILURE_TTL,
        result_ttl=EMAIL_JOB_RESULT_TTL,
    )
