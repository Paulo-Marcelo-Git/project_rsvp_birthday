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

# Ambiente comum (valores obviamente falsos)
export PATH="$T/bin:$PATH"
export UPLOADS_DIR="$T/uploads"
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

if [ "$FAIL" -eq 0 ]; then echo "TODOS OK"; else echo "FALHOU"; exit 1; fi
