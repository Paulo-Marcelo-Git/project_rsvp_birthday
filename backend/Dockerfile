# backend/Dockerfile

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
 && rm -rf /var/lib/apt/lists/*

COPY . .

RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Deixa todos os args do gunicorn em uma única env (sem brigar com JSON)
ENV GUNICORN_CMD_ARGS="\
-w 2 \
--threads 4 \
-k gthread \
-b 0.0.0.0:8000 \
--timeout 120 \
--graceful-timeout 30 \
--keep-alive 5 \
--access-logfile - \
--access-logformat '%(t)s | %(p)s | %(m)s %(U)s | status=%(s)s | resp_time=%(L)s sec | size=%(B)s bytes'"

CMD ["gunicorn", "app:app"]
