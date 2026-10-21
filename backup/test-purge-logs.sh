#!/bin/sh
# Teste do purge-logs.sh (PR-0). Offline; precisa de GNU find/touch/date
# (imagem do backup ou do backend). Uso: sh test-purge-logs.sh [purge-logs.sh]
set -eu
SCRIPT=${1:-$(dirname "$0")/purge-logs.sh}
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
FAIL=0

mk() { # $1 = arquivo, $2 = idade em horas
  mkdir -p "$(dirname "$1")"
  : > "$1"
  touch -d "@$(( $(date +%s) - $2 * 3600 ))" "$1"
}
gone() {
  if [ -e "$1" ]; then echo "FAIL - deveria ter apagado: $1"; FAIL=1; else echo "ok   - apagou $(basename "$1")"; fi
}
kept() {
  if [ -e "$1" ]; then echo "ok   - manteve $1"; else echo "FAIL - apagou indevidamente: $1"; FAIL=1; fi
}

# 1) Default (5 dias => -mtime +4)
L="$T/logs"
mk "$L/app-2026-01-01.log" 200
mk "$L/app-2026-01-02.log" 121
mk "$L/app-2026-01-03.log" 119
mk "$L/app-2026-01-04.log" 0
mk "$L/app.log" 500
mk "$L/app-rascunho.log" 500
mk "$L/notas.txt" 500
mk "$L/sub/app-2025-12-01.log" 500
LOG_DIR="$L" sh "$SCRIPT"
gone "$L/app-2026-01-01.log"
gone "$L/app-2026-01-02.log"
kept "$L/app-2026-01-03.log"
kept "$L/app-2026-01-04.log"
kept "$L/app.log"
kept "$L/app-rascunho.log"
kept "$L/notas.txt"
kept "$L/sub/app-2025-12-01.log"

# 2) LOG_RETENTION_DAYS=2 (=> -mtime +1)
L2="$T/logs2"
mk "$L2/app-2026-02-01.log" 49
mk "$L2/app-2026-02-02.log" 47
LOG_DIR="$L2" LOG_RETENTION_DAYS=2 sh "$SCRIPT"
gone "$L2/app-2026-02-01.log"
kept "$L2/app-2026-02-02.log"

# 3) Valor inválido: sai com 2 e não apaga nada
for bad in abc 0 -1 5x; do
  L3="$T/logs3-$bad"
  mk "$L3/app-2026-03-01.log" 500
  if LOG_DIR="$L3" LOG_RETENTION_DAYS="$bad" sh "$SCRIPT" >/dev/null 2>&1; then rc=0; else rc=$?; fi
  if [ "$rc" -eq 2 ]; then echo "ok   - LOG_RETENTION_DAYS=$bad recusado (rc=2)"; else echo "FAIL - LOG_RETENTION_DAYS=$bad rc=$rc"; FAIL=1; fi
  kept "$L3/app-2026-03-01.log"
done

# 4) Diretório inexistente: sai 0 sem erro
if LOG_DIR="$T/nao-existe" sh "$SCRIPT" >/dev/null 2>&1; then echo "ok   - LOG_DIR inexistente sai 0"; else echo "FAIL - LOG_DIR inexistente"; FAIL=1; fi

if [ "$FAIL" -eq 0 ]; then echo "TODOS OK"; else echo "FALHOU"; exit 1; fi
