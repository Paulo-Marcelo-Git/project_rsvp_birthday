#!/bin/sh
# Teste do offsite.sh + rclone-env.sh (SP1). Offline; rclone e curl são stubs
# em $T/bin. Uso: sh test-offsite.sh
set -eu
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0

mkdir -p "$T/bin" "$T/backups" "$T/uploads"
echo "arquivo" > "$T/uploads/a.jpg"

# Stub rclone: grava argumentos em $T/rclone.log; `obscure -` lê stdin e imprime
# OBSCURED; copy/sync/copyto falham com STUB_RCLONE_FAIL=1. Em copy guarda a lista
# do --files-from e o ambiente RCLONE_CONFIG_B2CRYPT_* (sem senhas).
cat > "$T/bin/rclone" <<'EOF'
#!/bin/sh
echo "$*" >> "${RCLONE_LOG:?}"
case "$1" in
  obscure) cat >/dev/null; echo OBSCURED; exit 0 ;;
esac
env | grep -E '^RCLONE_CONFIG_B2CRYPT_(DIRECTORY_NAME_ENCRYPTION|REMOTE)=' >> "${RCLONE_LOG}.env" || true
if [ "$1" = copy ]; then
  prev=
  for a in "$@"; do
    [ "$prev" = "--files-from" ] && cp "$a" "${RCLONE_LOG}.files"
    prev=$a
  done
fi
if [ "${STUB_RCLONE_FAIL:-0}" = "1" ]; then exit 1; fi
exit 0
EOF
chmod +x "$T/bin/rclone"

cat > "$T/bin/curl" <<'EOF'
#!/bin/sh
for a in "$@"; do u=$a; done
echo "${u#https://hc.test/}" >> "${CURL_LOG:?}"
exit 0
EOF
chmod +x "$T/bin/curl"

export PATH="$T/bin:$PATH"
export HC_SCRIPT="$D/hc.sh" RCLONE_ENV_SCRIPT="$D/rclone-env.sh"
export CURL_LOG="$T/curl.log" RCLONE_LOG="$T/rclone.log"
export BACKUP_DIR="$T/backups" UPLOADS_DIR="$T/uploads" ENV_FILE_PATH="$T/envfile"
echo "FAKE=1" > "$T/envfile"
SECRET_PW='senha-fake'"'"'com"aspas $x'
SECRET_KEY='fake-key-secreta'
CFG() {
  export B2_ACCOUNT_ID=fake-id B2_APP_KEY=$SECRET_KEY B2_BUCKET=bucket-teste \
         CRYPT_PASSWORD=$SECRET_PW CRYPT_SALT=fake-salt
}
CLR() { unset B2_ACCOUNT_ID B2_APP_KEY B2_BUCKET CRYPT_PASSWORD CRYPT_SALT || true; HC_OFFSITE_URL=; export HC_OFFSITE_URL; }
reset() { : > "$T/curl.log"; : > "$T/rclone.log"; rm -f "$T/rclone.log.env" "$T/rclone.log.files"; }
run() { if sh "$D/offsite.sh" >"$T/out.txt" 2>"$T/err.txt"; then rc=0; else rc=$?; fi; }
transfers() { grep -cE '^(copy|sync|copyto) ' "$T/rclone.log" || true; }

ok()   { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAIL=1; }
HCO=https://hc.test/uuid-o

# Dumps: 3 válidos, 1 .tmp, 1 vazio
for d in 20260101 20260102 20260103; do echo dump > "$T/backups/comemore_${d}_050000.sql.gz"; done
echo parcial > "$T/backups/comemore_20260104_050000.sql.gz.tmp"
: > "$T/backups/comemore_20260105_050000.sql.gz"

# 1) dev_sem_config
CLR; reset; run
[ "$rc" -eq 0 ] && ok "dev_sem_config rc=0" || fail "dev_sem_config rc=$rc"
[ "$(transfers)" = 0 ] && ok "dev_sem_config: sem copy/sync" || fail "dev_sem_config: transferiu"
grep -q 'cópia externa desabilitada' "$T/out.txt" "$T/err.txt" && ok "dev_sem_config: aviso" || fail "dev_sem_config: sem aviso"

# 2) config_parcial
CLR; CFG; export B2_APP_KEY=; export HC_OFFSITE_URL=$HCO; reset; run
[ "$rc" -ne 0 ] && ok "config_parcial rc=$rc (≠0)" || fail "config_parcial rc=0"
grep -qx 'uuid-o/fail' "$T/curl.log" && ok "config_parcial: ping /fail" || fail "config_parcial: sem /fail"
[ "$(transfers)" = 0 ] && ok "config_parcial: nada enviado" || fail "config_parcial: enviou"
grep -q 'B2_APP_KEY' "$T/err.txt" && ok "config_parcial: stderr cita B2_APP_KEY" || fail "config_parcial: stderr sem nome"
! grep -qF -e "$SECRET_PW" -e "$SECRET_KEY" -e fake-id "$T/err.txt" "$T/out.txt" && ok "config_parcial: nenhum valor na saída" || fail "config_parcial: valor vazou"

