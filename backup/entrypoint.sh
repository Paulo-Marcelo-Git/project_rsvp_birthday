#!/bin/sh
# Entrypoint do container de backup: grava o ambiente em arquivo 0600 (fora do crontab,
# que é legível e aparece em `crontab -l`) e inicia o crond.
# ENV_OUT/CRONTAB_OUT/ENTRYPOINT_NO_CROND existem só para teste.
set -eu
ENV_OUT=${ENV_OUT:-/etc/backup.env}

# crond não herda o ambiente do container: os jobs fazem `. /etc/backup.env`.
# `export -p` já escapa aspas/$/\ de forma segura para `.`; filtra só o que os scripts usam.
umask 077
export -p | grep -E '^export (DB_|BACKUP_|UPLOADS_DIR|LOG_|B2_|CRYPT_|HC_|ENV_FILE_PATH|TZ)' > "$ENV_OUT" || true
chmod 600 "$ENV_OUT"

# Cron em UTC: 05:05 UTC = 02:05 BRT; purge de logs 15 min depois.
# crond roda os jobs com PATH=/usr/bin:/bin; rclone fica em /usr/local/bin.
CRON='PATH=/usr/local/bin:/usr/bin:/bin
05 5 * * * . /etc/backup.env; /backup.sh >> /var/log/backup.log 2>&1
20 5 * * * . /etc/backup.env; /purge-logs.sh >> /var/log/purge-logs.log 2>&1'
if [ -n "${CRONTAB_OUT:-}" ]; then
  printf '%s\n' "$CRON" > "$CRONTAB_OUT"
else
  printf '%s\n' "$CRON" | crontab -
fi

[ "${ENTRYPOINT_NO_CROND:-}" = 1 ] && exit 0
exec crond -n
