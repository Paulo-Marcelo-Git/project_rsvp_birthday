#!/bin/bash
# Teste da config do nginx (SP2) em container descartavel nginx:1.24-alpine
# (mesma versao da producao). Offline; certificado autoassinado.
# Uso: bash deploy/nginx/test-nginx.sh
# Os testes de rate limit compartilham estado de zona no mesmo container, entao
# rodam por ultimo e nesta ordem: static_folga, rsvp_folga, 429_rsvp, 429_login.
set -u
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
C="nginx-test-$$-$RANDOM"
cleanup() { docker rm -f "$C" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
FAIL=0

ok()   { echo "OK $1"; }
fail() { echo "FALHA $1${2:+ ($2)}"; FAIL=1; }

command -v docker >/dev/null || { echo "docker ausente"; exit 2; }
command -v openssl >/dev/null || { echo "openssl ausente"; exit 2; }

# --- TLS de teste, nos mesmos caminhos que o site usa ---
LE="$T/le"
mkdir -p "$LE/live/zapbyte.com.br" "$T/log"
openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj "/CN=zapbyte.com.br" \
  -addext "subjectAltName=DNS:zapbyte.com.br,DNS:www.zapbyte.com.br" \
  -keyout "$LE/live/zapbyte.com.br/privkey.pem" \
  -out "$LE/live/zapbyte.com.br/fullchain.pem" 2>/dev/null
echo "ssl_protocols TLSv1.2 TLSv1.3;" > "$LE/options-ssl-nginx.conf"
openssl dhparam -dsaparam -out "$LE/ssl-dhparams.pem" 2048 2>/dev/null
chmod -R a+rX "$T"
chmod 777 "$T/log"

# --- Sobe o container (monta so o que existe) ---
ARGS=(-v "$D/zapbyte.com.br.conf:/etc/nginx/conf.d/zz-site.conf:ro"
      -v "$D/test/upstream-stub.conf:/etc/nginx/conf.d/stub.conf:ro"
      -v "$D/test/prod-http.conf:/etc/nginx/conf.d/00-prod-http.conf:ro"
      -v "$LE:/etc/letsencrypt:ro"
      -v "$T/log:/var/log/nginx")
[ -f "$D/comemore.conf" ] && ARGS+=(-v "$D/comemore.conf:/etc/nginx/conf.d/comemore.conf:ro")
[ -d "$D/snippets" ] && ARGS+=(-v "$D/snippets:/etc/nginx/snippets:ro")

docker run -d --name "$C" -p 127.0.0.1:18443:443 -p 127.0.0.1:18080:80 "${ARGS[@]}" \
  nginx:1.24-alpine sh -c "rm -f /etc/nginx/conf.d/default.conf; exec nginx -g 'daemon off;'" >/dev/null \
  || { echo "falha ao subir o container"; exit 2; }

# espera o nginx responder
for _ in $(seq 1 30); do
  curl -sk -o /dev/null --resolve zapbyte.com.br:18443:127.0.0.1 https://zapbyte.com.br:18443/ && break
  sleep 0.3
done

ACCESS="$T/log/access.log"
CURL=(curl -sk --resolve zapbyte.com.br:18443:127.0.0.1)
U=https://zapbyte.com.br:18443

hdrs() { "${CURL[@]}" -D - -o /dev/null "$@"; }          # so cabecalhos
codes() { "${CURL[@]}" -o /dev/null -w '%{http_code}\n' "$@"; }

check_sec_headers() { # $1 = cabecalhos; imprime o que faltou
  local h=$1 miss=""
  echo "$h" | grep -qiE '^strict-transport-security: max-age=31536000[[:space:]]*$' || miss="$miss HSTS"
  echo "$h" | grep -qiE '^strict-transport-security:.*(includeSubDomains|preload)' && miss="$miss HSTS-extra"
  echo "$h" | grep -qiE '^x-frame-options: DENY[[:space:]]*$' || miss="$miss XFO"
  echo "$h" | grep -qiE '^referrer-policy: strict-origin-when-cross-origin[[:space:]]*$' || miss="$miss Referrer"
  echo "$h" | grep -qiF 'permissions-policy: camera=(), microphone=(), geolocation=()' || miss="$miss Permissions"
  echo "$miss"
}

t_sintaxe() {
  docker exec "$C" nginx -t >/dev/null 2>&1 && ok t_sintaxe || fail t_sintaxe
}

t_headers_login() {
  local h miss; h=$(hdrs $U/login); miss=$(check_sec_headers "$h")
  echo "$h" | grep -qiE '^server: nginx[[:space:]]*$' || miss="$miss Server"
  [ -z "${miss// /}" ] && ok t_headers_login || fail t_headers_login "$miss"
}

t_headers_invite_404() {
  local h miss; h=$(hdrs $U/invite/token-inexistente); miss=$(check_sec_headers "$h")
  echo "$h" | grep -qiE '^x-robots-tag: noindex, nofollow[[:space:]]*$' || miss="$miss Robots"
  [ -z "${miss// /}" ] && ok t_headers_invite_404 || fail t_headers_invite_404 "$miss"
}

t_sem_nosniff_duplicado() {
  local n=0 u c
  for u in /login /invite/x /static/x /; do
    c=$(hdrs $U$u | grep -ci '^x-content-type-options:' || true)
    n=$((n + c))
  done
  [ "$n" -eq 0 ] && ok t_sem_nosniff_duplicado || fail t_sem_nosniff_duplicado "$n ocorrencias"
}

t_upload_51mb() {
  local f="$T/51mb.bin" code
  head -c $((51 * 1024 * 1024)) /dev/zero > "$f"
  code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST --data-binary @"$f" $U/invite/x)
  rm -f "$f"
  [ "$code" != 413 ] && ok t_upload_51mb || fail t_upload_51mb "status $code"
}

