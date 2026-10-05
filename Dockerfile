# syntax=docker/dockerfile:1

# ---- build stage: install dependencies into an isolated venv ----
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && find /opt/venv -type d -name __pycache__ -prune -exec rm -rf {} + \
    && rm -rf /opt/venv/lib/python*/site-packages/pip* /opt/venv/lib/python*/site-packages/setuptools*

# ---- runtime stage: only the venv + app code, no build tooling ----
FROM python:3.12-slim

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Jakarta \
    FLASK_APP=run \
    UPLOAD_FOLDER=/data/uploads \
    SVC_ROLE=all \
    PORT=3000

RUN useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /app /data/uploads \
    && chown app:app /app /data/uploads

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .
RUN chmod +x docker/entrypoint.sh

USER app
EXPOSE 3000
VOLUME ["/data/uploads"]

ENTRYPOINT ["/app/docker/entrypoint.sh"]
