#!/bin/sh
set -eu

# Drop privileges to the requested PUID/PGID (defaults 1000:1000).
PUID="${PUID:-1000}"
PGID="${PGID:-1000}"

if [ "$(id -u)" = "0" ]; then
    addgroup -g "$PGID" -S prowlarr 2>/dev/null || true
    adduser -u "$PUID" -S -G prowlarr -h /config -s /sbin/nologin prowlarr 2>/dev/null || true

    mkdir -p /config

    # Prowlarr has no env-var or CLI override for its API key, so seed a
    # minimal config.xml on first run. Existing configs are never overwritten.
    #
    # * ApiKey is seeded (when provided) so downstream containers share a
    #   stable credential instead of scraping the auto-generated key.
    # * AllowedHosts = "*" disables the Host-header check so nginx-proxy's
    #   forwarded hostname is always accepted (no config needed per domain).
    # * AuthenticationMethod = External disables the in-app login form via the
    #   supported "no authentication / proxy-delegated" scheme (the `None`
    #   value is deprecated in Servarr 2.x and officially no longer valid;
    #   it is also what Prowlarr's own stock config seeds, and it broke DI in
    #   this build). This matches the stack's LAN-only posture (SABnzbd
    #   behaves the same way). Prowlarr deliberately refuses the
    #   local-address bypass when an X-Forwarded-For header is present
    #   (anti-spoofing), so DisabledForLocalAddresses would still force a
    #   login behind nginx-proxy. External auth is the only zero-friction
    #   mode behind a proxy; the API stays protected by the API key. If the
    #   proxy is ever exposed beyond the LAN/VPN, switch to Forms auth in
    #   Settings > General and set credentials.
    # * AuthenticationRequired = DisabledForLocalAddresses: NOT `Disabled`.
    #   Prowlarr 2.6.5 crashes with a DryIoc InvalidCastException (500 on
    #   every request, including /api/v1/system/status) when
    #   AuthenticationRequired=Disabled — verified empirically; with
    #   AuthenticationMethod=External the value is inert anyway.
    if [ ! -f /config/config.xml ]; then
        {
            echo '<?xml version="1.0" encoding="utf-8"?>'
            echo '<Config>'
            if [ -n "${PROWLARR_API_KEY:-}" ]; then
                printf '  <ApiKey>%s</ApiKey>\n' "$PROWLARR_API_KEY"
            fi
            echo '  <Port>9696</Port>'
            echo '  <AuthenticationMethod>External</AuthenticationMethod>'
            echo '  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>'
            echo '  <AllowedHosts>*</AllowedHosts>'
            echo '</Config>'
        } > /config/config.xml
    fi

    chown -R "$PUID:$PGID" /config 2>/dev/null || true

    exec su-exec "$PUID:$PGID" "$@"
fi

exec "$@"