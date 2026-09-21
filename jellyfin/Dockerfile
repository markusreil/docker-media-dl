# syntax=docker/dockerfile:1
#
# Jellyfin — EXCEPTION to the Alpine-only rule.
#
# Alpine's community apk is stuck at 10.10.x while upstream Jellyfin is at
# 12.x, so this service builds as a thin layer on the official
# jellyfin/jellyfin image (Debian bookworm-slim) instead of Alpine. This is
# the single documented exception; every other service in this repo stays on
# Alpine. The version is pinned via JELLYFIN_VERSION — never use :latest.
#
# To bump: update JELLYFIN_VERSION in .env to the new upstream tag, rebuild.

ARG JELLYFIN_VERSION=12.1
FROM jellyfin/jellyfin:${JELLYFIN_VERSION}

ENV BASE_IMAGE=jellyfin/jellyfin

ARG BUILD_DATE=unknown
ENV BUILD_DATE=${BUILD_DATE}

# Debian has no su-exec; gosu is the equivalent privilege-drop tool.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends gosu wget sqlite3; \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8096
VOLUME ["/config", "/cache"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8096/health || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
