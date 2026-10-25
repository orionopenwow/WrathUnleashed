# wu-relay. Build from the hosting/ folder:  docker build -f relay/Dockerfile -t wu-relay:1 .
FROM python:3.12-alpine
RUN pip install --no-cache-dir "cryptography==43.0.3" && adduser -D -H -u 10002 relay \
 && mkdir -p /var/lib/wu-relay && chown relay /var/lib/wu-relay
COPY kit/tools/wunet /app/wunet
COPY relay/wurelay /app/wurelay
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RELAY_STATE=/var/lib/wu-relay/state.json
USER relay
WORKDIR /app
CMD ["python", "-m", "wurelay.relay"]
