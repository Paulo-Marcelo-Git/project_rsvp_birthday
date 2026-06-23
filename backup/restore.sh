#!/bin/sh
set -euo pipefail

# Uso: docker exec rsvp_backup sh /restore.sh /backups/comemore_YYYYMMDD_HHMMSS.sql.gz [nome_db]
BACKUP_FILE="${1:?Uso: docker exec rsvp_backup sh /restore.sh /backups/comemore_XYZ.sql.gz [nome_db]}"
RESTORE_DB="${2:-rsvp_restore_test}"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restaurando ${BACKUP_FILE} em ${RESTORE_DB}..."

mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" \
  -e "CREATE DATABASE IF NOT EXISTS \`${RESTORE_DB}\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

gunzip -c "$BACKUP_FILE" | mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$RESTORE_DB"

echo ""
echo "Tabelas em ${RESTORE_DB}:"
mysql -h "$DB_HOST" -u "$DB_USER" -p"$DB_PASSWORD" "$RESTORE_DB" -e "SHOW TABLES;"

echo ""
echo "Restore concluído."
echo "Para verificar as migrations no banco restaurado:"
echo "  docker exec rsvp_backend env DB_NAME=${RESTORE_DB} python -m alembic upgrade head"
