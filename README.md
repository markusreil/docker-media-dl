# media-dl

A collection of Docker containers for media download, archival and playback,
running as a single `docker compose` project with cluster name `media-dl`.

Everything is plain Alpine: SABnzbd is built from source tarball, Prowlarr from
the official musl build, qBittorrent from Alpine's community package
(`qbittorrent-nox`) — all still plain Alpine, no LinuxServer/third-party images.
All configuration lives in `.env`; `docker compose` fails fast if a required
variable is missing.

| Service | What it does | Public hostname | Port (internal) |
| --- | --- | --- | --- |
| [sabnzbd](sabnzbd/) | Usenet downloader | `sabnzbd.<BASE_DOMAIN>` | 8080 |
| [prowlarr](prowlarr/) | Indexer manager (torrent/usenet) | `prowlarr.<BASE_DOMAIN>` | 9696 |
| [qbittorrent](qbittorrent/) | BitTorrent client (WebUI) | `qbittorrent.<BASE_DOMAIN>` | 8085 (+6881 tcp/udp host) |

Each service directory has its own README with build details, environment
variables and access notes: [sabnzbd/README.md](sabnzbd/README.md),
[prowlarr/README.md](prowlarr/README.md),
[qbittorrent/README.md](qbittorrent/README.md).

## Prerequisites

* `docker` with Compose v2 (`docker compose`).
* A running [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) with the
  Let's Encrypt companion on a shared external docker network
  (default name `web-proxy`, set `NGINX_PROXY_NETWORK` in `.env`). Public
  hostnames are routed through it and certificates are requested from
  Let's Encrypt.

## Quick start

```sh
# edit .env first (all config, defaults, and comments live there)
docker compose build
docker compose up -d
```

Containers are reached at:

* `http://sabnzbd.<BASE_DOMAIN>` (SABnzbd web UI)
* `http://prowlarr.<BASE_DOMAIN>` (Prowlarr web UI)
* `http://qbittorrent.<BASE_DOMAIN>` (qBittorrent web UI, login required)

## Hostname scheme

Every service is published by nginx-proxy at `<service>.<BASE_DOMAIN>`, where
`BASE_DOMAIN` comes from `.env`. Change one variable to move the whole stack:

| `BASE_DOMAIN` in `.env` | SABnzbd | Prowlarr | qBittorrent |
| --- | --- | --- | --- |
| `localhost` | `sabnzbd.localhost` | `prowlarr.localhost` | `qbittorrent.localhost` |
| `media-dl.localhost` | `sabnzbd.media-dl.localhost` | `prowlarr.media-dl.localhost` | `qbittorrent.media-dl.localhost` |

The hostnames are declared once as YAML anchors in `x-hosts` at the top of
`docker-compose.yml` and referenced by all services for `VIRTUAL_HOST`,
`LETSENCRYPT_HOST`, and the Homepage dashboard labels (`homepage.href`).

## Configuration (.env)

All variables are required unless noted. Compose errors on any missing or
empty required variable (see `docker-compose.yml`).

| Variable | Purpose | Example |
| --- | --- | --- |
| `TZ` | Container timezone | `Europe/Amsterdam` |
| `PUID` / `PGID` | Host UID/GID owning downloaded files | `1000` / `1000` |
| `NGINX_PROXY_NETWORK` | External nginx-proxy docker network | `web-proxy` |
| `BASE_DOMAIN` | Domain suffix for all public hostnames | `localhost` |
| `ACME_EMAIL` | Contact for Let's Encrypt registration | `admin@example.com` |
| `SABNZBD_VERSION` | SABnzbd release version (build arg) | `5.1.3` |
| `SABNZBD_API_KEY` | SABnzbd API key (seeded into config) | 32-char hex |
| `SABNZBD_NZB_KEY` | SABnzbd NZB key (optional) | 32-char hex |
| `PROWLARR_VERSION` | Prowlarr release version (build arg) | `2.6.5.5623` |
| `PROWLARR_API_KEY` | Prowlarr API key (seeded into config) | 32-char hex |
| `QBT_VERSION` | qBittorrent release version (build arg) | `5.2.1` |
| `QBT_WEBUI_USERNAME` | qBittorrent WebUI login username | `admin` |
| `QBT_WEBUI_PASSWORD` | qBittorrent WebUI login password (**required**) | any string |
| `QBT_BT_PORT` | Host port for bittorrent peer traffic (TCP+UDP) | `6881` |

To update a service, bump its version variable and rebuild:

```sh
docker compose build sabnzbd prowlarr qbittorrent
docker compose up -d
```

## Storage

Data is kept in named volumes (created by Compose), never inside the images:

| Volume | Mounted at | Contents |
| --- | --- | --- |
| `sabnzbd-config` | `/config` | `sabnzbd.ini`, logs, admin |
| `sabnzbd-data` | `/data` | incomplete + complete downloads, config/db backups |
| `prowlarr-config` | `/config` | `config.xml`, logs |
| `qbittorrent-config` | `/config` | `qBittorrent.conf` |
| `qbittorrent-data` | `/data` | incomplete + complete torrents |

Both entrypoints are write-once: they seed a minimal config on **first start
only** (API keys, hostnames, auth mode) and never overwrite an existing one.
To reseed, remove the service and its volume, then recreate.

## Security posture

This stack is designed for **local/LAN use** (the `.localhost` hostnames are
one example); the services deliberately do not enforce logins:

* SABnzbd rejects requests from non-private client IPs by design, so
  public-internet clients get `403` regardless of auth.
* Prowlarr runs with authentication disabled (`AuthenticationMethod=External`)
  because form-based auth cannot work transparently behind a reverse proxy
  that forwards `X-Forwarded-For` (anti-spoofing) — see
  [prowlarr/README.md](prowlarr/README.md). The REST API is still protected
  by `PROWLARR_API_KEY`, and the UI can be locked down with Forms auth in
  `Settings > General` if the proxy is ever exposed publicly.
* qBittorrent always requires a login (there is no anonymous mode), so
  `QBT_WEBUI_USERNAME` / `QBT_WEBUI_PASSWORD` are seeded as a PBKDF2 hash
  on first start. It is the one service in the stack that publishes a host
  port (`QBT_BT_PORT`, default `6881`, TCP+UDP) for inbound bittorrent peer
  connections.

## Layout

```
docker-compose.yml     single compose file (services, hosts, networks, volumes)
.env                   all configuration (secrets) — tracked in git
sabnzbd/               Alpine SABnzbd image: Dockerfile, entrypoint, README
prowlarr/              Alpine Prowlarr image: Dockerfile, entrypoint, README
qbittorrent/           Alpine qBittorrent image: Dockerfile, entrypoint, README
```