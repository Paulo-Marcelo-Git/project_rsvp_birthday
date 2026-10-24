FROM mysql:8.0
# Reseta entrypoint da imagem MySQL (que inicia o servidor)
ENTRYPOINT []
# cronie fornece crond no Oracle Linux 9 (base da imagem mysql:8.0)
RUN microdnf install -y cronie && microdnf clean all
COPY backup.sh /backup.sh
COPY restore.sh /restore.sh
COPY restore-uploads.sh /restore-uploads.sh
COPY purge-logs.sh /purge-logs.sh
COPY hc.sh /hc.sh
RUN chmod +x /backup.sh /restore.sh /restore-uploads.sh /purge-logs.sh /hc.sh
# Cron: 05:00 UTC = 02:00 BRT
# crond não herda as env vars do container (PID 1) — grava DB_NAME/DB_HOST/DB_USER/
# DB_PASSWORD/BACKUP_DIR/BACKUP_RETENTION_DAYS/LOG_DIR/LOG_RETENTION_DAYS como linhas
# VAR=valor no topo do crontab (suporte nativo do cron), senão os scripts falham com
# "unbound variable". purge-logs.sh (logs diários do app) roda 15 min após o backup.
CMD ["sh", "-c", \
     "{ echo \"DB_NAME=$DB_NAME\"; echo \"DB_HOST=$DB_HOST\"; echo \"DB_USER=$DB_USER\"; echo \"DB_PASSWORD=$DB_PASSWORD\"; echo \"BACKUP_DIR=$BACKUP_DIR\"; echo \"BACKUP_RETENTION_DAYS=$BACKUP_RETENTION_DAYS\"; echo \"LOG_DIR=$LOG_DIR\"; echo \"LOG_RETENTION_DAYS=$LOG_RETENTION_DAYS\"; echo '05 2 * * * /backup.sh >> /var/log/backup.log 2>&1'; echo '20 2 * * * /purge-logs.sh >> /var/log/purge-logs.log 2>&1'; } | crontab - && crond -n"]
