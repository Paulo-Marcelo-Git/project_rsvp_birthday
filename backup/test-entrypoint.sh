#!/bin/sh
# Teste do entrypoint.sh. Offline; roda na imagem do backup.
# Uso: sh test-entrypoint.sh [entrypoint.sh]
set -eu
SCRIPT=${1:-$(dirname "$0")/entrypoint.sh}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok()   { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAIL=1; }

ENV_OUT="$T/backup.env"; CRONTAB_OUT="$T/crontab"
SPECIAL_DB="a'b\"c \$d\\e"
SPECIAL_B2='x y'
(
  export ENV_OUT CRONTAB_OUT ENTRYPOINT_NO_CROND=1
  export DB_NAME=rsvp_db DB_HOST=db DB_USER=root DB_PASSWORD="$SPECIAL_DB"
  export B2_APP_KEY="$SPECIAL_B2" B2_ACCOUNT_ID=fake-id B2_BUCKET=fake-bucket
  export CRYPT_PASSWORD=fake-crypt CRYPT_SALT=fake-salt
  export HC_BACKUP_URL=https://hc.invalid/fake HC_OFFSITE_URL=https://hc.invalid/fake2
  export UPLOADS_DIR=/uploads ENV_FILE_PATH=/run/comemore/env BACKUP_DIR=/backups
  export LOG_DIR=/logs LOG_RETENTION_DAYS=5 BACKUP_RETENTION_DAYS=7 TZ=UTC
  export OUTRA_SECRETA=x
  sh "$SCRIPT" > "$T/out.log" 2>&1
) || { fail "entrypoint saiu com erro"; cat "$T/out.log"; }

[ "$(stat -c %a "$ENV_OUT")" = 600 ] && ok "perm_0600" || fail "perm_0600"

if ( . "$ENV_OUT"; [ "$DB_PASSWORD" = "$SPECIAL_DB" ] && [ "$B2_APP_KEY" = "$SPECIAL_B2" ] ); then
  ok "roundtrip_especiais"
else
  fail "roundtrip_especiais"
fi

for v in DB_NAME DB_HOST DB_USER B2_ACCOUNT_ID B2_BUCKET CRYPT_PASSWORD CRYPT_SALT HC_BACKUP_URL HC_OFFSITE_URL UPLOADS_DIR ENV_FILE_PATH BACKUP_DIR LOG_DIR LOG_RETENTION_DAYS BACKUP_RETENTION_DAYS TZ; do
  if grep -q -E "^export $v=" "$ENV_OUT"; then ok "propaga $v"; else fail "nao propagou $v"; fi
done

[ "$(grep -c -E 'PASSWORD|KEY|SALT|HC_' "$CRONTAB_OUT")" = 0 ] && ok "crontab_sem_segredo" || fail "crontab com segredo"
grep -q '^05 5 \* \* \* \. /etc/backup.env; /backup.sh >> /var/log/backup.log 2>&1$' "$CRONTAB_OUT" && ok "cron backup 05 5" || fail "cron backup"
grep -q '^20 5 \* \* \* \. /etc/backup.env; /purge-logs.sh >> /var/log/purge-logs.log 2>&1$' "$CRONTAB_OUT" && ok "cron purge 20 5" || fail "cron purge"

[ -s "$ENV_OUT" ] && grep -q OUTRA_SECRETA "$ENV_OUT" && fail "filtra_vars: vazou OUTRA_SECRETA" || { [ -s "$ENV_OUT" ] && ok "filtra_vars" || fail "filtra_vars: sem env"; }

[ "$FAIL" = 0 ] && echo "TODOS OK" || { echo "HA FALHAS"; exit 1; }
