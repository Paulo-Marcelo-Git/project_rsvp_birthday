#!/bin/bash
# Teste da config do nginx (SP2) em container descartavel nginx:1.24-alpine
# (mesma versao da producao). Offline; certificado autoassinado.
# Uso: bash deploy/nginx/test-nginx.sh
# Os testes de rate limit compartilham estado de zona no mesmo container, entao
# rodam por ultimo e nesta ordem: static_folga, rsvp_folga, 429_rsvp, 429_login, zonas_auth_geral.
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
  # o stub responde 404 em /invite/: 404 prova que o corpo chegou ao upstream
  [ "$code" = 404 ] && ok t_upload_51mb || fail t_upload_51mb "status $code (esperado 404 do stub)"
}

t_upload_56mb() {
  local f="$T/56mb.bin" code
  head -c $((56 * 1024 * 1024)) /dev/zero > "$f"
  code=$("${CURL[@]}" -o /dev/null -w '%{http_code}' -X POST --data-binary @"$f" $U/invite/x)
  rm -f "$f"
  [ "$code" = 413 ] && ok t_upload_56mb || fail t_upload_56mb "status $code (esperado 413)"
}

t_proxy_headers() {
  local a b
  a=$("${CURL[@]}" $U/login); b=$("${CURL[@]}" $U/)
  if echo "$a" | grep -q 'xfp=https' && echo "$b" | grep -q 'xfp=https' \
     && echo "$a" | grep -qE 'xri=[^ ]+' && echo "$b" | grep -qE 'xri=[^ ]+' \
     && echo "$a" | grep -qE 'xff=[0-9a-f.:]+ ' && echo "$b" | grep -qE 'xff=[0-9a-f.:]+ ' \
     && echo "$a" | grep -q 'host=zapbyte.com.br$' && echo "$b" | grep -q 'host=zapbyte.com.br$'; then
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

t_log_mascara_query() {
  "${CURL[@]}" -o /dev/null "$U/invite/SEGREDO6?next=/invite/x&marca=q6"
  if grep 'marca=q6' "$ACCESS" | grep -q '/invite/\*\*\*' && [ "$(grep -c SEGREDO6 "$ACCESS")" -eq 0 ]; then
    ok t_log_mascara_query
  else fail t_log_mascara_query "linha ausente ou token no log"; fi
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
  local n; n=$(burst 150 $U/invite/SEGREDO429 | grep -c 429)
  [ "$n" -ge 1 ] && ok t_429_rsvp || fail t_429_rsvp "nenhum 429"
}
t_zonas_auth_geral() {
  # reesgota a zona auth (um slot pode ter reenchido desde t_429_login: 10r/m = 1 a cada 6s)
  # e entao toda rota auth deve dar 429 de imediato.
  local r c bad="" out i
  burst 40 $U/login -X POST >/dev/null
  # uma unica chamada de curl (conexao reaproveitada, sem fork entre as URLs): evita que
  # um slot de 10r/m reencha entre as checagens em ambiente lento (WSL/Docker)
  local routes=(/forgot_password /reset_password/x /signup /resend-verification /login)
  local urls=(); for r in "${routes[@]}"; do urls+=(-o /dev/null "$U$r"); done  # -o vale por URL
  out=$("${CURL[@]}" -w '%{http_code}\n' "${urls[@]}")
  i=0
  while read -r c; do
    [ "$c" = 429 ] || bad="$bad ${routes[$i]}=$c(esperado 429)"
    i=$((i + 1))
  done <<< "$out"
  [ "$i" -eq "${#routes[@]}" ] || bad="$bad contagem=$i(esperado ${#routes[@]})"
  sleep 1   # zona geral reencher (10r/s) das rajadas de static_folga
  # fora da zona auth (geral, sem exaurir): o stub responde 200
  for r in /verify-email/x /loginX /signup-foo; do
    c=$(codes $U$r); [ "$c" = 200 ] || bad="$bad $r=$c(esperado 200)"
  done
  [ -z "$bad" ] && ok t_zonas_auth_geral || fail t_zonas_auth_geral "$bad"
}
t_errorlog_429_sem_token() {
  # os bursts 429 usaram /invite/SEGREDO429 e /login (POST); error.log nao pode ter o token
  local n; n=$(grep -c SEGREDO429 "$T/log/error.log" 2>/dev/null || true)
  if [ "${n:-0}" -eq 0 ] && grep -q ' 429 ' "$ACCESS"; then ok t_errorlog_429_sem_token
  else fail t_errorlog_429_sem_token "$n linhas com token no error.log, ou nenhum 429 no access.log"; fi
}
t_429_login() {
  local n; n=$(burst 40 $U/login -X POST | grep -c 429)
  [ "$n" -ge 1 ] && ok t_429_login || fail t_429_login "nenhum 429"
}

# --- fase upstream indisponivel: 2o container SEM o stub (127.0.0.1:3000 recusa),
# entao o proprio nginx devolve 502 e grava no error.log. Logs em diretorio separado.
C2="nginx-test2-$$-$RANDOM"
T2="$T/log2"
cleanup2() { docker rm -f "$C2" >/dev/null 2>&1 || true; }
trap 'cleanup2; cleanup' EXIT
phase_upstream_down() {
  mkdir -p "$T2"; chmod 777 "$T2"
  local A2=(-v "$D/zapbyte.com.br.conf:/etc/nginx/conf.d/zz-site.conf:ro"
            -v "$D/test/prod-http.conf:/etc/nginx/conf.d/00-prod-http.conf:ro"
            -v "$LE:/etc/letsencrypt:ro"
            -v "$T2:/var/log/nginx")
  [ -f "$D/comemore.conf" ] && A2+=(-v "$D/comemore.conf:/etc/nginx/conf.d/comemore.conf:ro")
  [ -d "$D/snippets" ] && A2+=(-v "$D/snippets:/etc/nginx/snippets:ro")
  docker run -d --name "$C2" -p 127.0.0.1:18444:443 "${A2[@]}" \
    nginx:1.24-alpine sh -c "rm -f /etc/nginx/conf.d/default.conf; exec nginx -g 'daemon off;'" >/dev/null \
    || { fail phase_upstream_down "container 2 nao subiu"; return 1; }
  local i
  for i in $(seq 1 30); do
    curl -sk -o /dev/null --resolve zapbyte.com.br:18444:127.0.0.1 https://zapbyte.com.br:18444/ && break
    sleep 0.3
  done
  return 0
}
U2=https://zapbyte.com.br:18444
CURL2=(curl -sk --resolve zapbyte.com.br:18444:127.0.0.1)
ERR2="$T2/error.log"; ACC2="$T2/access.log"

t_errorlog_502_token_sem_token() {
  local c1 c2 c3 n bad=""
  c1=$("${CURL2[@]}" -o /dev/null -w '%{http_code}' $U2/invite/SEGREDO7)
  c2=$("${CURL2[@]}" -o /dev/null -w '%{http_code}' $U2/reset_password/SEGREDO8)
  c3=$("${CURL2[@]}" -o /dev/null -w '%{http_code}' $U2/verify-email/SEGREDO9)
  [ "$c1$c2$c3" = 502502502 ] || bad="$bad status=$c1/$c2/$c3"
  n=$(cat "$ERR2" 2>/dev/null | grep -cE 'SEGREDO(7|8|9)' || true)
  [ "${n:-0}" -eq 0 ] || bad="$bad $n linhas com token no error.log"
  grep -E ' 502 ' "$ACC2" | grep -q '/invite/\*\*\*' || bad="$bad access.log sem 502 invite mascarado"
  grep -E ' 502 ' "$ACC2" | grep -q '/reset_password/\*\*\*' || bad="$bad access.log sem 502 reset mascarado"
  grep -E ' 502 ' "$ACC2" | grep -q '/verify-email/\*\*\*' || bad="$bad access.log sem 502 verify mascarado"
  [ "$(grep -cE 'SEGREDO(7|8|9)' "$ACC2")" -eq 0 ] || bad="$bad token no access.log"
  [ -z "$bad" ] && ok t_errorlog_502_token_sem_token || fail t_errorlog_502_token_sem_token "$bad"
}
t_errorlog_502_login_registra() {
  local c; c=$("${CURL2[@]}" -o /dev/null -w '%{http_code}' $U2/login)
  if [ "$c" = 502 ] && grep -q 'request: "GET /login ' "$ERR2" 2>/dev/null; then ok t_errorlog_502_login_registra
  else fail t_errorlog_502_login_registra "status $c ou /login ausente do error.log"; fi
}
t_errorlog_413_token_sem_token() {
  local f="$T/56mb-b.bin" code n
  head -c $((56 * 1024 * 1024)) /dev/zero > "$f"
  code=$("${CURL2[@]}" -o /dev/null -w '%{http_code}' -X POST --data-binary @"$f" $U2/invite/SEGREDO10)
  rm -f "$f"
  n=$(cat "$ERR2" 2>/dev/null | grep -c SEGREDO10 || true)
  if [ "$code" = 413 ] && [ "${n:-0}" -eq 0 ]; then ok t_errorlog_413_token_sem_token
  else fail t_errorlog_413_token_sem_token "status $code, $n linhas com token no error.log"; fi
}

t_sintaxe
t_headers_login
t_headers_invite_404
t_sem_nosniff_duplicado
t_upload_51mb
t_upload_56mb
t_proxy_headers
t_log_mascara
t_log_referer
t_log_porta80
t_log_mascara_query
t_redirect_80
# rate limit por ultimo, nesta ordem (estado de zona compartilhado);
# espera a zona geral (10r/s, burst 40) reencher das requisicoes anteriores
sleep 5
t_static_folga
t_rsvp_folga
t_429_rsvp
t_429_login
t_zonas_auth_geral
t_errorlog_429_sem_token

# fase upstream indisponivel (container proprio, zonas de rate limit proprias)
if phase_upstream_down; then
  t_errorlog_502_token_sem_token
  t_errorlog_502_login_registra
  t_errorlog_413_token_sem_token
fi

exit $FAIL
