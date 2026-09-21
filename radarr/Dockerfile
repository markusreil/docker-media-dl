# syntax=docker/dockerfile:1
#
# Radarr on Alpine. Radarr ships self-contained .NET ("core") builds; the
# linux-musl-core tarball targets Alpine's musl libc and bundles the runtime,
# so no separate dotnet install is needed. The final image is pure Alpine.

FROM alpine:3.24

ARG RADARR_VERSION=6.4.4.10685
ARG BUILD_DATE=unknown

ENV RADARR_HOME=/config \
    BASE_IMAGE=alpine:3.24 \
    BUILD_DATE=${BUILD_DATE}

RUN set -eux; \
    apk add --no-cache \
        ca-certificates \
        tzdata \
        su-exec \
        icu-libs \
        sqlite-libs \
        libstdc++ \
        jq \
        wget; \
    mkdir -p /app /config; \
    wget -qO /tmp/radarr.tar.gz \
        "https://github.com/Radarr/Radarr/releases/download/v${RADARR_VERSION}/Radarr.master.${RADARR_VERSION}.linux-musl-core-x64.tar.gz"; \
    tar -xzf /tmp/radarr.tar.gz -C /app --strip-components=1; \
    rm -rf /tmp/* /root/.cache

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 7878
VOLUME ["/config"]

# /api/v3/system/status is the standard Radarr health endpoint; it always
# requires the API key (served from the RADARR_API_KEY env var), so a 401
# counts as unhealthy too (non-zero exit handled by wget's --server-response).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
        http://127.0.0.1:7878/api/v3/system/status || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/app/Radarr", "-nobrowser", "-data=/config"]
