# Ping do Healthchecks.io (usar com `.`). Best-effort: nunca derruba o backup
# e nunca imprime a URL (contém UUID secreto).
# Uso: hc_ping URL [start|fail]   (URL vazia => não faz nada)
hc_ping() {
  [ -n "${1:-}" ] || return 0
  _hc_url=$1
  [ -z "${2:-}" ] || _hc_url="${_hc_url}/$2"
  # stderr do curl descartado: mensagens de erro podem citar a URL
  if ! curl -fsS -m 10 --retry 3 -o /dev/null "$_hc_url" 2>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] AVISO: ping do healthcheck falhou" >&2
  fi
  return 0
}
