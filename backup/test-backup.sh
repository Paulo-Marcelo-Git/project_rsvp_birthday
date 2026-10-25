#!/bin/sh
# Teste do backup.sh (SP1). Offline; mysqldump (e depois curl/rclone) são stubs
# em $T/bin. Uso: sh test-backup.sh [backup.sh]
set -eu
SCRIPT=${1:-$(dirname "$0")/backup.sh}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0

mkdir -p "$T/bin" "$T/uploads"
echo "arquivo" > "$T/uploads/a.jpg"

# Stub mysqldump: STUB_DUMP_FAIL=1 => saída parcial e código 1
cat > "$T/bin/mysqldump" <<'EOF'
#!/bin/sh
if [ "${STUB_DUMP_FAIL:-0}" = "1" ]; then echo "-- parcial"; exit 1; fi
echo "-- dump ok"
EOF
chmod +x "$T/bin/mysqldump"

# Stub curl: grava só o sufixo após a URL base de teste em $T/curl.log;
# STUB_CURL_FAIL=1 => sai com 7 (não conectou)
cat > "$T/bin/curl" <<'EOF2'
#!/bin/sh
for a in "$@"; do u=$a; done
echo "${u#https://hc.test/}" >> "${CURL_LOG:?}"
if [ "${STUB_CURL_FAIL:-0}" = "1" ]; then echo "curl: (7) falha simulada" >&2; exit 7; fi
exit 0
EOF2
chmod +x "$T/bin/curl"

# Stub offsite: registra a chamada em $T/offsite.log; STUB_OFFSITE_RC define o código;
# STUB_OFFSITE_PING=1 => pinga HC_OFFSITE_URL/start como o offsite.sh real (ordem dos pings)
cat > "$T/offsite-stub.sh" <<'EOF3'
#!/bin/sh
echo chamado >> "${OFFSITE_LOG:?}"
[ "${STUB_OFFSITE_PING:-0}" != 1 ] || curl -fsS "${HC_OFFSITE_URL}/start"
exit "${STUB_OFFSITE_RC:-0}"
EOF3

# Ambiente comum (valores obviamente falsos)
export PATH="$T/bin:$PATH"
export UPLOADS_DIR="$T/uploads"
export HC_SCRIPT="$(cd "$(dirname "$0")" && pwd)/hc.sh"
export CURL_LOG="$T/curl.log"
export OFFSITE_SCRIPT="$T/offsite-stub.sh" OFFSITE_LOG="$T/offsite.log"
export HC_BACKUP_URL= HC_OFFSITE_URL=
export DB_USER=fake-user DB_PASSWORD=fake-pass DB_HOST=fake-host DB_NAME=fake_db

ok()   { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAIL=1; }

# conta arquivos que casam com o padrão em $1
count() { find "$1" -maxdepth 1 -name "$2" | wc -l | tr -d ' '; }

# 1) dump_ok
B="$T/backups-ok"
if BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "dump_ok rc=0" || fail "dump_ok rc=$rc"
[ "$(count "$B" 'comemore_*.sql.gz')" = 1 ] && ok "dump_ok: 1 .sql.gz" || fail "dump_ok: esperava 1 .sql.gz"
F=$(find "$B" -maxdepth 1 -name 'comemore_*.sql.gz' | head -n1)
if [ -n "$F" ] && gzip -t "$F" 2>/dev/null; then ok "dump_ok: gzip -t passa"; else fail "dump_ok: gzip -t falhou"; fi
[ "$(count "$B" '*.tmp')" = 0 ] && ok "dump_ok: nenhum .tmp sobrou" || fail "dump_ok: sobrou .tmp"

# 2) dump_falha
B="$T/backups-falha"
if STUB_DUMP_FAIL=1 BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "dump_falha rc=$rc (≠0)" || fail "dump_falha: rc=0, esperava ≠0"
[ "$(count "$B" 'comemore_*.sql.gz')" = 0 ] && ok "dump_falha: nenhum .sql.gz" || fail "dump_falha: sobrou .sql.gz truncado"
[ "$(count "$B" 'comemore_*.sql.gz.tmp')" = 0 ] && ok "dump_falha: nenhum .sql.gz.tmp" || fail "dump_falha: sobrou .sql.gz.tmp"

