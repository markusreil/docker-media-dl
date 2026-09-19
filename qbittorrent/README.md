# qBittorrent (Alpine)

A minimal Alpine-based qBittorrent image for the `media-dl` compose project.

Alpine packages the headless `qbittorrent-nox` build in its community
repository, so the image installs it via apk — no source build and no
third-party image. `python3` is present in the image only for the entrypoint's
PBKDF2 WebUI-password hashing.

## Build

The image is built by `../docker-compose.yml`:

```sh
cd ..
# edit .env first (required by compose)
docker compose build qbittorrent
```

`QBT_VERSION` is a required build arg (`Dockerfile` default: `5.2.1`).
The Alpine package is pinned with `~=`, e.g. `5.2.1-r0`.

## Runtime

| Item | Value |
| --- | --- |
| Port | `8085` (WebUI HTTP, exposed to the internal network only, forwarded via `VIRTUAL_HOST`) |
| Peer port | `6881` TCP+UDP published to the host (the one host-port exception in the stack, needed for inbound bittorrent connections; host port is configurable via `QBT_BT_PORT`) |
| Config volume | `qbittorrent-config` → `/config` (holds `qBittorrent.conf`) |
| Data volume | `qbittorrent-data` → `/data` (incomplete + complete torrents, same volume so finished moves are atomic renames) |
| Entrypoint | `/usr/local/bin/entrypoint.sh` |

The container joins the external `nginx-proxy` network and is reached through
the existing `nginx-proxy` / Let's Encrypt sidecar using `VIRTUAL_HOST` — at
`qbittorrent.<BASE_DOMAIN>` (see `BASE_DOMAIN` in `.env`).

### Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | UID/GID that files and the process run as (default `1000:1000`) |
| `TZ` | Container timezone |
| `VIRTUAL_HOST` | Public hostname routed by nginx-proxy (`qbittorrent.<BASE_DOMAIN>`) |
| `VIRTUAL_PORT` | Container port the proxy forwards to (`8085`) |
| `LETSENCRYPT_HOST` / `LETSENCRYPT_EMAIL` | Certificate request details |
| `QBT_HOST` | Public hostname (`qbittorrent.<BASE_DOMAIN>`), seeded into `WebUI\ServerDomains` on first start |
| `QBT_HOST_WHITELIST` | Extra accepted Host headers, hardcoded in compose as `qbittorrent;qbittorrent.<BASE_DOMAIN>` |
| `QBT_AUTH_SUBNET_WHITELIST` | Optional CIDR subnets that bypass the WebUI login (`172.18.0.0/16` in this repo's `.env`); empty = login always required. Seeded into `WebUI\AuthSubnetWhitelist` on first start |
| `QBT_WEBUI_USERNAME` | WebUI login username (default `admin`) |
| `QBT_WEBUI_PASSWORD` | WebUI login password — **required**, seeded as a PBKDF2 hash on first start |
| `QBT_BT_PORT` | Host port for bittorrent peer traffic (TCP+UDP), forwarded to the container's fixed port `6881` (default `6881`) |

### Startup behaviour

On first start, if `/config/qBittorrent/config/qBittorrent.conf` does not
exist, the entrypoint writes a minimal config:

```ini
[BitTorrent]
Session\DefaultSavePath=/data/complete
Session\TempPath=/data/incomplete
Session\TempPathEnabled=true
Session\Port=6881

[LegalNotice]
Accepted=true

[Preferences]
WebUI\Address=*
WebUI\HostHeaderValidation=true
WebUI\Port=8085
WebUI\ServerDomains="<QBT_HOST>;<QBT_HOST_WHITELIST>"  # de-duplicated
WebUI\AuthSubnetWhitelistEnabled=true   (when QBT_AUTH_SUBNET_WHITELIST is set)
WebUI\AuthSubnetWhitelist="<QBT_AUTH_SUBNET_WHITELIST>"
WebUI\Username=<user>
WebUI\Password_PBKDF2="@ByteArray(<hash>)"
```

The password hash is derived in the entrypoint with PBKDF2-HMAC-SHA512
(16-byte salt, 100000 iterations, 64-byte key) which matches the format
qBittorrent itself generates (verified against the actual release). Because
qBittorrent has no anonymous mode, the seeded login is the normal way in; the
only exception is when `QBT_AUTH_SUBNET_WHITELIST` is set — clients from those
subnets (e.g. the docker network nginx-proxy attaches to) skip the login.
Existing configs are never overwritten; to change credentials or reseed,
remove the service and its volume then `docker compose up -d`.

## Access paths

1. **Through nginx-proxy** — WebUI at `https://qbittorrent.<BASE_DOMAIN>`, login
   with `QBT_WEBUI_USERNAME` / `QBT_WEBUI_PASSWORD` (no login if the proxy's
   subnet is in `QBT_AUTH_SUBNET_WHITELIST`).

2. **Direct container-to-container** — other containers reach it at
   `http://qbittorrent:8085` with the same credentials (basic auth over the
   API works; for the WebUI API, qBittorrent's CSRF protection requires a
   matching `Referer` header on logins, i.e. set `Referer` to the
   qBittorrent origin).

3. **Peer traffic** — host port `QBT_BT_PORT` (default `6881`) TCP+UDP must
   be reachable from the internet/VPN for inbound torrent connections (port
   must actually be forwarded on the router/firewall).

## Hostname verification

qBittorrent runs `WebUI\HostHeaderValidation` against
`WebUI\ServerDomains` (semicolon-separated whitelist). Both required paths
are seeded: the public hostname (forwarded by nginx-proxy) and the service
name (container-to-container). This mirrors SABnzbd's `host_whitelist`. The
whitelist is not env-configurable; if you rename the compose service, edit
the hardcoded `QBT_HOST_WHITELIST` value in `docker-compose.yml`.

## Configuration reference

Configuration lives in `/config/qBittorrent/config/qBittorrent.conf` inside
the `qbittorrent-config` volume. qBittorrent rewrites it itself as settings
change. The entrypoint only seeds it on first start.

Changing WebUI credentials, ports, or session paths after first start
requires reseeding:

```sh
docker compose rm -sf qbittorrent
docker volume rm media-dl_qbittorrent-config
docker compose up -d
```

Or edit via the WebUI. The config volume is `media-dl_qbittorrent-config`.
