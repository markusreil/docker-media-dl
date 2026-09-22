# media-dl

A collection of Docker containers for media download, archival and playback,
running as a single `docker compose` project with cluster name `media-dl`.

Everything is plain Alpine: SABnzbd is built from source tarball, Prowlarr from
the official musl build, qBittorrent from Alpine's community package
(`qbittorrent-nox`) — all still plain Alpine, no LinuxServer/third-party images.
All configuration lives in `.env` (hidden, gitignored — copy via
`cp env.example .env`); the tracked template is `env.example`.
`docker compose` fails fast if a required
variable is missing.

| Service | What it does | Public hostname | Port (internal) |
| --- | --- | --- | --- |
| [sabnzbd](sabnzbd/) | Usenet downloader | `sabnzbd.<BASE_DOMAIN>` | 8080 |
| [prowlarr](prowlarr/) | Indexer manager (torrent/usenet) | `prowlarr.<BASE_DOMAIN>` | 9696 |
| [radarr](radarr/) | Movie manager | `radarr.<BASE_DOMAIN>` | 7878 |
| [sonarr](sonarr/) | TV series manager | `sonarr.<BASE_DOMAIN>` | 8989 |
| [qbittorrent](qbittorrent/) | BitTorrent client (WebUI) | `qbittorrent.<BASE_DOMAIN>` | 8085 (+6881 tcp/udp host) |
| [jellyfin](jellyfin/) | Media server | `jellyfin.<BASE_DOMAIN>` | 8096 |

Each service directory has its own README with build details, environment
variables and access notes: [sabnzbd/README.md](sabnzbd/README.md),
[prowlarr/README.md](prowlarr/README.md),
[radarr/README.md](radarr/README.md),
[sonarr/README.md](sonarr/README.md),
[qbittorrent/README.md](qbittorrent/README.md).

## Prerequisites

