#!/bin/sh
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="comemore_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup de ${DB_NAME}..."

mysqldump \
  -h "$DB_HOST" \
  -u "$DB_USER" \
  -p"$DB_PASSWORD" \
  --single-transaction \
  --routines \
  --triggers \
  "$DB_NAME" | gzip > "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup salvo: ${FILENAME} (${SIZE})"

DELETED=$(find "$BACKUP_DIR" -name 'comemore_*.sql.gz' -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Retenção: ${DELETED} arquivo(s) removido(s) (>${RETENTION_DAYS} dias)"
