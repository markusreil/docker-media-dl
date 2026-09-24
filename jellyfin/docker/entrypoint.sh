#!/bin/sh
set -eu

# Drop privileges to the requested PUID/PGID (defaults 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    # Debian-adapted user setup: create the jellyfin group/user if missing,
    # otherwise adjust the existing IDs into place.
    if getent group jellyfin >/dev/null 2>&1; then
        groupmod -g "$PGID" jellyfin 2>/dev/null || true
    else
        groupadd -g "$PGID" jellyfin 2>/dev/null || true
    fi
    if id jellyfin >/dev/null 2>&1; then
        usermod -u "$PUID" -g "$PGID" -d /config -s /usr/sbin/nologin jellyfin 2>/dev/null || true
    else
        useradd -u "$PUID" -g "$PGID" -d /config -s /usr/sbin/nologin -M jellyfin 2>/dev/null || true
    fi

    # Map host GPU group GIDs (set by the optional docker-compose.hwaccel.yml
    # overlay) into the container and add the unprivileged user to them, so it
    # can open group-restricted DRM nodes (e.g. /dev/dri/card0 is root:video
    # 660). Docker's group_add cannot be used: gosu resets supplementary groups
    # on the privilege drop, so the mapping must exist in /etc/group first.
    # Unset vars = no-op (base stack without the overlay).
    add_host_group() {
        _gid="$1"; _base="$2"
        [ -n "$_gid" ] || return 0
        _grp="$(getent group "$_gid" | cut -d: -f1)"
        if [ -z "$_grp" ]; then
            _grp="$_base"; _i=0
            while getent group "$_grp" >/dev/null 2>&1; do
                _i=$((_i + 1)); _grp="${_base}${_i}"
            done
            groupadd -g "$_gid" "$_grp" 2>/dev/null || true
        fi
        id -nG jellyfin 2>/dev/null | tr ' ' '\n' | grep -qxF "$_grp" \
            || usermod -aG "$_grp" jellyfin 2>/dev/null || true
    }
    add_host_group "${JELLYFIN_VIDEO_GID:-}" gpu-video
    add_host_group "${JELLYFIN_RENDER_GID:-}" gpu-render

    mkdir -p /config/config /config/log /cache /media

    # No config seeding: Jellyfin ships a stock first-run wizard that runs in
    # the web UI (admin account, libraries, metadata language). Seeding config
    # files here would fight the wizard, so the entrypoint only ensures the
    # directories exist and fixes ownership. Existing configs are never
    # overwritten; a fresh start requires removing the service and its
    # volumes (see README.md).

    # Config and cache are small: safe to fix recursively. /media is an NFS
    # mount (potentially huge) — only fix the mountpoint root, never recurse.
    chown -R "$PUID:$PGID" /config /cache 2>/dev/null || true
    chown "$PUID:$PGID" /media 2>/dev/null || true

    # Seed JELLYFIN_API_KEY into jellyfin.db (ApiKeys table) when the server
    # has already initialized its schema. On the VERY FIRST start jellyfin.db
    # does not exist yet (the server creates it via EF migrations) — never
    # fabricate the DB; skip and converge on the next start. Never touches
    # *-wal/*-shm files; only writes pre-exec while the server is stopped.
    # INSERT OR IGNORE keeps this idempotent across restarts.
    if [ -n "${JELLYFIN_API_KEY:-}" ]; then
        _db="/config/data/jellyfin.db"
        if [ -f "$_db" ] && gosu "$PUID:$PGID" sqlite3 "$_db" ".tables" 2>/dev/null | grep -qw ApiKeys; then
            _now="$(date -u '+%Y-%m-%d %H:%M:%S.0000000')"
            gosu "$PUID:$PGID" sqlite3 "$_db" "INSERT OR IGNORE INTO ApiKeys (DateCreated, DateLastActivity, Name, AccessToken) VALUES ('$_now', '0001-01-01 00:00:00.0000000', 'media-dl', '$JELLYFIN_API_KEY');"
            echo "jellyfin: API key seeded into ApiKeys (name media-dl)"
        else
            echo "jellyfin: skipping API key seed (database uninitialized — converges on next start)"
        fi
    else
        echo "jellyfin: skipping API key seed (JELLYFIN_API_KEY unset)"
    fi

    # Extra CMD/compose args pass through as "$@". Exec by username (not
    # "$PUID:$PGID") so the supplementary groups mapped into /etc/group above
    # are applied on the privilege drop.
    exec gosu jellyfin /jellyfin/jellyfin --datadir /config --configdir /config/config --logdir /config/log --cachedir /cache "$@"
fi

exec /jellyfin/jellyfin --datadir /config --configdir /config/config --logdir /config/log --cachedir /cache "$@"
