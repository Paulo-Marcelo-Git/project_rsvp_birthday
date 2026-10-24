#!/bin/sh
# Contagem de linhas por tabela (conferir produção x restore). Só números, nenhuma linha de dado.
# Uso: docker exec rsvp_backup sh /count-rows.sh NOME_DB   -> "tabela<TAB>COUNT(*)"
set -eu

DB="${1:?Uso: sh /count-rows.sh NOME_DB}"
case "$DB" in
  *[!A-Za-z0-9_]*|'') echo "ERRO: nome de banco inválido" >&2; exit 2 ;;
esac

# Credenciais via arquivo de opções (fora do `ps`), removido ao sair.
umask 077
CNF=$(mktemp)
trap 'rm -f "$CNF"' EXIT
esc() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }
{
  printf '[client]\n'
  printf 'user="%s"\n' "$(esc "$DB_USER")"
  printf 'password="%s"\n' "$(esc "$DB_PASSWORD")"
  printf 'host="%s"\n' "$(esc "$DB_HOST")"
} > "$CNF"

TABLES=$(mysql --defaults-extra-file="$CNF" -N -B \
  -e "SELECT table_name FROM information_schema.tables WHERE table_schema='${DB}' ORDER BY table_name")

for t in $TABLES; do
  n=$(mysql --defaults-extra-file="$CNF" -N -B "$DB" -e "SELECT COUNT(*) FROM \`${t}\`")
  printf '%s\t%s\n' "$t" "$n"
done