* `docker` with Compose v2 (`docker compose`).
* A running [nginx-proxy](https://github.com/nginx-proxy/nginx-proxy) with the
  Let's Encrypt companion on a shared external docker network
  (default name `web-proxy`, set `NGINX_PROXY_NETWORK` in `.env`). Public
  hostnames are routed through it and certificates are requested from
  Let's Encrypt.

Networking: everything is reached via the proxy (`expose` only). The single
host-ports exception is qbittorrent, which publishes
`${QBT_BT_PORT}:6881/tcp+udp` for bittorrent peer traffic.

## Quick start

```sh
# edit .env first (copy via `cp env.example .env`; all config, defaults, and comments live there)
docker compose build
docker compose up -d
```

Containers are reached at:

* `http://sabnzbd.<BASE_DOMAIN>` (SABnzbd web UI)
* `http://prowlarr.<BASE_DOMAIN>` (Prowlarr web UI)
* `http://radarr.<BASE_DOMAIN>` (Radarr UI)
* `http://sonarr.<BASE_DOMAIN>` (Sonarr UI)
* `http://qbittorrent.<BASE_DOMAIN>` (qBittorrent web UI, login required)
* `http://jellyfin.<BASE_DOMAIN>` (Jellyfin media server)

## Hostname scheme

Every service is published by nginx-proxy at `<service>.<BASE_DOMAIN>`, where
`BASE_DOMAIN` comes from `.env`. Change one variable to move the whole stack:

| `BASE_DOMAIN` in `.env` | SABnzbd | Prowlarr | Radarr | Sonarr | qBittorrent | Jellyfin |
| --- | --- | --- | --- | --- | --- | --- |
| `localhost` | `sabnzbd.localhost` | `prowlarr.localhost` | `radarr.localhost` | `sonarr.localhost` | `qbittorrent.localhost` | `jellyfin.localhost` |
| `media-dl.localhost` | `sabnzbd.media-dl.localhost` | `prowlarr.media-dl.localhost` | `radarr.media-dl.localhost` | `sonarr.media-dl.localhost` | `qbittorrent.media-dl.localhost` | `jellyfin.media-dl.localhost` |

The hostnames are declared once as YAML anchors in `x-hosts` at the top of
`docker-compose.yml` and referenced by all services for `VIRTUAL_HOST`,
`LETSENCRYPT_HOST`, and the Homepage dashboard labels (`homepage.href`).

TLS is per-service: nginx-proxy reads `HTTPS_METHOD` from each proxied
container, so one service can be HTTP-only without affecting the rest. Jellyfin
sets it from `JELLYFIN_HTTPS_METHOD` (default `nohttps` = plain HTTP, no 443
listener, no redirect); the other services keep the proxy default (`redirect`).

## Configuration (.env)

All variables are required unless noted. Compose errors on any missing or
empty required variable (see `docker-compose.yml`).

| Variable | Purpose | Example |
| --- | --- | --- |
| `TZ` | Container timezone | `Europe/Amsterdam` |
| `PUID` / `PGID` | Host UID/GID owning downloaded files | `1000` / `1000` |
| `NGINX_PROXY_NETWORK` | External nginx-proxy docker network | `web-proxy` |
| `BASE_DOMAIN` | Domain suffix for all public hostnames | `localhost` |
| `SABNZBD_VERSION` | SABnzbd release version (build arg) | `5.1.3` |
| `SABNZBD_API_KEY` | SABnzbd API key (seeded into config) | 32-char hex |
| `SABNZBD_NZB_KEY` | SABnzbd NZB key (optional) | 32-char hex |
| `PROWLARR_VERSION` | Prowlarr release version (build arg) | `2.6.5.5623` |
| `PROWLARR_API_KEY` | Prowlarr API key (seeded into config) | 32-char hex |
| `RADARR_VERSION` | Radarr release version (build arg) | `6.4.4.10685` |
| `RADARR_API_KEY` | Radarr API key (seeded into config) | 32-char hex |
| `SONARR_VERSION` | Sonarr release version (build arg) | `4.0.20.3014` |
| `SONARR_API_KEY` | Sonarr API key (seeded into config) | 32-char hex |
| `QBT_VERSION` | qBittorrent release version (build arg) | `5.2.1` |
| `QBT_WEBUI_USERNAME` | qBittorrent WebUI login username | `admin` |
| `QBT_WEBUI_PASSWORD` | qBittorrent WebUI login password (**required**) | any string |
| `QBT_BT_PORT` | Host port for bittorrent peer traffic (TCP+UDP) | `6881` |
| `MEDIA_VOLUME` | Shared media source switch (`media-local` default, or `media-nfs`); Jellyfin mounts `/media:ro`, Radarr/Sonarr mount `/media` read-write | `media-nfs` |
| `MEDIA_NFS_HOST` / `MEDIA_NFS_PATH` / `MEDIA_NFS_VERS` | NFS server, export path, version (default `4`); only used when `MEDIA_VOLUME=media-nfs` | — |
| `MEDIA_ARCHIVED_NFS_PATH` | Optional second NFS export path on the same host (reuses `MEDIA_NFS_HOST`/`MEDIA_NFS_VERS`); only used with the `docker-compose.media-archived.yml` overlay (see Storage) | `/mnt/tank/archive` |
| `JELLYFIN_VERSION` | Jellyfin release version, tracks upstream `jellyfin/jellyfin` tag (build arg) | `12.1` |
| `JELLYFIN_API_KEY` | Jellyfin API key (seeded into `jellyfin.db` on start) | 32-char hex |
| `JELLYFIN_HTTPS_METHOD` | Per-vhost nginx-proxy `HTTPS_METHOD` for Jellyfin only: `nohttps` (HTTP-only), `redirect` (proxy default), `noredirect` | `nohttps` |

To update a service, bump its version variable and rebuild:

```sh
docker compose build sabnzbd prowlarr qbittorrent
docker compose up -d
```

## Storage

Data is kept in named volumes (created by Compose), never inside the images:

| Volume | Mounted at | Contents |
| --- | --- | --- |
| `sabnzbd-data` | REMOVED — replaced by shared `downloads` (see below) |
| `sabnzbd-config` | `/config` | `sabnzbd.ini`, logs, admin |
| `downloads` | `/data` in sabnzbd, qbittorrent, radarr, and sonarr (radarr/sonarr read-write) | `usenet/incomplete`, `usenet/complete`, `usenet/backup` (SABnzbd) + `torrents/incomplete`, `torrents/complete` (qBittorrent) |
| `prowlarr-config` | `/config` | `config.xml`, logs |
| `radarr-config` | `/config` | `config.xml`, logs |
| `sonarr-config` | `/config` | `config.xml`, logs |
| `qbittorrent-config` | `/config` | `qBittorrent.conf` |
| `qbittorrent-data` | REMOVED — replaced by shared `downloads` (see above) |
| `media-local` | `/media` (Jellyfin `:ro`, Radarr/Sonarr read-write) | local media library (default source via `MEDIA_VOLUME`) |
| `media-nfs` | `/media` (Jellyfin `:ro`, Radarr/Sonarr read-write) | NFS media library mount (used when `MEDIA_VOLUME=media-nfs`) |
| `media-archived-nfs` | `/media-archived` (`:ro` in Jellyfin, Radarr, Sonarr) | Second NFS export on the same host — archived library, read-only (only with the overlay below) |

### Archived library (optional overlay)

Compose has no conditional mounts, so the archived library lives in
`docker-compose.media-archived.yml` instead of the base file — the base
stack works with or without it. To serve the archive, add `-f` to manual
commands and automatic deployments alike:

```sh
docker compose -f docker-compose.yml -f docker-compose.media-archived.yml up -d
```

This mounts `media-archived-nfs` (`:${MEDIA_ARCHIVED_NFS_PATH}`, same host)
read-only at `/media-archived` in Jellyfin, Radarr and Sonarr. Without the
overlay the variable is ignored entirely; with it, compose fails fast when
it is missing or empty.

Both entrypoints are write-once: they seed a minimal config on **first start
only** (API keys, hostnames, auth mode) and never overwrite an existing one.
To reseed, remove the service and its volume, then recreate.

Downloads share one `downloads` volume mounted at identical `/data` paths in
sabnzbd, qbittorrent, radarr, and sonarr (radarr/sonarr read-write for
hardlink/import).
Per-client subdirs (`usenet/` for SABnzbd, `torrents/` for qBittorrent) avoid
the name clash of both clients writing to `/data/complete`. Identical paths
mean Radarr/Sonarr see the exact downloader paths — no RemotePathMappings
needed, the Servarr "directory does not appear to exist" health check stays
green, and hardlinks work on the single filesystem.

> Migration: existing installs must reseed the sabnzbd and qbittorrent
> configs (write-once seeders) so the new `/data/usenet/...` and
> `/data/torrents/...` paths apply; the old `sabnzbd-data` /
> `qbittorrent-data` volumes become orphans (remove once migrated).

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
docker-compose.media-archived.yml
                       optional overlay: archived-library volume + mounts
                       (`-f` it in to serve /media-archived, else ignored)
env.example            tracked example configuration (copy to .env, hidden/ignored)
.env                   local configuration (secrets) — hidden, gitignored, never committed
sabnzbd/               Alpine SABnzbd image: Dockerfile, entrypoint, README
prowlarr/              Alpine Prowlarr image: Dockerfile, entrypoint, README
radarr/                Alpine Radarr image: Dockerfile, entrypoint, README
sonarr/                Alpine Sonarr image: Dockerfile, entrypoint, README
qbittorrent/           Alpine qBittorrent image: Dockerfile, entrypoint, README
jellyfin/              Jellyfin image (official upstream base, see README): Dockerfile, entrypoint, README
```

## TODO: candidate integrations

Not implemented yet — additional services evaluated September 2026, ordered by
value for this stack. Any that get added must keep the existing conventions:
`.env`-only config (documented in `env.example` + service README), `x-hosts`
anchor + `*...*-href`, external `nginx-proxy` network with `expose` only, a
standard config volume, and a write-once entrypoint. Alpine base preferred;
official-image exceptions must be documented like Jellyfin's.

### Worth adding

* **Bazarr** — subtitle companion for Radarr/Sonarr. Fills the one real
  functional gap: Jellyfin's built-in subtitle support has no per-show language
  profiles or upgrade-on-better-subtitle. Active (v1.6.1, Sep 2026). Reads the
  Radarr/Sonarr APIs (needs their API keys + internal
  `http://sonarr:8989` reachability) and reads/writes sidecar subtitles under
  `/media`. No official Alpine image → small python/pip Dockerfile, same
  pattern as SABnzbd.
* **Cleanuparr** — download-queue housekeeping: removes stalled/blocked items
  from SABnzbd and qBittorrent queues (supersedes Decluttarr). Active
  (v2.10.6, Sep 2026). .NET — official `ghcr.io/cleanuparr/cleanuparr` image
  or a source build.
* **Recyclarr** — syncs TRaSH-Guides quality profiles and custom formats into
  Radarr/Sonarr on a schedule; no UI, no state to expose. Active (v8.7.2,
  Sep 2026). Tiny .NET tool, easy Alpine build.

### Conditional (only if the household wants it)

* **Seerr** (formerly Jellyseerr; Overseerr is now archived) — request and
  discovery frontend for Jellyfin + Sonarr/Radarr, lets other users request
  media without touching the *arr UIs. Active (~12.6k stars, Sep 2026).
  Heaviest build (Node) → candidate for a documented official-image exception
  like Jellyfin's, or build Node from source.
* **Calibre-Web-Automated (CWA)** — ebook ingest, OPDS, and Kobo/Koreader sync;
  the de-facto replacement for the now-archived Readarr. Ebook-first: its
  supported format list has no m4b/mp3 or audiobook ingest — see
  Audiobooks / podcasts below for that side. Active (v4.0.6, Feb 2026).
  Python — official `crocodilestick/calibre-web-automated` image or a source
  build. Needs its own config volume plus a books volume (new storage, unlike
  the existing downloads/media volumes).
* **autobrr** — instant grab from IRC/announce feeds; only worthwhile with
  private trackers that publish announce channels. With Prowlarr RSS/scheduled
  searches alone it adds nothing. Active (v1.86.0, Sep 2026). Single Go binary,
  trivial Alpine build.
* **Lidarr** — "Sonarr for music" (MusicBrainz metadata). Alive but
  low-velocity (last real release Nov 2025) and adds a metadata-server
  dependency that movies/TV don't have. Only if automated music is wanted;
  same .NET musl build pattern as Radarr/Sonarr.

### Audiobooks / podcasts

Audiobooks are a separate track from the video stack. Jellyfin is a poor
audiobook server (per-track rather than per-book progress, weak m4b chapter
support, no Audible metadata) and its Books plugin is ebooks-only — keep
Jellyfin for video and add a dedicated server for listening.

* **Audiobookshelf** — self-hosted audiobook + podcast server: per-user position
  sync, chapter-accurate m4b navigation, native Android/iOS apps with offline
  download, podcast auto-download. Very active (v2.36.1, Sep 2026). Library-only
  — it does **not** search indexers or download audiobooks, so files must be fed
  to it. Source build is heavy (Node + FFmpeg + client) → candidate for a
  documented official-image exception like Jellyfin's. Serve on a subdomain
  (`audiobookshelf.<BASE_DOMAIN>`); upstream constrains subpath hosting to
  exactly `/audiobookshelf`.
* **AudioBookRequest** — request UI for audiobook acquisition and the piece that
  replaces the retired Readarr: Audible search → ABS duplicate check → delegates
  search/download to **Prowlarr** (→ SABnzbd/qBittorrent) → triggers an ABS scan.
  Active (~700 stars, Aug 2026). Small Python app, easy Alpine build. Caveat: it
  does not rename/move files after download — point a dedicated downloader
  category at an ABS-watched folder (auto-detect). Only useful if the Prowlarr
  indexers carry audiobook categories.
* **Manual pipeline (no new service)** — Prowlarr saved-search/RSS → downloader
  category → ABS-watched folder. Adequate for low audiobook volume; prefer this
  over AudioBookRequest if request-driven acquisition isn't needed.
* **Audnexus** (optional) — ABS's metadata/chapter source (Audible/Apple/Google
  aggregation, maintained 2026). Self-host only if you want to avoid the public
  API dependency; no action needed day one.
* **Not recommended** — Readarr forks/mirrors (unsupported), LazyLibrarian
  (stale since 2022, ebook-oriented), Bookseerr (no community).

Ebooks are a separate decision: see Calibre-Web-Automated above — it is
ebook-only and does not address audiobooks. Running CWA (ebooks) and
Audiobookshelf (audiobooks/podcasts) together is complementary, not overkill.

### Considered and rejected

* **Readarr** — archived Jun 2025 (metadata unusable, no rebuild planned).
  Do not add; use CWA if books are wanted.
* **Whisparr** — active but off-mission for a general-purpose stack.
* **Decluttarr** — superseded by Cleanuparr.
* **Profilarr** — redundant with Recyclarr; pick one.
* **Buildarr** — stalled since May 2024, and its config-as-code model conflicts
  with this repo's `.env` + write-once-seeder approach.
* **Notifiarr** — adds an external-service dependency; native *arr/Jellyfin
  webhooks cover notifications for a LAN-only stack.

Research current as of Sep 2026 (GitHub activity/release evidence); re-verify
maintenance status before implementing, as several projects in this space have
changed state recently (Overseerr archived, Readarr retired, Jellyseerr renamed
to Seerr).