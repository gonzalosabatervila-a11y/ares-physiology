FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
COPY migrations ./migrations
RUN pip install --no-cache-dir . \
    && useradd -r -m -s /usr/sbin/nologin ares \
    && mkdir -p /data /run/secrets/ares \
    && chown -R ares:ares /data /run/secrets/ares

USER ares
ENV ARES_DATA_DIR=/data \
    ARES_MIGRATIONS_DIR=/app/migrations \
    ARES_SECRETS_DIR=/run/secrets/ares \
    ARES_SECRET_STATE_DIR=/data/secrets \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
EXPOSE 8443
CMD ["ares","serve"]
