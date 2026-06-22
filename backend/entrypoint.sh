#!/bin/sh
# Entrypoint do container backend.
# Aguarda MySQL, aplica migrations Alembic e inicia gunicorn.
#
# IMPORTANTE (dev/staging): se você ainda tem o schema antigo (init.sql) no
# volume Docker, faça `docker compose down -v` ANTES de `docker compose up`.
# Senão as tabelas antigas coexistem com as do Alembic e o boot pode falhar.
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

echo "[entrypoint] Iniciando gunicorn..."
exec gunicorn app:app "$@"
