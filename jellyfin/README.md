# Jellyfin (official image)

A thin layer on the official `jellyfin/jellyfin` image for the `media-dl`
compose project.

This is the single documented exception to the repo's Alpine-only rule:
Alpine's community apk is stuck at 10.10.x while upstream Jellyfin is at
12.1, so Jellyfin builds `FROM jellyfin/jellyfin` (Debian bookworm-slim)
instead of Alpine. Every other service stays on Alpine.

Version scheme note: 10.11.x was the last 10.x release (no 10.12 ever
existed); upstream then moved to 12.x, so this service tracks `12.1`.

No hardware transcoding is configured: no `/dev/dri` passthrough and no
discovery/published ports (7359/1900/8920). Software transcoding via the
bundled ffmpeg 8 only.

## Build

The image is built by `../docker-compose.yml`:

```sh
cd ..
# edit .env first (required by compose)
docker compose build jellyfin
```

`JELLYFIN_VERSION` is a required build arg (`Dockerfile` default: `12.1`,
tracking the upstream `jellyfin/jellyfin` tag — e.g. `12.1` / `12.1.0`, never
`:latest`). The image records `ENV BASE_IMAGE=jellyfin/jellyfin` (upstream
base; version still via `JELLYFIN_VERSION`). To bump: set `JELLYFIN_VERSION` in `.env` deliberately, then
rebuild.

Build context files live in `docker/` (`docker/entrypoint.sh` is copied to
`/usr/local/bin/entrypoint.sh` in the image).

## Migration warning (10.x -> 12.x)

* Back up `/config` (the `jellyfin-config` volume) before upgrading.
* Expect a library rescan after the upgrade.
* Plugins must be rebuilt for .NET 10 — update/reinstall them.
* Legacy `/emby` API routes were removed; update any clients/scripts that
  still use them.

## Runtime

| Item | Value |
| --- | --- |
| Base | Debian bookworm-slim (official `jellyfin/jellyfin:12.1`) |
| Port | `8096` (HTTP, exposed to the internal network only) |
| Config volume | `jellyfin-config` → `/config` (data dir, `config/` + `log/` subdirs) |
| Cache volume | `jellyfin-cache` → `/cache` (transcode/cache dir) |
| Media volume | `/media:ro` from `MEDIA_VOLUME` — `media-local` (regular volume, default) or `media-nfs` (NFS library mount, shared with Radarr/Sonarr) |
| Archived media volume | `/media-archived:ro` from `media-archived-nfs` (second NFS export on the same host, read-only; only with the `docker-compose.media-archived.yml` overlay) |
| Privilege drop | `gosu` (Debian has no `su-exec`) |
| ffmpeg | Bundled ffmpeg 8 at `/usr/lib/jellyfin-ffmpeg/ffmpeg` (`JELLYFIN_FFMPEG`) |
| Web UI | `/jellyfin/jellyfin-web` (`JELLYFIN_WEB_DIR`) |
| Entrypoint | `/usr/local/bin/entrypoint.sh` (from `docker/entrypoint.sh`, drops privileges, no config seeding) |

The container does not publish ports to the host. It joins the external
`nginx-proxy` network and is reached through the existing `nginx-proxy` /
Let's Encrypt sidecar using `VIRTUAL_HOST`.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | UID/GID that files and the process run as (default `1000:1000`) |
| `TZ` | Container timezone |
| `VIRTUAL_HOST` | Public hostname routed by nginx-proxy, derived from `BASE_DOMAIN` in `.env` as `jellyfin.<BASE_DOMAIN>` |
| `VIRTUAL_PORT` | Container port the proxy forwards to (`8096`) |
| `LETSENCRYPT_HOST` | Certificate hostname (contact uses proxy `DEFAULT_EMAIL`) |
| `MEDIA_VOLUME` | Media source, env-var-only switch: `media-local` (default) or `media-nfs`; change in `.env` then `docker compose up -d` (no data migration — local starts empty). Shared with Radarr/Sonarr (Jellyfin mounts ro, Radarr/Sonarr mount rw) |
| `JELLYFIN_API_KEY` | API key (access token), seeded into `jellyfin.db` `ApiKeys` on start and shared with peers; 32-char lowercase hex |
| `MEDIA_NFS_HOST` / `MEDIA_NFS_PATH` / `MEDIA_NFS_VERS` | NFS server, export path (e.g. `/mnt/tank/media`) and version (default `4`); only used when `MEDIA_VOLUME=media-nfs` |
| `MEDIA_ARCHIVED_NFS_PATH` | Optional second NFS export path on the same server (reuses `MEDIA_NFS_HOST`/`MEDIA_NFS_VERS`); only used with the `docker-compose.media-archived.yml` overlay, served read-only at `/media-archived` |

