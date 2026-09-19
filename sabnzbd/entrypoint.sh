#!/bin/sh
set -eu

# Drop privileges to the requested PUID/PGID (defaults 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    addgroup -g "$PGID" -S sabnzbd 2>/dev/null || true
    adduser -u "$PUID" -S -G sabnzbd -h /config -s /sbin/nologin sabnzbd 2>/dev/null || true

    mkdir -p /config /data/incomplete /data/complete /data/backup

    # SABnzbd has no env-var or CLI override for its folders, so seed a minimal
    # config on first run. Incomplete and complete share the /data volume so
    # finished jobs can be moved atomically (rename) and hardlinked, and a
    # dedicated backup dir keeps config/database backups out of complete.
    # Existing configs are never overwritten.
    #
    # SABnzbd also refuses requests whose Host header is not localhost, an IP,
    # *.local, or listed in host_whitelist (anti-DNS-rebinding). Two access
    # paths must pass this check:
    #   * nginx-proxy forwards the public Host header -> SABNZBD_HOST
    #   * other containers use http://sabnzbd:8080  -> SABNZBD_HOST_WHITELIST
    #     (hardcoded in docker-compose.yml: "sabnzbd, sabnzbd.<BASE_DOMAIN>")
    # The API/NZB keys are seeded too (when provided) so downstream containers
    # share a stable credential instead of scraping the generated key.
    # See README.md.
    if [ ! -f /config/sabnzbd.ini ]; then
        # host_whitelist = <SABNZBD_HOST>, <SABNZBD_HOST_WHITELIST>, merged with
        # duplicates removed. The extras overlap with SABNZBD_HOST by design (the
        # public hostname appears in both) so the list stays de-duplicated.
        whitelist="${SABNZBD_HOST:-}"
        # shellcheck disable=SC2086 # intentional word splitting on the CSV
        for entry in $(printf '%s' "${SABNZBD_HOST_WHITELIST:-sabnzbd}" | tr ',' ' '); do
            # Match whole tokens only (entry followed by "," or end-of-list
            # i.e. a space here) so "sabnzbd" never masks "sabnzbd.<domain>".
            case " $whitelist " in
                *" $entry,"*|*" $entry "*) ;;
                *) whitelist="${whitelist:+$whitelist, }$entry" ;;
            esac
        done

        {
            echo '[misc]'
            echo 'download_dir = /data/incomplete'
            echo 'complete_dir = /data/complete'
            echo 'backup_dir = /data/backup'
            if [ -n "$whitelist" ]; then
                printf 'host_whitelist = %s\n' "$whitelist"
            fi
            if [ -n "${SABNZBD_API_KEY:-}" ]; then
                printf 'api_key = %s\n' "$SABNZBD_API_KEY"
            fi
            if [ -n "${SABNZBD_NZB_KEY:-}" ]; then
                printf 'nzb_key = %s\n' "$SABNZBD_NZB_KEY"
            fi
        } > /config/sabnzbd.ini
    fi

    # Config is small: safe to fix recursively. Data can be huge, so only
    # ensure the directory roots are owned correctly to avoid expensive
    # recursive chown (new files inherit ownership from the running user).
    chown -R "$PUID:$PGID" /config 2>/dev/null || true
    chown "$PUID:$PGID" /data /data/incomplete /data/complete /data/backup 2>/dev/null || true

    exec su-exec "$PUID:$PGID" "$@"
fi

exec "$@"