t_proxy_headers() {
  local a b
  a=$("${CURL[@]}" $U/login); b=$("${CURL[@]}" $U/)
  if echo "$a" | grep -q 'xfp=https' && echo "$b" | grep -q 'xfp=https' \
     && echo "$a" | grep -qE 'xri=[^ ]+' && echo "$b" | grep -qE 'xri=[^ ]+'; then
    ok t_proxy_headers
  else fail t_proxy_headers "$a | $b"; fi
}

t_log_mascara() {
  "${CURL[@]}" -o /dev/null $U/invite/SEGREDO1
  "${CURL[@]}" -o /dev/null $U/reset_password/SEGREDO2
  "${CURL[@]}" -o /dev/null "$U/verify-email/SEGREDO3?x=1"
  if grep -q '/invite/\*\*\*' "$ACCESS" && grep -q '/reset_password/\*\*\*' "$ACCESS" \
     && grep -q '/verify-email/\*\*\*?x=1' "$ACCESS" && [ "$(grep -c SEGREDO "$ACCESS")" -eq 0 ]; then
    ok t_log_mascara
  else fail t_log_mascara "$(grep -c SEGREDO "$ACCESS") linhas com token"; fi
}

t_log_referer() {
  "${CURL[@]}" -o /dev/null -H "Referer: https://zapbyte.com.br/invite/SEGREDO4" "$U/?marca=ref4"
  # positivo: a requisicao foi logada e o Referer saiu mascarado
  if grep 'marca=ref4' "$ACCESS" | grep -q '/invite/\*\*\*' && [ "$(grep -c SEGREDO4 "$ACCESS")" -eq 0 ]; then
    ok t_log_referer
  else fail t_log_referer "linha ausente ou token no log"; fi
}

t_log_porta80() {
  curl -s -o /dev/null -H "Host: zapbyte.com.br" "http://127.0.0.1:18080/invite/SEGREDO5?marca=p80"
  # positivo: a requisicao da porta 80 foi logada, mascarada
  if grep 'marca=p80' "$ACCESS" | grep -q '/invite/\*\*\*' && [ "$(grep -c SEGREDO5 "$ACCESS")" -eq 0 ]; then
    ok t_log_porta80
  else fail t_log_porta80 "linha ausente ou token no log"; fi
}

t_redirect_80() {
  local h
  h=$(curl -s -D - -o /dev/null -H "Host: zapbyte.com.br" http://127.0.0.1:18080/login)
  if echo "$h" | head -1 | grep -q ' 301' \
     && echo "$h" | grep -qiE '^location: https://zapbyte.com.br/login[[:space:]]*$'; then
    ok t_redirect_80
  else fail t_redirect_80 "$(echo "$h" | head -1)"; fi
}

# --- rate limit: N requisicoes seguidas numa unica chamada de curl ---
burst() { # $1=N $2=url [args extras de curl]
  local n=$1 u=$2; shift 2
  local urls=(); local i
  for i in $(seq 1 "$n"); do urls+=("$u"); done
  "${CURL[@]}" -o /dev/null -w '%{http_code}\n' "$@" "${urls[@]}"
}

t_static_folga() {
  local n; n=$(burst 40 $U/static/x | grep -c 429)
  [ "$n" -eq 0 ] && ok t_static_folga || fail t_static_folga "$n respostas 429"
}
t_rsvp_folga() {
  local n; n=$(burst 40 $U/invite/abc | grep -c 429)
  [ "$n" -eq 0 ] && ok t_rsvp_folga || fail t_rsvp_folga "$n respostas 429"
}
t_429_rsvp() {
  local n; n=$(burst 150 $U/invite/abc | grep -c 429)
  [ "$n" -ge 1 ] && ok t_429_rsvp || fail t_429_rsvp "nenhum 429"
}
t_429_login() {
  local n; n=$(burst 40 $U/login -X POST | grep -c 429)
  [ "$n" -ge 1 ] && ok t_429_login || fail t_429_login "nenhum 429"
}

t_sintaxe
t_headers_login
t_headers_invite_404
t_sem_nosniff_duplicado
t_upload_51mb
t_proxy_headers
t_log_mascara
t_log_referer
t_log_porta80
t_redirect_80
# rate limit por ultimo, nesta ordem (estado de zona compartilhado)
t_static_folga
t_rsvp_folga
t_429_rsvp
t_429_login

exit $FAIL