### Media source

`/media` is read-only under either source. Both volumes stay declared in
`docker-compose.yml`; the service mounts whichever
`MEDIA_VOLUME` names. The NFS volume itself is `hard` (read-write, so
Radarr/Sonarr can import); only Jellyfin's mount adds `:ro`. `hard` means playback
retries through transient server hiccups instead of erroring mid-stream.

`/media-archived` is a second NFS export on the same server
(`media-archived-nfs`, path from `MEDIA_ARCHIVED_NFS_PATH`), mounted
read-only in Jellyfin, Radarr and Sonarr — but only when the
`docker-compose.media-archived.yml` overlay is included (`-f`), since
compose cannot conditionally omit mounts. The NFS mount itself carries `ro`,
so the archive cannot be written to even by the read-write `/media` peers.

### Startup behaviour

No config files are seeded. On first start the entrypoint only creates
`/config/config`, `/config/log`, `/cache`, and `/media`, fixes ownership,
and drops privileges. Jellyfin's stock first-run wizard runs in the web UI
(admin account, libraries, metadata language) — complete it there.

The API key *is* seeded into the database: when `JELLYFIN_API_KEY` is set
and `/config/data/jellyfin.db` already has the `ApiKeys` table, the
entrypoint runs (as the target `PUID:PGID` user, pre-exec while the server
is stopped):

```sql
INSERT OR IGNORE INTO ApiKeys
  (DateCreated, DateLastActivity, Name, AccessToken)
  VALUES ('<now-utc>', '0001-01-01 00:00:00.0000000', 'media-dl', '<key>');
```

`INSERT OR IGNORE` makes this idempotent across restarts. On the very first
start the DB does not exist yet (the server creates it via EF migrations),
so the entrypoint skips with a message and the key converges on the next
start — just restart once after first boot. Verify inside the container:

```sh
sqlite3 /config/data/jellyfin.db "SELECT Name,AccessToken FROM ApiKeys;"
```

To reseed, delete the row (`DELETE FROM ApiKeys WHERE Name='media-dl';`)
and restart, or remove the service and its volumes (`rm` + `volume rm ...`,
which wipes all Jellyfin state).

Existing configs are never overwritten. To start over, remove the service
and its volumes, then recreate:

```sh
docker compose rm -sf jellyfin
docker volume rm media-dl_jellyfin-config media-dl_jellyfin-cache
docker compose up -d jellyfin
```

(The NFS media volume holds the library itself and is left untouched.)

## Access paths

### Through nginx-proxy (UI + API)

The public UI is at `https://jellyfin.<BASE_DOMAIN>`.

Jellyfin's Known Proxies / trusted-proxy handling: behind nginx-proxy the
server sees the proxy's IP; if client-IP logging or remote-access controls
misbehave, add the proxy network to Jellyfin's Known Proxies setting
(`Dashboard > Networking`). Websockets (used by the web UI for live updates)
work through nginx-proxy's default configuration.

### Direct container-to-container (API)

Other containers on the same network reach Jellyfin at
`http://jellyfin:8096` (e.g. for the Homepage widget).

## Configuration reference

Jellyfin stores its state under the config volume:

* `/config/config` — `system.xml`, `encoding.xml`, `network.xml`
  (`JELLYFIN_CONFIG_DIR`)
* `/config/log` — server logs (`JELLYFIN_LOG_DIR`)
* `/config` (root) — `data/` library databases (`JELLYFIN_DATA_DIR`)
* `/cache` — transcodes and temporary files (`JELLYFIN_CACHE_DIR`)
* `/media` — read-only library mount (`media-local` or NFS)
* `/media-archived` — read-only archived-library mount (second NFS export, same host; overlay only)

Use the web UI (`Dashboard`) for day-to-day changes; Jellyfin rewrites its
XML configs itself. Key paths passed on the command line:

* `--datadir /config --configdir /config/config --logdir /config/log`
* `--cachedir /cache` (webdir/ffmpeg come from the official image defaults:
  `/jellyfin/jellyfin-web` and `/usr/lib/jellyfin-ffmpeg/ffmpeg)
