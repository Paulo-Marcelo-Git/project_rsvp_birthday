#!/usr/bin/env bash
# Roda a suíte de testes (unit; integration fica de fora pelo pytest.ini).
# Ponto de entrada único para o Claude Code: liberado em .claude/settings.local.json,
# então não pede aprovação. Não rode pytest com comando composto — use este script.
# Uso:
#   bash scripts/test.sh [args do pytest]                    -> no próprio projeto
#   bash scripts/test.sh --scratch <dir> [args do pytest]    -> numa cópia scratch (<dir>/repo e <dir>/uploads)
# Python do host quando ele tem todas as deps; senão cai para a imagem Docker do backend
# (o host não tem flask_limiter e o ambiente não tem rede para instalar).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = "--scratch" ]; then
  BASE="${2:?informe o diretório da cópia scratch}"
  shift 2
  [ -d "$BASE/repo" ] || { echo "Não encontrei $BASE/repo" >&2; exit 1; }
  ROOT="$BASE/repo"
  UPLOADS="$BASE/uploads"
else
  UPLOADS="${TMPDIR:-/tmp}/rsvp_test_uploads"
fi
mkdir -p "$UPLOADS"
cd "$ROOT"

if python3 -c "import flask_limiter, pytest" 2>/dev/null; then
  UPLOAD_FOLDER="$UPLOADS" timeout 600 python3 -m pytest -q -p no:cacheprovider "$@" 2>&1 | tail -n 40
else
  echo "[test.sh] python3 do host sem deps; usando a imagem project_rsvp_birthday-backend" >&2
  timeout 600 docker run --rm \
    -v "$ROOT/backend:/app" \
    -v "$ROOT/VERSION:/VERSION:ro" \
    -v "$UPLOADS:/uploads_test" \
    -v "$HOME/.local/lib/python3.12/site-packages:/extra-packages:ro" \
    -e PYTHONPATH=/extra-packages -e UPLOAD_FOLDER=/uploads_test \
    -e DB_USER=test -e DB_PASSWORD=test -e DB_HOST=localhost -e DB_NAME=test_db -e SECRET_KEY=test-secret \
    -w /app \
    project_rsvp_birthday-backend:latest \
    python -m pytest -q -p no:cacheprovider -m "not integration" "$@" 2>&1 | tail -n 40
fi
