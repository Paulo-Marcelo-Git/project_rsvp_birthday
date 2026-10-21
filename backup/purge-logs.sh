#!/bin/sh
# Apaga os logs diários do app (app-AAAA-MM-DD.log) com mais de
# LOG_RETENTION_DAYS dias (default 5). Roda 1x/dia pelo cron do container
# backup, que monta ./logs do host em /logs (PR-0, LGPD — spec-mãe D9).
# Só toca arquivos com o nome exato app-AAAA-MM-DD.log no topo de LOG_DIR:
# app.log antigo, outros arquivos e subpastas nunca são apagados aqui.
set -eu

LOG_DIR=${LOG_DIR:-/logs}
RETENTION_DAYS=${LOG_RETENTION_DAYS:-5}
now() { date '+%Y-%m-%d %H:%M:%S'; }

case "$RETENTION_DAYS" in
  ''|*[!0-9]*)
    echo "[$(now)] ERRO: LOG_RETENTION_DAYS inválido ('${RETENTION_DAYS}'); nada apagado" >&2
    exit 2
    ;;
esac
if [ "$RETENTION_DAYS" -lt 1 ]; then
  echo "[$(now)] ERRO: LOG_RETENTION_DAYS deve ser >= 1; nada apagado" >&2
  exit 2
fi

if [ ! -d "$LOG_DIR" ]; then
  echo "[$(now)] AVISO: ${LOG_DIR} não existe; nada a fazer"
  exit 0
fi

# -mtime +N casa arquivos com idade >= (N+1) dias inteiros: para 5 dias, +4.
MTIME=$((RETENTION_DAYS - 1))
DELETED=$(find "$LOG_DIR" -maxdepth 1 -type f \
  -name 'app-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].log' \
  -mtime +"$MTIME" -print -delete | wc -l)
echo "[$(now)] Limpeza de logs: ${DELETED} arquivo(s) removido(s) (>${RETENTION_DAYS} dias) em ${LOG_DIR}"
