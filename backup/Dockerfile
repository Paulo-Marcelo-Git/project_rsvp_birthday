FROM alpine:3.19
RUN apk add --no-cache mysql-client gzip
COPY backup.sh /backup.sh
COPY restore.sh /restore.sh
RUN chmod +x /backup.sh /restore.sh
# Cron: 05:00 UTC = 02:00 BRT
CMD ["sh", "-c", \
     "echo '05 2 * * * /backup.sh >> /var/log/backup.log 2>&1' | crontab - && crond -f -l 8"]
