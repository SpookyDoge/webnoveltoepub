# syntax=docker/dockerfile:1
#
# Dwa targety:
#   runtime    - lekki obraz (requests + BeautifulSoup), domyslny; ~200 MB
#   playwright - + Chromium do stron renderowanych JS-em ("ciezki tryb"); ~1.5 GB
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

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]


# --------------------------------------------------------------------------
FROM base AS playwright

# Przegladarki poza /root, zeby byly czytelne dla nie-roota.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    WNE_PLAYWRIGHT_ENABLED=true

COPY requirements-playwright.txt ./
RUN pip install --no-cache-dir -r requirements-playwright.txt \
    && playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY app ./app
COPY web ./web

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
