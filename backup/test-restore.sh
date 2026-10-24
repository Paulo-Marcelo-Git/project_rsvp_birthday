#!/bin/sh
# Teste do count-rows.sh e do restore-offsite.sh (SP1). Offline; mysql e rclone são
# stubs em $T/bin. Uso: sh test-restore.sh
set -eu
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0
ok()   { echo "ok   - $1"; }
fail() { echo "FAIL - $1"; FAIL=1; }

mkdir -p "$T/bin"
# Stub mysql: lista de tabelas (information_schema) e contagens fixas
cat > "$T/bin/mysql" <<'EOF2'
#!/bin/sh
q=
for a in "$@"; do q=$a; done
case "$q" in
  *information_schema*) printf 'alembic_version\nevents\ninvitees\n' ;;
  *'`alembic_version`'*) echo 1 ;;
  *'`events`'*) echo 3 ;;
  *'`invitees`'*) echo 10 ;;
esac
EOF2
# Stub rclone: lsf lista fixa; copyto/copy criam arquivos com conteúdo secreto falso
cat > "$T/bin/rclone" <<'EOF2'
#!/bin/sh
echo "$*" >> "${RCLONE_LOG:?}"
case "$1" in
  obscure) cat >/dev/null; echo OBSCURED ;;
  lsf) printf 'comemore_20260101_050000.sql.gz\ncomemore_20260103_050000.sql.gz\ncomemore_20260102_050000.sql.gz\nlixo.txt\n' ;;
  copyto) case "$3" in */env_*) echo 'SEGREDO_FAKE_DO_ENV=abc' > "$3" ;; *) echo dump > "$3" ;; esac ;;
  copy) mkdir -p "$3"; echo img > "$3/a.jpg" ;;
esac
exit 0
EOF2
chmod +x "$T/bin/mysql" "$T/bin/rclone"
export PATH="$T/bin:$PATH" RCLONE_LOG="$T/rclone.log"
export RCLONE_ENV_SCRIPT="$D/rclone-env.sh"
export DB_USER=fake-user DB_PASSWORD='senha"fake\x' DB_HOST=fake-host

# count-rows
printf 'alembic_version\t1\nevents\t3\ninvitees\t10\n' > "$T/esperado"
sh "$D/count-rows.sh" rsvp_db > "$T/cr.txt"
[ "$(cat "$T/esperado")" = "$(cat "$T/cr.txt")" ] && ok "count-rows: saída exata" || fail "count-rows: saída difere"
if sh "$D/count-rows.sh" 'x; drop' >/dev/null 2>&1; then fail "count-rows: aceitou nome inválido"; else ok "count-rows: rejeita nome inválido"; fi

# restore-offsite
export B2_ACCOUNT_ID=fake-id B2_APP_KEY=fake-key B2_BUCKET=bucket-teste CRYPT_PASSWORD=fake-pw CRYPT_SALT=fake-salt
run() { : > "$T/rclone.log"; rm -rf "$T/dest"; if sh "$D/restore-offsite.sh" "$T/dest" "$@" >"$T/out.txt" 2>"$T/err.txt"; then rc=0; else rc=$?; fi; }

run
[ "$rc" -eq 0 ] && ok "sem_data rc=0" || fail "sem_data rc=$rc"
[ -f "$T/dest/comemore_20260103_050000.sql.gz" ] && ok "sem_data: baixou o dump mais recente" || fail "sem_data: dump errado"
[ -f "$T/dest/env_20260103" ] && ok "sem_data: env da mesma data" || fail "sem_data: sem env"
[ -f "$T/dest/uploads/a.jpg" ] && ok "sem_data: uploads baixados" || fail "sem_data: sem uploads"
[ "$(stat -c %a "$T/dest/env_20260103")" = 600 ] && ok "env com modo 600" || fail "env sem modo 600"
! grep -rq 'SEGREDO_FAKE' "$T/out.txt" "$T/err.txt" && ok "saída sem conteúdo do env" || fail "conteúdo do env vazou"
grep -q 'env_20260103' "$T/out.txt" && ok "saída lista o nome do env" || fail "saída sem nome do env"

run 20260102
[ "$rc" -eq 0 ] && [ -f "$T/dest/comemore_20260102_050000.sql.gz" ] && [ -f "$T/dest/env_20260102" ] && [ ! -f "$T/dest/comemore_20260103_050000.sql.gz" ] \
  && ok "com_data: baixou 20260102" || fail "com_data: arquivo errado (rc=$rc)"

run 20250101
[ "$rc" -ne 0 ] && ok "data_inexistente rc=$rc (≠0)" || fail "data_inexistente rc=0"
! grep -qE '^copyto ' "$T/rclone.log" && ok "data_inexistente: nada baixado" || fail "data_inexistente: baixou"

run 2026-01-02
[ "$rc" -ne 0 ] && ok "data_invalida rc=$rc (≠0)" || fail "data_invalida rc=0"

B2_APP_KEY= CRYPT_SALT= run
[ "$rc" -ne 0 ] && ok "sem_vars rc=$rc (≠0)" || fail "sem_vars rc=0"
grep -q 'B2_APP_KEY' "$T/err.txt" && grep -q 'CRYPT_SALT' "$T/err.txt" && ok "sem_vars: stderr cita os nomes" || fail "sem_vars: sem nomes"
! grep -qE '^(copyto|copy|lsf) ' "$T/rclone.log" && ok "sem_vars: nada baixado" || fail "sem_vars: baixou"
! grep -qF -e fake-id -e fake-key -e fake-pw "$T/err.txt" "$T/out.txt" && ok "sem_vars: nenhum valor na saída" || fail "sem_vars: valor vazou"

if [ "$FAIL" -eq 0 ]; then echo "TODOS OK"; else echo "FALHOU"; exit 1; fi