# 2b) b2_parcial_sem_hc: só B2_BUCKET, sem HC => falha (não pula)
CLR; export B2_BUCKET=bucket-teste; reset; run
[ "$rc" -eq 3 ] && ok "b2_parcial_sem_hc rc=3" || fail "b2_parcial_sem_hc rc=$rc"
MISS=1; for n in B2_ACCOUNT_ID B2_APP_KEY CRYPT_PASSWORD CRYPT_SALT; do grep -q "$n" "$T/err.txt" || MISS=0; done
[ "$MISS" = 1 ] && ok "b2_parcial_sem_hc: stderr lista os 4 nomes" || fail "b2_parcial_sem_hc: nomes faltando no stderr"
! grep -q 'bucket-teste' "$T/err.txt" && ok "b2_parcial_sem_hc: sem valores" || fail "b2_parcial_sem_hc: valor vazou"
[ "$(transfers)" = 0 ] && ok "b2_parcial_sem_hc: nada enviado" || fail "b2_parcial_sem_hc: enviou"
[ ! -s "$T/curl.log" ] && ok "b2_parcial_sem_hc: curl vazio" || fail "b2_parcial_sem_hc: curl chamado"

# 3) envia_tudo
CLR; CFG; export HC_OFFSITE_URL=$HCO; reset; run
[ "$rc" -eq 0 ] && ok "envia_tudo rc=0" || fail "envia_tudo rc=$rc"
EXP=$(printf 'comemore_20260101_050000.sql.gz\ncomemore_20260102_050000.sql.gz\ncomemore_20260103_050000.sql.gz')
[ "$(sort "$T/rclone.log.files" 2>/dev/null)" = "$EXP" ] && ok "envia_tudo: files-from = 3 dumps válidos" || fail "envia_tudo: files-from inesperado: $(tr '\n' ' ' < "$T/rclone.log.files" 2>/dev/null)"
grep -q "^sync $UPLOADS_DIR b2crypt:uploads" "$T/rclone.log" && ok "envia_tudo: sync uploads" || fail "envia_tudo: sem sync uploads"
grep -q "^copyto $ENV_FILE_PATH b2crypt:env/env_$(date +%Y%m%d)\$" "$T/rclone.log" && ok "envia_tudo: copyto env" || fail "envia_tudo: sem copyto env"
[ "$(cat "$T/curl.log")" = "$(printf 'uuid-o/start\nuuid-o')" ] && ok "envia_tudo: pings start e sucesso" || fail "envia_tudo: curl.log: $(tr '\n' ' ' < "$T/curl.log")"
grep -q 'cópia externa concluída' "$T/out.txt" && ok "envia_tudo: log de conclusão" || fail "envia_tudo: sem log"

# 4) rclone_falha
CLR; CFG; export HC_OFFSITE_URL=$HCO; reset; STUB_RCLONE_FAIL=1 run
[ "$rc" -ne 0 ] && ok "rclone_falha rc=$rc (≠0)" || fail "rclone_falha rc=0"
grep -qx 'uuid-o/fail' "$T/curl.log" && ok "rclone_falha: ping /fail" || fail "rclone_falha: sem /fail"
! grep -qx 'uuid-o' "$T/curl.log" && ok "rclone_falha: sem ping de sucesso" || fail "rclone_falha: pingou sucesso"

# 4b) env_ausente => falha
CLR; CFG; export HC_OFFSITE_URL=$HCO; reset; ENV_FILE_PATH="$T/nao-existe" run
[ "$rc" -ne 0 ] && ok "env_ausente rc=$rc (≠0)" || fail "env_ausente rc=0"
grep -qx 'uuid-o/fail' "$T/curl.log" && ok "env_ausente: ping /fail" || fail "env_ausente: sem /fail"

# 5) segredo_fora_do_ps
CLR; CFG; reset; run
grep -q '^sync ' "$T/rclone.log" && ok "segredo_fora_do_ps: houve sync (checagem não vazia)" || fail "segredo_fora_do_ps: sem sync"
! grep -qF -e "$SECRET_PW" -e "$SECRET_KEY" "$T/rclone.log" && ok "segredo_fora_do_ps: argv limpo" || fail "segredo_fora_do_ps: segredo em argv"

# 6) remote_config
grep -qx 'RCLONE_CONFIG_B2CRYPT_DIRECTORY_NAME_ENCRYPTION=false' "$T/rclone.log.env" && ok "remote_config: dir encryption false" || fail "remote_config: dir encryption"
grep -qx 'RCLONE_CONFIG_B2CRYPT_REMOTE=b2:bucket-teste/comemore' "$T/rclone.log.env" && ok "remote_config: remote" || fail "remote_config: remote"

if [ "$FAIL" -eq 0 ]; then echo "TODOS OK"; else echo "FALHOU"; exit 1; fi
