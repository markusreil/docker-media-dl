#!/bin/sh
set -eu

# Drop privileges to the requested PUID/PGID (defaults 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

# Idempotent upsert of the Sabnzbd download client via the Radarr v3 API.
# Runs as the unprivileged user after the server is reachable. Uses the
# /downloadclient/schema template (implementation == "Sabnzbd") and
# ?forceSave=true so validation never blocks the seed.
seed_sabnzbd_client() {
    base="http://127.0.0.1:7878/api/v3/downloadclient"
    # Wait for the API (up to ~120s).
    i=0
    while [ "$i" -lt 60 ]; do
        if wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
            http://127.0.0.1:7878/api/v3/system/status 2>/dev/null; then
            break
        fi
        i=$((i + 1))
        sleep 2
    done

    clients=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base" 2>/dev/null || true)
    [ -n "$clients" ] || return 0
    id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="Sabnzbd") | .id // empty' | head -n 1)

    schema=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base/schema" 2>/dev/null || true)
    [ -n "$schema" ] || return 0
    # movieCategory must be left blank: this Radarr pin cannot match ANY
    # SABnzbd category by name. Its SabnzbdCategory deserializer maps JSON
    # keys to C# properties verbatim (PascalCase: "Name"/"Dir"), but SABnzbd
    # sends lowercase ("name"/"dir"), so every category comes back with a null
    # Name and a non-blank movieCategory always fails validation with
    # "Category does not exist" (verified against 6.4.4.10685). A blank value
    # rides SABnzbd's catch-all "*" and completes at the complete_dir root —
    # the layout SABnzbd seeds (movies dir=""). Follow the pinned-version
    # behavior rather than the docs; revisit when bumping the Radarr pin.
    body=$(printf '%s' "$schema" | jq \
        --arg apiKey "${SABNZBD_API_KEY:-}" \
        '.[] | select(.implementation=="Sabnzbd") | .enable=true
        | .protocol="usenet" | .priority=1
        | .removeCompletedDownloads=true | .removeFailedDownloads=true
        | .implementation="Sabnzbd" | .implementationName="Sabnzbd"
        | .configContract="SabnzbdSettings" | .tags=[]
        | .fields=(.fields
            | map(if .name=="host" then .value="sabnzbd"
                elif .name=="port" then .value=8080
                elif .name=="useSsl" then .value=false
                elif .name=="apiKey" then .value=$apiKey
                elif .name=="username" then .value=""
                elif .name=="password" then .value=""
                elif .name=="movieCategory" then .value=""
                else . end))')
    [ -n "$body" ] && [ "$body" != "null" ] || return 0

    attempt=1
    while [ "$attempt" -le 10 ]; do
        cur_id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="Sabnzbd") | .id // empty' 2>/dev/null | head -n 1 || true)
        if [ -n "$cur_id" ] && [ "$attempt" -gt 1 ]; then
            echo "seed: Sabnzbd download client present (id $cur_id)"
            return 0
        fi
        if [ -n "$cur_id" ]; then
            req_body=$(printf '%s' "$body" | jq --argjson id "$cur_id" '. + {id: $id, name: "Sabnzbd"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
                --header="Content-Type: application/json" \
                --method=PUT --body-data="$req_body" "$base/$cur_id?forceSave=true" 2>/dev/null || true
        else
            req_body=$(printf '%s' "$body" | jq '. + {name: "Sabnzbd"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
                --header="Content-Type: application/json" \
                --post-data="$req_body" "$base?forceSave=true" 2>/dev/null || true
        fi
        clients=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base" 2>/dev/null || true)
        verify_id=""
        if [ -n "$clients" ]; then
            verify_id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="Sabnzbd") | .id // empty' 2>/dev/null | head -n 1 || true)
        fi
        if [ -n "$verify_id" ]; then
            echo "seed: Sabnzbd download client present (id $verify_id)"
            return 0
        fi
        echo "seed: Sabnzbd upsert attempt $attempt failed, retrying"
        attempt=$((attempt + 1))
        [ "$attempt" -le 10 ] && sleep 10 || true
    done
    return 0
}

