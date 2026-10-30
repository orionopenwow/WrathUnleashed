# wu-host-tools: the host agent, setup and self-check (one small image, built on the host's PC by
# "Host a Wrath realm" when the prebuilt one isn't published yet). Python 3.12 + PyMySQL (talks to the
# realm's MySQL 8.4, caching_sha2_password needs cryptography) + cryptography (fast Ed25519).
FROM python:3.12-alpine
RUN pip install --no-cache-dir "pymysql==1.1.1" "cryptography==43.0.3" \
 && adduser -D -H -u 10001 wu
COPY wunet /app/wunet
COPY wuhost /app/wuhost
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
CMD ["python", "-m", "wuhost.agent", "--state", "/state"]
