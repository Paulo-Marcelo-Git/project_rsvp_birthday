#!/bin/sh
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
RETENTION_DAYS=${BACKUP_RETENTION_DAYS:-7}
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
FILENAME="comemore_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

# Credenciais via arquivo de opções (fora do `ps`), removido ao sair.
umask 077
CNF=$(mktemp)
DUMP_TMP="${BACKUP_DIR}/${FILENAME}.tmp"
trap 'rm -f "$CNF" "$DUMP_TMP"' EXIT
esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
{
  printf '[client]\n'
  printf 'user="%s"\n' "$(esc "$DB_USER")"
  printf 'password="%s"\n' "$(esc "$DB_PASSWORD")"
  printf 'host="%s"\n' "$(esc "$DB_HOST")"
} > "$CNF"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup de ${DB_NAME}..."

# Dump atômico: grava em .tmp, valida com gzip -t e só então renomeia; em
# qualquer falha o .tmp é apagado (trap) e nunca fica arquivo truncado.
mysqldump \
  --defaults-extra-file="$CNF" \
  --single-transaction \
  --routines \
  --triggers \
  "$DB_NAME" | gzip > "$DUMP_TMP"
gzip -t "$DUMP_TMP"
mv "$DUMP_TMP" "${BACKUP_DIR}/${FILENAME}"

SIZE=$(du -sh "${BACKUP_DIR}/${FILENAME}" | cut -f1)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup salvo: ${FILENAME} (${SIZE})"

UPLOADS_DIR=${UPLOADS_DIR:-/uploads}
UPLOADS_FILE="comemore_uploads_${TIMESTAMP}.tar.gz"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Iniciando backup dos uploads (${UPLOADS_DIR})..."
# Grava em nome temporário e só renomeia em caso de sucesso: nunca fica um
# arquivo truncado com nome de backup válido.
UPLOADS_TMP="${BACKUP_DIR}/${UPLOADS_FILE}.tmp"
TAR_RC=0
tar -czf "$UPLOADS_TMP" -C "$UPLOADS_DIR" . || TAR_RC=$?
if [ "$TAR_RC" -ge 2 ]; then
  rm -f "$UPLOADS_TMP"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERRO: tar dos uploads falhou (código ${TAR_RC}); backup de uploads NÃO gerado" >&2
else
  if [ "$TAR_RC" -eq 1 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] AVISO: arquivos mudaram durante a leitura (tar código 1); arquivo mantido"
  fi
  mv "$UPLOADS_TMP" "${BACKUP_DIR}/${UPLOADS_FILE}"
  UPLOADS_SIZE=$(du -sh "${BACKUP_DIR}/${UPLOADS_FILE}" | cut -f1)
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Backup de uploads salvo: ${UPLOADS_FILE} (${UPLOADS_SIZE})"
fi

# Retenção roda sempre (mesmo se o tar falhou) para não encher o volume de backup.
DELETED=$(find "$BACKUP_DIR" \( -name 'comemore_*.sql.gz' -o -name 'comemore_*.sql.gz.tmp' -o -name 'comemore_uploads_*.tar.gz' -o -name 'comemore_uploads_*.tar.gz.tmp' \) -mtime +"$RETENTION_DAYS" -print -delete | wc -l)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Retenção: ${DELETED} arquivo(s) removido(s) (>${RETENTION_DAYS} dias)"

# Falha real do tar => código de saída != 0 (depois da retenção)
if [ "$TAR_RC" -ge 2 ]; then
  exit "$TAR_RC"
fi
