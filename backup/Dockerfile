FROM mysql:8.0
# Reseta entrypoint da imagem MySQL (que inicia o servidor)
ENTRYPOINT []
# cronie fornece crond no Oracle Linux 9 (base da imagem mysql:8.0); unzip para o rclone
RUN microdnf install -y cronie unzip && microdnf clean all
# rclone fixo com checksum (SHA256SUMS oficial do release v1.75.1): o build falha se divergir
RUN curl -fsSL -o rclone.zip https://github.com/rclone/rclone/releases/download/v1.75.1/rclone-v1.75.1-linux-amd64.zip \
 && echo "982b5aa772841168f8e380f139e9e787b2a105403e32b94da8676a0e1c0a13ab  rclone.zip" | sha256sum -c - \
 && unzip -j rclone.zip '*/rclone' -d /usr/local/bin \
 && chmod 755 /usr/local/bin/rclone \
 && rm -f rclone.zip
COPY backup.sh /backup.sh
COPY restore.sh /restore.sh
COPY restore-uploads.sh /restore-uploads.sh
COPY purge-logs.sh /purge-logs.sh
COPY hc.sh /hc.sh
COPY offsite.sh /offsite.sh
COPY rclone-env.sh /rclone-env.sh
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /backup.sh /restore.sh /restore-uploads.sh /purge-logs.sh /hc.sh /offsite.sh /rclone-env.sh /entrypoint.sh
# Cron (em UTC): backup 05:05 UTC = 02:05 BRT; purge-logs 15 min depois.
# crond não herda as env vars do container: o entrypoint grava /etc/backup.env (0600) e os
# jobs fazem `. /etc/backup.env`. Segredos nunca vão para o crontab.
CMD ["/entrypoint.sh"]
