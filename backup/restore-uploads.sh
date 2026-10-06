#!/bin/sh
set -euo pipefail

# Uso: docker exec rsvp_backup sh /restore-uploads.sh /backups/comemore_uploads_YYYYMMDD_HHMMSS.tar.gz [destino]
# Default do destino é um diretório de TESTE — o volume de produção é montado
# read-only neste container de propósito. Restaurar em produção: ver README.
BACKUP_FILE="${1:?Uso: docker exec rsvp_backup sh /restore-uploads.sh /backups/comemore_uploads_XYZ.tar.gz [destino]}"
DEST="${2:-/tmp/uploads_restore_test}"

mkdir -p "$DEST"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Restaurando ${BACKUP_FILE} em ${DEST}..."
tar -xzf "$BACKUP_FILE" -C "$DEST"
COUNT=$(find "$DEST" -type f | wc -l)
echo "Restore concluído: ${COUNT} arquivo(s) em ${DEST}."
