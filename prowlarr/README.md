# Prowlarr (Alpine)

A minimal Alpine-based [Prowlarr](https://github.com/Prowlarr/Prowlarr) image
for the `media-dl` compose project.

Alpine does not package Prowlarr and obsolescent .NET runtime installs are
heavy, so the image uses Prowlarr's self-contained `linux-musl-core` build
(the .NET runtime is bundled and targets musl, Alpine's libc). The final
image is pure Alpine.

## Build

The image is built by `../docker-compose.yml`:

```sh
cd ..
# edit .env first (required by compose)
docker compose build prowlarr
```

`PROWLARR_VERSION` is a required build arg (`Dockerfile` default: `2.6.5.5623`).

## Runtime

| Item | Value |
| --- | --- |
| Port | `9696` (HTTP, exposed to the internal network only) |
| Config volume | `prowlarr-config` → `/config` (holds `config.xml`, logs) |
| Entrypoint | `/usr/local/bin/entrypoint.sh` (drops privileges, seeds config) |

The container does not publish ports to the host. It joins the external
`nginx-proxy` network and is reached through the existing `nginx-proxy` /
Let's Encrypt sidecar using `VIRTUAL_HOST` — at `prowlarr.<DOMAIN>` (see
`DOMAIN` in `.env`).

### Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | UID/GID that files and the process run as (default `1000:1000`) |
| `TZ` | Container timezone |
| `VIRTUAL_HOST` | Public hostname routed by nginx-proxy (`prowlarr.<DOMAIN>`) |
| `VIRTUAL_PORT` | Container port the proxy forwards to (`9696`) |
| `LETSENCRYPT_HOST` / `LETSENCRYPT_EMAIL` | Certificate request details |
| `PROWLARR_API_KEY` | API key (access token), seeded into `config.xml` on first start, shared with other services, and used by the container healthcheck (required) |

### Startup behaviour

On first start, if `/config/config.xml` does not exist, the entrypoint writes
a minimal config:

```xml
<?xml version="1.0" encoding="utf-8"?>
<Config>
  <ApiKey>                  <!-- only when PROWLARR_API_KEY is set -->
  <Port>9696</Port>
  <AuthenticationMethod>External</AuthenticationMethod>
  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>
  <AllowedHosts>*</AllowedHosts>
</Config>
```

* Seeding the API key keeps it stable across restarts, so other containers
  can consume it as `${PROWLARR_API_KEY}` instead of scraping the
  auto-generated value. Existing configs are never overwritten.
* `AllowedHosts = *` accepts any forwarded `Host` header, so no per-domain
  config is needed on the proxy or when the container is reached by other
  containers as `http://prowlarr:9696`.
* `AuthenticationMethod = External` disables the in-app login form via the
  Servarr "no authentication / proxy-delegated" scheme (the `None` value is
  deprecated and no longer valid in Servarr 2.x; `External` is the officially
  supported name). This matches the stack's LAN-only posture. Note that
  Prowlarr deliberately skips the local-address auth bypass when an
  `X-Forwarded-For` header is present (anti-spoofing), so form-based auth
  would still force a login behind nginx-proxy — external/no auth is the
  only zero-friction mode behind a proxy. `AuthenticationRequired` is set to
  `DisabledForLocalAddresses` rather than `Disabled` because Prowlarr 2.6.5
  returns HTTP 500 on every request when it equals `Disabled` (DryIoc
  resolution bug, verified empirically in this project). If the proxy is ever
  exposed beyond the LAN/VPN, enable Forms auth in `Settings > General` and
  set credentials. The API remains protected by the API key either way.

## Access paths

### Through nginx-proxy (UI + API)

nginx-proxy routes `prowlarr.<DOMAIN>` to the container. The UI is available
at `https://prowlarr.<DOMAIN>`; the API at
`https://prowlarr.<DOMAIN>/api/v1/<...>` with `X-Api-Key: <PROWLARR_API_KEY>`.

### Direct container-to-container (API)

Other containers on the same network reach Prowlarr at
`http://prowlarr:9696`, authenticated with the `X-Api-Key` header:

```sh
curl -H "X-Api-Key: $PROWLARR_API_KEY" http://prowlarr:9696/api/v1/system/status
```

### Indexers and the rest of the stack

Prowlarr is the indexer manager: add indexers there once, then point
Sonarr/Radarr/Lidarr at `http://prowlarr:9696` with the `X-Api-Key` (and
their own API keys) and let the built-in sync distribute indexers to them
("Settings > Apps"). SABnzbd itself needs no Prowlarr connection — downloads
arrive through whatever *arr app grabs from Prowlarr.