# Pings do Healthchecks (URLs falsas)
HCB=https://hc.test/uuid-b
HCO=https://hc.test/uuid-o

# 3) ping_sucesso
B="$T/backups-ping-ok"; : > "$T/curl.log"
if HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "ping_sucesso rc=0" || fail "ping_sucesso rc=$rc"
[ "$(cat "$T/curl.log")" = "$(printf 'uuid-b/start\nuuid-b')" ] && ok "ping_sucesso: start e depois sucesso" || fail "ping_sucesso: curl.log inesperado: $(tr '\n' ' ' < "$T/curl.log")"

# 4) ping_falha_dump (dump falhou => os dois alertas)
B="$T/backups-ping-dump"; : > "$T/curl.log"
if STUB_DUMP_FAIL=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "ping_falha_dump rc=$rc (≠0)" || fail "ping_falha_dump: rc=0"
grep -qx 'uuid-b/fail' "$T/curl.log" && ok "ping_falha_dump: uuid-b/fail" || fail "ping_falha_dump: sem uuid-b/fail"
grep -qx 'uuid-o/fail' "$T/curl.log" && ok "ping_falha_dump: uuid-o/fail" || fail "ping_falha_dump: sem uuid-o/fail"
! grep -qx 'uuid-b' "$T/curl.log" && ok "ping_falha_dump: sem ping de sucesso" || fail "ping_falha_dump: pingou sucesso"

# 5) ping_falha_tar (uploads inexistente => tar rc 2)
B="$T/backups-ping-tar"; : > "$T/curl.log"
if UPLOADS_DIR="$T/nao-existe" HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "ping_falha_tar rc=$rc (≠0)" || fail "ping_falha_tar: rc=0"
grep -qx 'uuid-b/fail' "$T/curl.log" && ok "ping_falha_tar: uuid-b/fail" || fail "ping_falha_tar: sem uuid-b/fail"
! grep -qx 'uuid-o/fail' "$T/curl.log" && ok "ping_falha_tar: sem uuid-o/fail (dump terminou)" || fail "ping_falha_tar: pingou uuid-o/fail"

# 6) hc_fora_do_ar (curl falha sempre; backup segue e sai 0)
B="$T/backups-hc-off"; : > "$T/curl.log"
if STUB_CURL_FAIL=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >"$T/out-hc.txt" 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "hc_fora_do_ar rc=0" || fail "hc_fora_do_ar rc=$rc"
[ "$(count "$B" 'comemore_*.sql.gz')" = 1 ] && ok "hc_fora_do_ar: dump gerado" || fail "hc_fora_do_ar: sem dump"
grep -q 'AVISO: ping do healthcheck falhou' "$T/out-hc.txt" && ok "hc_fora_do_ar: aviso emitido" || fail "hc_fora_do_ar: sem aviso"

# 7) sem_hc
B="$T/backups-sem-hc"; : > "$T/curl.log"
if HC_BACKUP_URL= HC_OFFSITE_URL= BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "sem_hc rc=0" || fail "sem_hc rc=$rc"
[ ! -s "$T/curl.log" ] && ok "sem_hc: curl não chamado" || fail "sem_hc: curl chamado"

# 8) log_sem_url (sucesso, falha de dump e curl fora do ar)
: > "$T/all-out.txt"
HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$T/b-l1" sh "$SCRIPT" >>"$T/all-out.txt" 2>&1 || true
STUB_DUMP_FAIL=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$T/b-l2" sh "$SCRIPT" >>"$T/all-out.txt" 2>&1 || true
STUB_CURL_FAIL=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$T/b-l3" sh "$SCRIPT" >>"$T/all-out.txt" 2>&1 || true
! grep -q 'hc.test' "$T/all-out.txt" && ok "log_sem_url: nenhuma saída contém a URL" || fail "log_sem_url: URL vazou na saída"

