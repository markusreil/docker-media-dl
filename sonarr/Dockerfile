# syntax=docker/dockerfile:1
#
# Sonarr on Alpine. Sonarr ships self-contained .NET ("core") builds; the
# linux-musl-x64 tarball targets Alpine's musl libc and bundles the runtime,
# so no separate dotnet install is needed. The final image is pure Alpine.

FROM alpine:3.24

ARG SONARR_VERSION=4.0.20.3014
ARG BUILD_DATE=unknown

ENV SONARR_HOME=/config \
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
    wget -qO /tmp/sonarr.tar.gz \
        "https://github.com/Sonarr/Sonarr/releases/download/v${SONARR_VERSION}/Sonarr.main.${SONARR_VERSION}.linux-musl-x64.tar.gz"; \
    tar -xzf /tmp/sonarr.tar.gz -C /app --strip-components=1; \
    rm -rf /tmp/* /root/.cache

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8989
VOLUME ["/config"]

# /api/v3/system/status is the standard Sonarr health endpoint; it always
# requires the API key (served from the SONARR_API_KEY env var), so a 401
# counts as unhealthy too (non-zero exit handled by wget's --server-response).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null --header="X-Api-Key: $SONARR_API_KEY" \
        http://127.0.0.1:8989/api/v3/system/status || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/app/Sonarr", "-nobrowser", "-data=/config"]