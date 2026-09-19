# syntax=docker/dockerfile:1
#
# qBittorrent (qbittorrent-nox) on Alpine. Alpine packages the headless Qt6
# "nox" build in its community repository, so the binary and its Qt6 /
# libtorrent-rasterbar dependencies come straight from apk — no source build
# and no third-party image. python3 is present only so the entrypoint can
# derive the PBKDF2 WebUI password hash on first boot. Final image is Alpine.

FROM alpine:3.24

ARG QBT_VERSION=5.2.1

RUN set -eux; \
    apk add --no-cache \
        "qbittorrent-nox~=${QBT_VERSION}" \
        python3 \
        ca-certificates \
        tzdata \
        su-exec; \
    rm -rf /tmp/* /root/.cache

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8085
VOLUME ["/config", "/data"]

# GET / returns 200 without authentication, so a plain wget works as the
# health probe (the WebUI/API itself always requires the seeded login).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8085/ || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["qbittorrent-nox", "--profile=/config", "--webui-port=8085", "--torrenting-port=6881", "--confirm-legal-notice"]
