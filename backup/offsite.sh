#!/bin/sh
# Cópia externa criptografada (Backblaze B2 via rclone crypt). Sem argumentos.
# Saída 0 = enviado ou pulado (dev); != 0 = falha (com ping /fail no check externo).
set -euo pipefail

BACKUP_DIR=${BACKUP_DIR:-/backups}
UPLOADS_DIR=${UPLOADS_DIR:-/uploads}
ENV_FILE_PATH=${ENV_FILE_PATH:-/run/comemore/env}

. "${HC_SCRIPT:-/hc.sh}"
. "${RCLONE_ENV_SCRIPT:-/rclone-env.sh}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# check só lista NOMES faltantes (stderr capturado para decidir dev x produção)
if ! CHK_ERR=$(rclone_env_check 2>&1); then
  # Só pula (dev) se NADA está configurado; config parcial é erro (falha não pode ser silenciosa).
  if [ -z "${HC_OFFSITE_URL:-}${B2_ACCOUNT_ID:-}${B2_APP_KEY:-}${B2_BUCKET:-}${CRYPT_PASSWORD:-}${CRYPT_SALT:-}" ]; then
    log "AVISO: cópia externa desabilitada (B2 não configurado)"
    exit 0
  fi
  echo "$CHK_ERR" >&2
  log "ERRO: configuração da cópia externa incompleta; nada enviado" >&2
  hc_ping "${HC_OFFSITE_URL:-}" fail
  exit 3
fi

hc_ping "${HC_OFFSITE_URL:-}" start
FAILED=0

if ! rclone_env_export; then
  log "ERRO: não foi possível preparar o rclone" >&2
  hc_ping "${HC_OFFSITE_URL:-}" fail
  exit 4
fi

# Todos os dumps válidos locais (não só o do dia): recupera dias que falharam antes.
LIST=$(mktemp)
trap 'rm -f "$LIST"' EXIT
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'comemore_*.sql.gz' -size +0 -printf '%f\n' > "$LIST"
log "Cópia externa: $(wc -l < "$LIST" | tr -d ' ') dump(s) listado(s)"

rclone copy --files-from "$LIST" "$BACKUP_DIR" b2crypt:db || { log "ERRO: envio dos dumps falhou" >&2; FAILED=1; }

# Trava: pasta local vazia (volume perdido/restore em andamento) não pode esconder
# no B2 os uploads que existem lá. Remoto vazio também => sync normal.
SYNC_OK=1
LOCAL_UM=$(find "$UPLOADS_DIR" -type f -print 2>/dev/null | head -n 1 || true)
if [ -z "$LOCAL_UM" ]; then
  # código 3 do rclone = diretório não encontrado (nada no B2 ainda) => remoto vazio
  LSF_RC=0
  REMOTO=$(rclone lsf -R --files-only b2crypt:uploads) || LSF_RC=$?
  if [ "$LSF_RC" -ne 0 ] && [ "$LSF_RC" -ne 3 ]; then
    log "ERRO: listagem dos uploads no B2 falhou (código ${LSF_RC}); sync recusado" >&2
    SYNC_OK=0; FAILED=1
  elif [ -n "$REMOTO" ]; then
    log "ERRO: pasta de uploads local vazia e cópia externa não vazia; sync recusado" >&2
    SYNC_OK=0; FAILED=1
  fi
  REMOTO=
fi
if [ "$SYNC_OK" -eq 1 ]; then
  rclone sync "$UPLOADS_DIR" b2crypt:uploads || { log "ERRO: envio dos uploads falhou" >&2; FAILED=1; }
fi

if [ -s "$ENV_FILE_PATH" ]; then
  rclone copyto "$ENV_FILE_PATH" "b2crypt:env/env_$(date +%Y%m%d)" || { log "ERRO: envio do .env falhou" >&2; FAILED=1; }
else
  log "ERRO: arquivo de ambiente ausente ou vazio" >&2
  FAILED=1
fi

if [ "$FAILED" -ne 0 ]; then
  hc_ping "${HC_OFFSITE_URL:-}" fail
  exit 1
fi
log "cópia externa concluída"
hc_ping "${HC_OFFSITE_URL:-}"
