#!/bin/sh
set -eu

# Drop privileges to the requested PUID/PGID (defaults 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    addgroup -g "$PGID" -S qbittorrent 2>/dev/null || true
    adduser -u "$PUID" -S -G qbittorrent -h /config -s /sbin/nologin qbittorrent 2>/dev/null || true

    mkdir -p /config/qBittorrent/config /data/incomplete /data/complete

    # qBittorrent has no env-var/CLI override for its WebUI credentials
    # (password has to exist in the config as a PBKDF2 hash), so the
    # entrypoint seeds a minimal config on first start only. Existing configs
    # are never overwritten; reseeding requires removing the service and its
    # config volume, then recreating (see README.md).
    #
#     Login is always required by default: unlike SABnzbd/Prowlarr there is
    #     no anonymous/LAN-only mode in qBittorrent, so QBT_WEBUI_USERNAME and
    #     QBT_WEBUI_PASSWORD are seeded and the stack uses them to reach the
    #     WebUI and API behind nginx-proxy.
    #
    #     Optional: QBT_AUTH_SUBNET_WHITELIST (CIDR list) skips login for
    #     clients from those subnets — set it to the docker network nginx-proxy
    #     attaches to (e.g. 172.18.0.0/16) to open the WebUI without a login
    #     behind the proxy. Empty = login always required.
    #
    # Host-header handling (anti-DNS-rebinding) mirrors SABnzbd's
    # host_whitelist approach: WebUI\HostHeaderValidation stays on and
    # WebUI\ServerDomains is seeded with the public hostname (QBT_HOST) plus
    # the service name (QBT_HOST_WHITELIST, hardcoded in docker-compose.yml as
    # "qbittorrent;qbittorrent.<BASE_DOMAIN>" so other containers can use
    # http://qbittorrent:8085).
    #
    # The PBKDF2 format was verified empirically against qbittorrent-nox
    # 5.2.1's own output: PBKDF2-HMAC-SHA512, 16-byte random salt, 100000
    # iterations, 64-byte key, stored as
    #   WebUI\Password_PBKDF2="@ByteArray(<b64 salt>:<b64 key>)"
    # (QSettings serializes the QByteArray with a @ByteArray(...) wrapper).
    if [ ! -f /config/qBittorrent/config/qBittorrent.conf ]; then
        username="${QBT_WEBUI_USERNAME:-admin}"
        password="${QBT_WEBUI_PASSWORD:-}"

        if [ -z "$password" ]; then
            echo "ERROR: QBT_WEBUI_PASSWORD is required (see .env)" >&2
            exit 1
        fi

        pbkdf2_hash="$(python3 - "$password" <<'PYEOF'
import base64
import hashlib
import os
import sys

password = sys.argv[1].encode()
salt = os.urandom(16)
dk = hashlib.pbkdf2_hmac("sha512", password, salt, 100000, dklen=64)
print("{}:{}".format(base64.b64encode(salt).decode(), base64.b64encode(dk).decode()))
PYEOF
)"

        # ServerDomains = <QBT_HOST>;<QBT_HOST_WHITELIST>, merged with
        # duplicates removed. The extras overlap with QBT_HOST by design (the
        # public hostname appears in both) so the list stays de-duplicated.
        domains="${QBT_HOST:-}"
        # shellcheck disable=SC2086 # intentional word splitting on the list
        for entry in $(printf '%s' "${QBT_HOST_WHITELIST:-qbittorrent}" | tr ';' ' '); do
            # Match whole tokens only (wrapped in the ";" separator) so
            # "qbittorrent" never masks a longer name.
            case ";$domains;" in
                *";$entry;"*) ;;
                *) domains="${domains:+$domains;}$entry" ;;
            esac
        done

        auth_subnets="${QBT_AUTH_SUBNET_WHITELIST:-}"

        {
            echo '[BitTorrent]'
            printf '%s\n' 'Session\DefaultSavePath=/data/complete'
            printf '%s\n' 'Session\TempPath=/data/incomplete'
            printf '%s\n' 'Session\TempPathEnabled=true'
            printf '%s\n' 'Session\Port=6881'
            echo
            echo '[LegalNotice]'
            printf '%s\n' 'Accepted=true'
            echo
            echo '[Preferences]'
            printf '%s\n' 'WebUI\Address=*'
            printf '%s\n' 'WebUI\HostHeaderValidation=true'
            printf '%s\n' 'WebUI\Port=8085'
            if [ -n "$domains" ]; then
                printf '%s\n' "WebUI\\ServerDomains=\"$domains\""
            fi
            if [ -n "$auth_subnets" ]; then
                printf '%s\n' 'WebUI\AuthSubnetWhitelistEnabled=true'
                printf '%s\n' "WebUI\\AuthSubnetWhitelist=$auth_subnets"
            fi
            printf '%s\n' "WebUI\\Username=$username"
            printf '%s\n' "WebUI\\Password_PBKDF2=\"@ByteArray($pbkdf2_hash)\""
        } > /config/qBittorrent/config/qBittorrent.conf
    fi

    # Config is small: safe to fix recursively. Data can be huge, so only
    # ensure the directory roots are owned correctly to avoid expensive
    # recursive chown (new files inherit ownership from the running user).
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    chown "$PUID:$PGID" /data /data/incomplete /data/complete 2>/dev/null || true

    exec su-exec "$PUID:$PGID" "$@"
fi

exec "$@"
