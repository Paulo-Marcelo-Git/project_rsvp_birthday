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

# Pings do Healthchecks (best-effort, ver hc.sh).
. "${HC_SCRIPT:-/hc.sh}"
DUMP_DONE=0
# LOCAL_PINGED=1: o check "backup-local" já recebeu o ping final (ao fim da parte
# local, antes da cópia externa). Ele reflete só o backup local; falha da cópia
# externa tem check próprio (offsite.sh) mas ainda muda o rc.
LOCAL_PINGED=0
# Trap único: limpeza + ping final se a parte local não terminou, preservando o código de saída.
on_exit() {
  rc=$?
  rm -f "$CNF" "$DUMP_TMP"
  if [ "$LOCAL_PINGED" -ne 1 ]; then
    if [ "$rc" -ne 0 ]; then
      hc_ping "${HC_BACKUP_URL:-}" fail
      # dump não terminou => não há o que enviar ao B2: alerta o check externo também
      [ "$DUMP_DONE" -eq 1 ] || hc_ping "${HC_OFFSITE_URL:-}" fail
    else
      hc_ping "${HC_BACKUP_URL:-}"
    fi
  fi
  exit "$rc"
}
trap on_exit EXIT
hc_ping "${HC_BACKUP_URL:-}" start
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
DUMP_DONE=1

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

# Ping final do backup local antes da cópia externa (ordem da spec §7).
if [ "$TAR_RC" -ge 2 ]; then
  hc_ping "${HC_BACKUP_URL:-}" fail
else
  hc_ping "${HC_BACKUP_URL:-}"
fi
LOCAL_PINGED=1

# Cópia externa roda sempre que o dump terminou (mesmo com tar falho).
OFFSITE_RC=0
if [ "$DUMP_DONE" -eq 1 ]; then
  sh "${OFFSITE_SCRIPT:-/offsite.sh}" || OFFSITE_RC=$?
fi

# Código final = primeiro != 0 entre tar e cópia externa
if [ "$TAR_RC" -ge 2 ]; then
  exit "$TAR_RC"
fi
exit "$OFFSITE_RC"
