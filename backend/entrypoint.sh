#!/bin/sh
# Entrypoint do container backend.
# Aguarda MySQL, aplica migrations Alembic e inicia gunicorn.
#
# IMPORTANTE (dev/staging): se você tinha schema legado pré-Alembic no volume
# Docker, faça `docker compose down -v` ANTES de `docker compose up`.
set -e

echo "[entrypoint] Aguardando MySQL..."
until python -c "
import os, pymysql
try:
    pymysql.connect(
        host=os.environ['DB_HOST'],
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        database=os.environ['DB_NAME'],
        connect_timeout=3,
    )
    print('MySQL pronto.')
except Exception as e:
    raise SystemExit(1)
" 2>/dev/null; do
    sleep 2
done

echo "[entrypoint] Aplicando migrations Alembic..."
alembic upgrade head

if [ "${DEBUGPY_ENABLED:-}" = "true" ]; then
    echo "############################################################"
    echo "# ATENCAO: DEBUGPY_ENABLED=true                             #"
    echo "# Rodando 'flask run' (single-thread, SEM gunicorn) com     #"
    echo "# debugpy na porta 5678. Isto NAO deve rodar em producao -  #"
    echo "# derruba a capacidade de throughput do backend.            #"
    echo "# Para reverter: apague DEBUGPY_ENABLED do .env e reinicie. #"
    echo "############################################################"
    exec env FLASK_APP=app python -X frozen_modules=off -m debugpy --listen 0.0.0.0:5678 -m flask run --host 0.0.0.0 --port 8000 --no-reload
fi

echo "[entrypoint] Iniciando gunicorn..."
exec gunicorn app:app "$@"