# Idempotent upsert of the qBittorrent download client via the Radarr v3 API.
# Mirrors seed_sabnzbd_client: /downloadclient/schema template
# (implementation == "QBittorrent") with ?forceSave=true.
seed_qbittorrent_client() {
    base="http://127.0.0.1:7878/api/v3/downloadclient"
    # Wait for the API (up to ~120s).
    i=0
    while [ "$i" -lt 60 ]; do
        if wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
            http://127.0.0.1:7878/api/v3/system/status 2>/dev/null; then
            break
        fi
        i=$((i + 1))
        sleep 2
    done

    clients=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base" 2>/dev/null || true)
    [ -n "$clients" ] || return 0
    id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="QBittorrent") | .id // empty' | head -n 1)

    schema=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base/schema" 2>/dev/null || true)
    [ -n "$schema" ] || return 0
    body=$(printf '%s' "$schema" | jq \
        --arg username "${QBT_WEBUI_USERNAME:-admin}" \
        --arg password "${QBT_WEBUI_PASSWORD:-}" \
        '.[] | select(.implementation=="QBittorrent") | .enable=true
        | .protocol="torrent" | .priority=2
        | .removeCompletedDownloads=true | .removeFailedDownloads=true
        | .implementation="QBittorrent" | .implementationName="QBittorrent"
        | .configContract="QBittorrentSettings" | .tags=[]
        | .fields=(.fields
            | map(if .name=="host" then .value="qbittorrent"
                elif .name=="port" then .value=8085
                elif .name=="useSsl" then .value=false
                elif .name=="username" then .value=$username
                elif .name=="password" then .value=$password
                elif .name=="movieCategory" then .value="movies"
                else . end))')
    [ -n "$body" ] && [ "$body" != "null" ] || return 0

    attempt=1
    while [ "$attempt" -le 10 ]; do
        cur_id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="QBittorrent") | .id // empty' 2>/dev/null | head -n 1 || true)
        if [ -n "$cur_id" ] && [ "$attempt" -gt 1 ]; then
            echo "seed: QBittorrent download client present (id $cur_id)"
            return 0
        fi
        if [ -n "$cur_id" ]; then
            req_body=$(printf '%s' "$body" | jq --argjson id "$cur_id" '. + {id: $id, name: "QBittorrent"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
                --header="Content-Type: application/json" \
                --method=PUT --body-data="$req_body" "$base/$cur_id?forceSave=true" 2>/dev/null || true
        else
            req_body=$(printf '%s' "$body" | jq '. + {name: "QBittorrent"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $RADARR_API_KEY" \
                --header="Content-Type: application/json" \
                --post-data="$req_body" "$base?forceSave=true" 2>/dev/null || true
        fi
        clients=$(wget -q -O - --header="X-Api-Key: $RADARR_API_KEY" "$base" 2>/dev/null || true)
        verify_id=""
        if [ -n "$clients" ]; then
            verify_id=$(printf '%s' "$clients" | jq -r '.[] | select(.name=="QBittorrent") | .id // empty' 2>/dev/null | head -n 1 || true)
        fi
        if [ -n "$verify_id" ]; then
            echo "seed: QBittorrent download client present (id $verify_id)"
            return 0
        fi
        echo "seed: QBittorrent upsert attempt $attempt failed, retrying"
        attempt=$((attempt + 1))
        [ "$attempt" -le 10 ] && sleep 10 || true
    done
    return 0
}

# Idempotent upsert of Radarr as an Application inside Prowlarr.
# Servarr topology: Radarr has no native Prowlarr indexer implementation;
# Prowlarr pushes trackers into Radarr as Newznab/Torznab entries.
# Built from the GET /api/v1/applications/schema template
# (implementation == "Radarr"), matched by name for the existing id,
# POST (create) or PUT /{id} (update). Best-effort sync trigger after.
seed_prowlarr_app() {
    base="http://prowlarr:9696/api/v1/applications"
    # Wait for Prowlarr (up to ~120s).
    i=0
    while [ "$i" -lt 60 ]; do
        if wget -q -O /dev/null --header="X-Api-Key: $PROWLARR_API_KEY" \
            http://prowlarr:9696/api/v1/system/status 2>/dev/null; then
            break
        fi
        i=$((i + 1))
        sleep 2
    done

    apps=$(wget -q -O - --header="X-Api-Key: $PROWLARR_API_KEY" "$base" 2>/dev/null || true)
    [ -n "$apps" ] || return 0
    id=$(printf '%s' "$apps" | jq -r '.[] | select(.name=="Radarr") | .id // empty' | head -n 1)

    schema=$(wget -q -O - --header="X-Api-Key: $PROWLARR_API_KEY" "$base/schema" 2>/dev/null || true)
    [ -n "$schema" ] || return 0
    body=$(printf '%s' "$schema" | jq \
        --arg apiKey "$RADARR_API_KEY" \
        '.[] | select(.implementation=="Radarr") | .enable=true
        | .syncLevel="fullSync" | .tags=[]
        | .fields=(.fields
            | map(if .name=="prowlarrUrl" then .value="http://prowlarr:9696"
                elif .name=="baseUrl" then .value="http://radarr:7878"
                elif .name=="apiKey" then .value=$apiKey
                elif .name=="syncCategories" then .value=[2000,2010,2020,2030,2040,2045,2050,2060,2070,2080]
                else . end))')
    [ -n "$body" ] && [ "$body" != "null" ] || return 0

    attempt=1
    while [ "$attempt" -le 10 ]; do
        cur_id=$(printf '%s' "$apps" | jq -r '.[] | select(.name=="Radarr") | .id // empty' 2>/dev/null | head -n 1 || true)
        if [ -n "$cur_id" ] && [ "$attempt" -gt 1 ]; then
            echo "seed: Radarr application present (id $cur_id)"
            break
        fi
        if [ -n "$cur_id" ]; then
            req_body=$(printf '%s' "$body" | jq --argjson id "$cur_id" '. + {id: $id, name: "Radarr"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $PROWLARR_API_KEY" \
                --header="Content-Type: application/json" \
                --method=PUT --body-data="$req_body" "$base/$cur_id" 2>/dev/null || true
        else
            req_body=$(printf '%s' "$body" | jq '. + {name: "Radarr"}' || true)
            wget -q -O /dev/null --header="X-Api-Key: $PROWLARR_API_KEY" \
                --header="Content-Type: application/json" \
                --post-data="$req_body" "$base" 2>/dev/null || true
        fi
        apps=$(wget -q -O - --header="X-Api-Key: $PROWLARR_API_KEY" "$base" 2>/dev/null || true)
        verify_id=""
        if [ -n "$apps" ]; then
            verify_id=$(printf '%s' "$apps" | jq -r '.[] | select(.name=="Radarr") | .id // empty' 2>/dev/null | head -n 1 || true)
        fi
        if [ -n "$verify_id" ]; then
            echo "seed: Radarr application present (id $verify_id)"
            break
        fi
        echo "seed: Radarr upsert attempt $attempt failed, retrying"
        attempt=$((attempt + 1))
        [ "$attempt" -le 10 ] && sleep 10 || true
    done

    wget -q -O /dev/null --header="X-Api-Key: $PROWLARR_API_KEY" \
        --post-data="" "$base/sync" 2>/dev/null || true
}

if [ "$(id -u)" = "0" ]; then
    addgroup -g "$PGID" -S radarr 2>/dev/null || true
    adduser -u "$PUID" -S -G radarr -h /config -s /sbin/nologin radarr 2>/dev/null || true

    mkdir -p /config

    # Radarr has no env-var or CLI override for its API key, so seed a
    # minimal config.xml on first run. Existing configs are never overwritten.
    #
    # * ApiKey is seeded (when provided) so downstream containers share a
    #   stable credential instead of scraping the auto-generated key.
    # * AllowedHosts = "*" disables the Host-header check so nginx-proxy's
    #   forwarded hostname is always accepted (no config needed per domain).
    # * AuthenticationMethod = External disables the in-app login form via the
    #   supported "no authentication / proxy-delegated" scheme (the `None`
    #   value is deprecated in Servarr 2.x and officially no longer valid;
    #   it is also what Radarr's own stock config seeds, and it broke DI in
    #   this build). This matches the stack's LAN-only posture (SABnzbd
    #   behaves the same way). Radarr deliberately refuses the
    #   local-address bypass when an X-Forwarded-For header is present
    #   (anti-spoofing), so DisabledForLocalAddresses would still force a
    #   login behind nginx-proxy. External auth is the only zero-friction
    #   mode behind a proxy; the API stays protected by the API key. If the
    #   proxy is ever exposed beyond the LAN/VPN, switch to Forms auth in
    #   Settings > General and set credentials.
    # * AuthenticationRequired = DisabledForLocalAddresses: NOT `Disabled`.
    #   Radarr crashes with a DryIoc InvalidCastException (500 on
    #   every request, including /api/v3/system/status) when
    #   AuthenticationRequired=Disabled — verified empirically; with
    #   AuthenticationMethod=External the value is inert anyway.
    if [ ! -f /config/config.xml ]; then
        {
            echo '<?xml version="1.0" encoding="utf-8"?>'
            echo '<Config>'
            if [ -n "${RADARR_API_KEY:-}" ]; then
                printf '  <ApiKey>%s</ApiKey>\n' "$RADARR_API_KEY"
            fi
            echo '  <Port>7878</Port>'
            echo '  <AuthenticationMethod>External</AuthenticationMethod>'
            echo '  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>'
            echo '  <AllowedHosts>*</AllowedHosts>'
            echo '</Config>'
        } > /config/config.xml
    fi

    chown -R "$PUID:$PGID" /config 2>/dev/null || true

    # Start Radarr in the background as the unprivileged user, seed the
    # Sabnzbd + qBittorrent download clients and the Prowlarr Application
    # once the APIs are up (only when the respective credentials are set),
    # then wait on Radarr as the foreground action.
    su-exec "$PUID:$PGID" /app/Radarr -nobrowser -data=/config &
    RADARR_PID=$!
    if [ -n "${RADARR_API_KEY:-}" ] && [ -n "${SABNZBD_API_KEY:-}" ]; then
        seed_sabnzbd_client || true
    fi
    if [ -n "${RADARR_API_KEY:-}" ] && [ -n "${QBT_WEBUI_PASSWORD:-}" ]; then
        seed_qbittorrent_client || true
    fi
    if [ -n "${RADARR_API_KEY:-}" ] && [ -n "${PROWLARR_API_KEY:-}" ]; then
        seed_prowlarr_app || true
    fi
    wait "$RADARR_PID"
    exit $?
fi

exec "$@"
