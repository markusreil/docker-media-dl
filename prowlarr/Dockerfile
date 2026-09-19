# syntax=docker/dockerfile:1
#
# Prowlarr on Alpine. Prowlarr ships self-contained .NET ("core") builds; the
# linux-musl-core tarball targets Alpine's musl libc and bundles the runtime,
# so no separate dotnet install is needed. The final image is pure Alpine.

FROM alpine:3.24

ARG PROWLARR_VERSION=2.6.5.5623

ENV PROWLARR_HOME=/config

RUN set -eux; \
    apk add --no-cache \
        ca-certificates \
        tzdata \
        su-exec \
        icu-libs \
        sqlite-libs \
        libstdc++; \
    mkdir -p /app /config; \
    wget -qO /tmp/prowlarr.tar.gz \
        "https://github.com/Prowlarr/Prowlarr/releases/download/v${PROWLARR_VERSION}/Prowlarr.master.${PROWLARR_VERSION}.linux-musl-core-x64.tar.gz"; \
    tar -xzf /tmp/prowlarr.tar.gz -C /app --strip-components=1; \
    rm -rf /tmp/* /root/.cache

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 9696
VOLUME ["/config"]

# /api/v1/system/status is the standard Servarr health endpoint; it always
# requires the API key (served from the PROWLARR_API_KEY env var), so a 401
# counts as unhealthy too (non-zero exit handled by wget's --server-response).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null --header="X-Api-Key: $PROWLARR_API_KEY" \
        http://127.0.0.1:9696/api/v1/system/status || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["/app/Prowlarr", "-nobrowser", "-data=/config"]