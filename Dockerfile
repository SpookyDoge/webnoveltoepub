# syntax=docker/dockerfile:1
#
# Two targets:
#   runtime    - lightweight image (requests + BeautifulSoup), default; ~200 MB
#   playwright - + Chromium for JS-rendered sites ("heavy mode"); ~1.5 GB
#
# docker build --target runtime    -t webnoveltoepub .
# docker build --target playwright -t webnoveltoepub:playwright .

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

RUN useradd --create-home --uid 10001 appuser


# --------------------------------------------------------------------------
FROM base AS runtime

COPY app ./app
COPY web ./web

# Directory for EPUB copies (WNE_SAVE_TO_DISK). It has to belong to appuser,
# otherwise a non-root process cannot write anything without a bind mount.
RUN mkdir -p /app/output && chown appuser:appuser /app/output

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --------------------------------------------------------------------------
FROM base AS playwright

# Browsers outside /root so a non-root user can read them.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WNE_PLAYWRIGHT_ENABLED=true

COPY requirements-playwright.txt ./
RUN pip install --no-cache-dir -r requirements-playwright.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY app ./app
COPY web ./web

# Directory for EPUB copies (WNE_SAVE_TO_DISK). It has to belong to appuser,
# otherwise a non-root process cannot write anything without a bind mount.
RUN mkdir -p /app/output && chown appuser:appuser /app/output

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
