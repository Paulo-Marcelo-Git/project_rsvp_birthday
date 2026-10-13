#!/bin/sh
set -euo pipefail

# Uso: docker exec rsvp_backup sh /restore.sh /backups/comemore_YYYYMMDD_HHMMSS.sql.gz [nome_db]
BACKUP_FILE="${1:?Uso: docker exec rsvp_backup sh /restore.sh /backups/comemore_XYZ.sql.gz [nome_db]}"
RESTORE_DB="${2:-rsvp_restore_test}"

# Credenciais via arquivo de opções (fora do `ps`), removido ao sair.
umask 077
CNF=$(mktemp)
trap 'rm -f "$CNF"' EXIT
esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
{
  printf '[client]\n'
  printf 'user="%s"\n' "$(esc "$DB_USER")"
  printf 'password="%s"\n' "$(esc "$DB_PASSWORD")"
  printf 'host="%s"\n' "$(esc "$DB_HOST")"
} > "$CNF"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restaurando ${BACKUP_FILE} em ${RESTORE_DB}..."

mysql --defaults-extra-file="$CNF" \
  -e "CREATE DATABASE IF NOT EXISTS \`${RESTORE_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

gunzip -c "$BACKUP_FILE" | mysql --defaults-extra-file="$CNF" "$RESTORE_DB"

echo ""
echo "Tabelas em ${RESTORE_DB}:"
mysql --defaults-extra-file="$CNF" "$RESTORE_DB" -e "SHOW TABLES;"

echo ""
echo "Restore concluído."
echo "Para verificar as migrations no banco restaurado:"
echo "  docker exec rsvp_backend env DB_NAME=${RESTORE_DB} python -m alembic upgrade head"
