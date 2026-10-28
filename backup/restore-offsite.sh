#!/bin/sh
# Baixa do B2 (rclone crypt) para DESTINO: dump, .env e uploads. Imprime só nomes e tamanhos.
# Uso: sh restore-offsite.sh DESTINO [AAAAMMDD]   (sem data = dump mais recente)
# Roda no container (/rclone-env.sh) ou numa VPS nova, com rclone no PATH e as 5 variáveis
# B2_ACCOUNT_ID B2_APP_KEY B2_BUCKET CRYPT_PASSWORD CRYPT_SALT exportadas no shell.
set -eu

DEST="${1:?Uso: sh restore-offsite.sh DESTINO [AAAAMMDD]}"
DATA="${2:-}"
case "$DATA" in
  ''|[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]) ;;
  *) echo "ERRO: data deve ser AAAAMMDD" >&2; exit 2 ;;
esac

if [ -z "${RCLONE_ENV_SCRIPT:-}" ]; then
  if [ -f /rclone-env.sh ]; then RCLONE_ENV_SCRIPT=/rclone-env.sh
  else RCLONE_ENV_SCRIPT="$(cd "$(dirname "$0")" && pwd)/rclone-env.sh"; fi
fi
. "$RCLONE_ENV_SCRIPT"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

rclone_env_check || exit 1
rclone_env_export || { log "ERRO: não foi possível preparar o rclone" >&2; exit 4; }

# Tudo criado só para o dono (o .env baixado contém segredos).
umask 077
mkdir -p "$DEST"

DUMPS=$(rclone lsf b2crypt:db) || { log "ERRO: listagem do B2 falhou" >&2; exit 1; }
PAT=$DATA
[ -n "$PAT" ] || PAT='[0-9]{8}'
DUMPS=$(printf '%s\n' "$DUMPS" | grep -E "^comemore_${PAT}_[0-9]{6}\.sql\.gz\$" | sort || true)
DUMP=$(printf '%s\n' "$DUMPS" | tail -n 1)
[ -n "$DUMP" ] || { log "ERRO: nenhum dump encontrado no B2${DATA:+ para $DATA}" >&2; exit 1; }
D=${DUMP#comemore_}; D=${D%%_*}

FAILED=0
rclone copyto "b2crypt:db/$DUMP" "$DEST/$DUMP" || { log "ERRO: download do dump falhou" >&2; FAILED=1; }
rclone copyto "b2crypt:env/env_$D" "$DEST/env_$D" || { log "ERRO: download do env_$D falhou" >&2; FAILED=1; }
[ ! -f "$DEST/env_$D" ] || chmod 600 "$DEST/env_$D"
rclone copy b2crypt:uploads "$DEST/uploads" || { log "ERRO: download dos uploads falhou" >&2; FAILED=1; }

log "Baixado em $DEST (dump de $D):"
for f in "$DEST/$DUMP" "$DEST/env_$D"; do
  [ -f "$f" ] && echo "  $(basename "$f")  $(wc -c < "$f" | tr -d ' ') bytes"
done
[ -d "$DEST/uploads" ] && echo "  uploads/  $(find "$DEST/uploads" -type f | wc -l | tr -d ' ') arquivo(s)"
[ "$FAILED" -eq 0 ] || exit 1
log "Download concluído."
