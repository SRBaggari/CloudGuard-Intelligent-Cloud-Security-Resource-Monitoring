# CloudGuard backend (FastAPI)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app

# Run as an unprivileged user. Docker monitoring needs access to the mounted socket:
# pass DOCKER_GID (the host's docker group id) at build time, see docker-compose.yml.
ARG DOCKER_GID=999
RUN (groupadd -g ${DOCKER_GID} dockerhost || true) \
 && useradd -m -u 10001 cloudguard \
 && (usermod -aG ${DOCKER_GID} cloudguard || true) \
 && mkdir -p /app/data && chown -R cloudguard /app/data
USER cloudguard

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
