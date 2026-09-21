# syntax=docker/dockerfile:1
#
# SABnzbd on Alpine. Alpine does not package SABnzbd (and cannot ship the
# non-free unrar), so the app is installed from the official source tarball
# into a venv, and unrar is copied from the official LinuxServer build stage.
# The final image is pure Alpine.

FROM ghcr.io/linuxserver/unrar:latest AS unrar

FROM alpine:3.24

ARG SABNZBD_VERSION=5.1.3
ARG BUILD_DATE=unknown

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH" \
    SABNZBD_HOME=/config \
    BASE_IMAGE=alpine:3.24 \
    BUILD_DATE=${BUILD_DATE}

RUN set -eux; \
    apk add --no-cache \
        python3 \
        py3-pip \
        ca-certificates \
        tzdata \
        7zip \
        p7zip \
        su-exec; \
    apk add --no-cache --virtual .build-deps \
        build-base \
        python3-dev \
        libffi-dev \
        openssl-dev \
        pkgconf \
        cargo \
        rust; \
    mkdir -p /app /config /downloads; \
    wget -qO /tmp/sabnzbd.tar.gz \
        "https://github.com/sabnzbd/sabnzbd/releases/download/${SABNZBD_VERSION}/SABnzbd-${SABNZBD_VERSION}-src.tar.gz"; \
    tar -xzf /tmp/sabnzbd.tar.gz -C /app --strip-components=1; \
    python3 -m venv /opt/venv; \
    /opt/venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel; \
    /opt/venv/bin/pip install --no-cache-dir -r /app/requirements.txt; \
    cd /app && /opt/venv/bin/python tools/make_mo.py; \
    apk del --no-network .build-deps; \
    rm -rf /tmp/* /root/.cache

# par2cmdline-turbo (the faster ParPar-based par2 fork) is not in the Alpine
# 3.24 stable repos; it only ships in edge/testing. Pass the repo inline so edge
# is not persisted in the image, and pin the version for reproducibility. Only
# the turbo package comes from edge; its deps resolve from stable. This layer is
# kept after the big build layer so it does not invalidate that cache.
ARG PAR2_TURBO_VERSION=1.5.0-r0
RUN apk add --no-cache \
        --repository=https://dl-cdn.alpinelinux.org/alpine/edge/testing \
        "par2cmdline-turbo=${PAR2_TURBO_VERSION}"

COPY --from=unrar /usr/bin/unrar-alpine /usr/bin/unrar

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh && { rmdir /downloads 2>/dev/null || true; }

EXPOSE 8080
VOLUME ["/config", "/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/opt/venv/bin/python", "/app/SABnzbd.py", \
     "--config-file", "/config/sabnzbd.ini", \
     "--server", "0.0.0.0:8080", \
     "--browser", "0", \
     "--disable-file-log"]
