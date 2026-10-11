# syntax=docker/dockerfile:1
#
# Two targets share one dependency layer:
#   prod  - runtime dependencies only, application code only (no tests, no dev tooling). Used by docker-compose.prod.yml.
#   dev   - adds pytest/ruff and the tests so the suite can run inside the container. Used by docker-compose.yml.

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install -r requirements.txt

# Run as an unprivileged user.
# /app/var/mail is where development email is written (production uses SMTP).
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/var/mail \
    && chown -R appuser:appuser /app/var


FROM base AS prod
COPY --chown=appuser:appuser manage.py ./
COPY --chown=appuser:appuser config ./config
COPY --chown=appuser:appuser core ./core
COPY --chown=appuser:appuser apps ./apps
USER appuser
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]


FROM base AS dev
COPY requirements-dev.txt ./
RUN pip install -r requirements-dev.txt
COPY --chown=appuser:appuser . .
USER appuser
EXPOSE 8000
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