# 9) offsite_chamado (dump ok)
: > "$T/offsite.log"
if BACKUP_DIR="$T/b-o1" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "offsite_chamado rc=0" || fail "offsite_chamado rc=$rc"
[ "$(wc -l < "$T/offsite.log" | tr -d ' ')" = 1 ] && ok "offsite_chamado: 1 chamada" || fail "offsite_chamado: chamadas inesperadas"

# 10) offsite_nao_chamado (dump falhou)
: > "$T/offsite.log"
if STUB_DUMP_FAIL=1 BACKUP_DIR="$T/b-o2" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "offsite_nao_chamado rc=$rc (≠0)" || fail "offsite_nao_chamado rc=0"
[ ! -s "$T/offsite.log" ] && ok "offsite_nao_chamado: não chamado" || fail "offsite_nao_chamado: foi chamado"

# 11) offsite_com_tar_falho (tar falhou => offsite chamado mesmo assim, rc ≠ 0)
: > "$T/offsite.log"
if UPLOADS_DIR="$T/nao-existe" BACKUP_DIR="$T/b-o3" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "offsite_com_tar_falho rc=$rc (≠0)" || fail "offsite_com_tar_falho rc=0"
[ "$(wc -l < "$T/offsite.log" | tr -d ' ')" = 1 ] && ok "offsite_com_tar_falho: offsite chamado" || fail "offsite_com_tar_falho: não chamado"

# 12) offsite_falha_nao_marca_local (offsite rc=1: check local ok, rc final ≠ 0)
B="$T/b-o4"; : > "$T/curl.log"
if STUB_OFFSITE_RC=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "offsite_falha_nao_marca_local rc=$rc (≠0)" || fail "offsite_falha_nao_marca_local rc=0"
grep -qx 'uuid-b' "$T/curl.log" && ok "offsite_falha_nao_marca_local: uuid-b sucesso" || fail "offsite_falha_nao_marca_local: sem sucesso local"
! grep -qx 'uuid-b/fail' "$T/curl.log" && ok "offsite_falha_nao_marca_local: sem uuid-b/fail" || fail "offsite_falha_nao_marca_local: uuid-b/fail"

# 13) ping_local_antes_offsite: sucesso local pingado ao fim da parte local (antes do offsite),
# uma vez só
B="$T/b-o5"; : > "$T/curl.log"
if STUB_OFFSITE_PING=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -eq 0 ] && ok "ping_local_antes_offsite rc=0" || fail "ping_local_antes_offsite rc=$rc"
[ "$(cat "$T/curl.log")" = "$(printf 'uuid-b/start\nuuid-b\nuuid-o/start')" ] && ok "ping_local_antes_offsite: uuid-b antes de uuid-o/start" || fail "ping_local_antes_offsite: curl.log: $(tr '\n' ' ' < "$T/curl.log")"

# 14) ping_falha_tar_antes_offsite: /fail local também sai antes do offsite, uma vez só
B="$T/b-o6"; : > "$T/curl.log"
if STUB_OFFSITE_PING=1 UPLOADS_DIR="$T/nao-existe" HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$rc" -ne 0 ] && ok "ping_falha_tar_antes_offsite rc=$rc (≠0)" || fail "ping_falha_tar_antes_offsite rc=0"
[ "$(cat "$T/curl.log")" = "$(printf 'uuid-b/start\nuuid-b/fail\nuuid-o/start')" ] && ok "ping_falha_tar_antes_offsite: ordem e sem repetição" || fail "ping_falha_tar_antes_offsite: curl.log: $(tr '\n' ' ' < "$T/curl.log")"

# 15) offsite_falha_um_ping_local: offsite rc=1 => uuid-b de sucesso exatamente uma vez
B="$T/b-o7"; : > "$T/curl.log"
if STUB_OFFSITE_RC=1 HC_BACKUP_URL=$HCB HC_OFFSITE_URL=$HCO BACKUP_DIR="$B" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
[ "$(grep -cx 'uuid-b' "$T/curl.log")" = 1 ] && ok "offsite_falha_um_ping_local: 1 ping de sucesso" || fail "offsite_falha_um_ping_local: curl.log: $(tr '\n' ' ' < "$T/curl.log")"

if [ "$FAIL" -eq 0 ]; then echo "TODOS OK"; else echo "FALHOU"; exit 1; fi
