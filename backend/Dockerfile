# backend/Dockerfile

FROM python:3.12-slim

WORKDIR /app

COPY . .

RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt \
 && chmod +x entrypoint.sh

# Args do gunicorn (workers, threads, bind, timeouts, access log com tokens
# mascarados) ficam em gunicorn.conf.py, carregado pelo entrypoint.sh.
# Não use a env de args do gunicorn aqui: ela sobrescreveria o arquivo.

CMD ["./entrypoint.sh"]
