FROM mysql:8.0
# Reseta entrypoint da imagem MySQL (que inicia o servidor)
ENTRYPOINT []
# cronie fornece crond no Oracle Linux 9 (base da imagem mysql:8.0)
RUN microdnf install -y cronie && microdnf clean all
COPY backup.sh /backup.sh
COPY restore.sh /restore.sh
RUN chmod +x /backup.sh /restore.sh
# Cron: 05:00 UTC = 02:00 BRT
CMD ["sh", "-c", \
     "echo '05 2 * * * /backup.sh >> /var/log/backup.log 2>&1' | crontab - && crond -n"]
