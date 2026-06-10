FROM python:3.11-slim AS runtime

WORKDIR /app

ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ARG PLAYWRIGHT_DOWNLOAD_HOST=
ARG APT_MIRROR=http://deb.debian.org/debian
ARG APT_SECURITY_MIRROR=http://deb.debian.org/debian-security

ENV PIP_NO_CACHE_DIR=1 \
    PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_TRUSTED_HOST=${PIP_TRUSTED_HOST} \
    PLAYWRIGHT_DOWNLOAD_HOST=${PLAYWRIGHT_DOWNLOAD_HOST} \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WEBFETCH_V2_ROOT=/app/third_party/webfetch_v2

COPY third_party/webfetch_v2 ./third_party/webfetch_v2
COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
COPY backend/db ./db
COPY backend/packages ./packages

RUN python -m pip install --upgrade pip \
    && python -m pip install ".[trace]" \
    && python -m pip install "./third_party/webfetch_v2[extraction,browser]"

RUN sed -i \
        -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && python -m playwright install --with-deps chromium

ENV PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
