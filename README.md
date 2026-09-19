# media-dl

A collection of Docker containers for media download, archival and playback,
running as a single `docker compose` project with cluster name `media-dl`.

Everything is plain Alpine: both images are built from source in this repo —
no LinuxServer/third-party images. All configuration lives in `.env`;
`docker compose` fails fast if a required variable is missing.

| Service | What it does | Public hostname | Port (internal) |
| --- | --- | --- | --- |
| [sabnzbd](sabnzbd/) | Usenet downloader | `sabnzbd.<DOMAIN>` | 8080 |
| [prowlarr](prowlarr/) | Indexer manager (torrent/usenet) | `prowlarr.<DOMAIN>` | 9696 |

Each service directory has its own README with build details, environment
variables and access notes: [sabnzbd/README.md](sabnzbd/README.md),
[prowlarr/README.md](prowlarr/README.md).

## Prerequisites

* `docker` with Compose v2 (`docker compose`).
* A running [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) with the
  Let's Encrypt companion on a shared external docker network
  (default name `web-proxy`, set `NGINX_PROXY_NETWORK` in `.env`). Public
  hostnames are routed through it and certificates are requested from
  Let's Encrypt.

## Quick start

```sh
cp .env.example .env     # then edit .env
docker compose build
docker compose up -d
```

Containers are reached at:

* `http://sabnzbd.<DOMAIN>` (SABnzbd web UI)
* `http://prowlarr.<DOMAIN>` (Prowlarr web UI)

## Hostname scheme

Every service is published by nginx-proxy at `<service>.<DOMAIN>`, where
`DOMAIN` comes from `.env`. Change one variable to move the whole stack:

| `DOMAIN` in `.env` | SABnzbd | Prowlarr |
| --- | --- | --- |
| `localhost` | `sabnzbd.localhost` | `prowlarr.localhost` |
| `media-dl.localhost` | `sabnzbd.media-dl.localhost` | `prowlarr.media-dl.localhost` |

The hostnames are declared once as YAML anchors in `x-hosts` at the top of
`docker-compose.yml` and referenced by both services for `VIRTUAL_HOST` and
`LETSENCRYPT_HOST`.

## Configuration (.env)

All variables are required unless noted. Compose errors on any missing or
empty required variable (see `docker-compose.yml`).

| Variable | Purpose | Example |
| --- | --- | --- |
| `TZ` | Container timezone | `Europe/Amsterdam` |
| `PUID` / `PGID` | Host UID/GID owning downloaded files | `1000` / `1000` |
| `NGINX_PROXY_NETWORK` | External nginx-proxy docker network | `web-proxy` |
| `DOMAIN` | Domain suffix for all public hostnames | `localhost` |
| `ACME_EMAIL` | Contact for Let's Encrypt registration | `admin@example.com` |
| `SABNZBD_VERSION` | SABnzbd release version (build arg) | `5.1.3` |
| `SABNZBD_HOST_WHITELIST` | Extra Host headers SABnzbd accepts | `sabnzbd` |
| `SABNZBD_API_KEY` | SABnzbd API key (seeded into config) | 32-char hex |
| `SABNZBD_NZB_KEY` | SABnzbd NZB key (optional) | 32-char hex |
| `PROWLARR_VERSION` | Prowlarr release version (build arg) | `2.6.5.5623` |
| `PROWLARR_API_KEY` | Prowlarr API key (seeded into config) | 32-char hex |

To update a service, bump its version variable and rebuild:

```sh
docker compose build sabnzbd prowlarr
docker compose up -d
```

## Storage

Data is kept in named volumes (created by Compose), never inside the images:

| Volume | Mounted at | Contents |
| --- | --- | --- |
| `sabnzbd-config` | `/config` | `sabnzbd.ini`, logs, admin |
| `sabnzbd-data` | `/data` | incomplete + complete downloads, config/db backups |
| `prowlarr-config` | `/config` | `config.xml`, logs |

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

## Layout

```
docker-compose.yml     single compose file (services, hosts, networks, volumes)
.env                   all configuration (secrets) — tracked in git
sabnzbd/               Alpine SABnzbd image: Dockerfile, entrypoint, README
prowlarr/              Alpine Prowlarr image: Dockerfile, entrypoint, README
```