# Radarr (Alpine)

A minimal Alpine-based [Radarr](https://github.com/Radarr/Radarr) image
for the `media-dl` compose project.

Alpine does not package Radarr and obsolescent .NET runtime installs are
heavy, so the image uses Radarr's self-contained `linux-musl-core` build
(the .NET runtime is bundled and targets musl, Alpine's libc). The final
image is pure Alpine.

## Build

The image is built by `../docker-compose.yml`:

```sh
cd ..
# edit .env first (required by compose)
docker compose build radarr
```

`RADARR_VERSION` is a required build arg (`Dockerfile` default: `6.4.4.10685`).

Build context files live in `docker/` (`docker/entrypoint.sh` is copied to
`/usr/local/bin/entrypoint.sh` in the image).

The image records `ENV BASE_IMAGE=alpine:3.24` (what it was built `FROM`) and
`ENV BUILD_DATE` (build timestamp, defaults to `unknown`).

## Runtime

| Item | Value |
| --- | --- |
| Port | `7878` (HTTP, exposed to the internal network only) |
| Config volume | `radarr-config` → `/config` (holds `config.xml`, logs) |
| Media volume | `/media` read-write from `MEDIA_VOLUME` — `media-local` (regular volume, default) or `media-nfs` (NFS library mount, shared with Jellyfin) |
| Archived media volume | `/media-archived:ro` from `media-archived-nfs` (second NFS export on the same host; scanned, never written to; only with the `docker-compose.media-archived.yml` overlay) |
| Downloads volume | shared `downloads` → `/data` read-write (same volume/path as sabnzbd + qbittorrent: `usenet/` + `torrents/` subdirs) |
| Entrypoint | `/usr/local/bin/entrypoint.sh` (drops privileges, seeds config) |

The container does not publish ports to the host. It joins the external
`nginx-proxy` network and is reached through the existing `nginx-proxy` /
ACME companion using `VIRTUAL_HOST` — at `radarr.<BASE_DOMAIN>` (see
`BASE_DOMAIN` in `.env`).

### Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | UID/GID that files and the process run as (default `1000:1000`) |
| `TZ` | Container timezone |
| `VIRTUAL_HOST` | Public hostname routed by nginx-proxy (`radarr.<BASE_DOMAIN>`) |
| `VIRTUAL_PORT` | Container port the proxy forwards to (`7878`) |
| `ACME_HOST` | Certificate hostname; the certificate is requested from the cluster's ACME companion |
| `GEN_SELF_SIGNED_CERT` | Self-signed certificate opt-in for the LAN/self-signed proxy variant; wired from `RADARR_GEN_SELF_SIGNED_CERT` (default `false`; set `true` for LAN/self-signed). Declared alongside `ACME_HOST` so the proxy variant decides which applies |
| `RADARR_API_KEY` | API key (access token), seeded into `config.xml` on first start, shared with other services, and used by the container healthcheck (required) |
| `SABNZBD_API_KEY` | SABnzbd API key, consumed on every (re)start to upsert the Sabnzbd download client via the Radarr v3 API (required, existing var shared with SABnzbd) |
| `QBT_WEBUI_USERNAME` / `QBT_WEBUI_PASSWORD` | qBittorrent WebUI credentials, consumed on every (re)start to upsert the QBittorrent download client via the Radarr v3 API (existing vars shared with qBittorrent) |
| `PROWLARR_API_KEY` | Prowlarr API key, consumed on every (re)start to register Radarr as an Application inside Prowlarr (required, existing var shared with Prowlarr) |
| `MEDIA_VOLUME` | Media source, env-var-only switch: `media-local` (default) or `media-nfs`; `/media` is mounted read-write so Radarr can import/rename files |
| `MEDIA_ARCHIVED_NFS_PATH` | Optional second NFS export path on the same server (reuses `MEDIA_NFS_HOST`/`MEDIA_NFS_VERS`); only used with the `docker-compose.media-archived.yml` overlay, mounted read-only at `/media-archived` |

### Startup behaviour

On first start, if `/config/config.xml` does not exist, the entrypoint writes
a minimal config:

```xml
<?xml version="1.0" encoding="utf-8"?>
<Config>
  <ApiKey>                  <!-- only when RADARR_API_KEY is set -->
  <Port>7878</Port>
  <AuthenticationMethod>External</AuthenticationMethod>
  <AuthenticationRequired>DisabledForLocalAddresses</AuthenticationRequired>
  <AllowedHosts>*</AllowedHosts>
</Config>
```

* Seeding the API key keeps it stable across restarts, so other containers
  can consume it as `${RADARR_API_KEY}` instead of scraping the
  auto-generated value. Existing configs are never overwritten.
* `AllowedHosts = *` accepts any forwarded `Host` header, so no per-domain
  config is needed on the proxy or when the container is reached by other
  containers as `http://radarr:7878`.
* `AuthenticationMethod = External` disables the in-app login form via the
  Servarr "no authentication / proxy-delegated" scheme (the `None` value is
  deprecated and no longer valid in Servarr 2.x; `External` is the officially
  supported name). This matches the stack's LAN-only posture. Note that
  Radarr deliberately skips the local-address auth bypass when an
  `X-Forwarded-For` header is present (anti-spoofing), so form-based auth
  would still force a login behind nginx-proxy — external/no auth is the
  only zero-friction mode behind a proxy. `AuthenticationRequired` is set to
  `DisabledForLocalAddresses` rather than `Disabled` because Servarr returns
  HTTP 500 on every request when it equals `Disabled` (DryIoc
  resolution bug, verified empirically in this project). If the proxy is ever
  exposed beyond the LAN/VPN, enable Forms auth in `Settings > General` and
  set credentials. The API remains protected by the API key either way.
* To reseed (apply a new API key): `docker compose rm -sf radarr` +
  `docker volume rm media-dl_radarr-config`, then `docker compose up -d`.

### Shared downloads volume (`/data`)

Radarr mounts the shared `downloads` volume at `/data` read-write — identical
paths to sabnzbd (`/data/usenet/...`) and qbittorrent
(`/data/torrents/...`). Identical paths matter: Radarr validates the
downloader's reported paths directly, so no RemotePathMappings are needed and
the Servarr health warning ("download client places downloads in ... but this
directory does not appear to exist") stays green; a single filesystem also
allows hardlink/atomic-rename imports. Read-write is required so Radarr can
hardlink/import. `/media` is unchanged.

### Sabnzbd download client (auto-seeded)

On every (re)start, after `config.xml` seeding, the entrypoint starts Radarr
in the background, polls `GET /api/v3/system/status` (up to ~120s), then
idempotently upserts a download client named `Sabnzbd`:

* Built from the `GET /api/v3/downloadclient/schema` template
  (`implementation == "Sabnzbd"`); matched by name for the existing id,
  `POST` (create) or `PUT /{id}` (update) with `?forceSave=true`.
* Connection: host `sabnzbd`, port `8080`, `useSsl=false`,
  `apiKey` from `SABNZBD_API_KEY`, empty username/password.
* `movieCategory` is deliberately left **blank** (not `movies`): this Radarr
  pin deserializes SABnzbd's categories with PascalCase key expectations
  (`Name`/`Dir`) while SABnzbd sends lowercase (`name`/`dir`), so no category
  can ever match and a non-blank `movieCategory` always fails validation with
  `Category does not exist` (verified empirically against 6.4.4.10685). A
  blank value falls through to SABnzbd's catch-all `*` category, which
  completes at the `complete_dir` root — exactly the layout SABnzbd seeds
  (its built-in `movies` category has `dir=""`). Re-check this against the
  docs when bumping the Radarr pin — a future release may fix the key casing
  and allow `movies` again.
* recent/older movie+TV priorities `-100`;
  `enable=true`, `protocol=usenet`, `priority=1`,
  `removeCompletedDownloads`/`removeFailedDownloads=true`.

`forceSave=true` skips connection validation so the seed never blocks startup
(e.g. when SABnzbd is not up yet); Radarr re-tests on use. Unlike
`config.xml`, this upsert runs on every start, so a rotated
`SABNZBD_API_KEY` converges on restart. To disable: delete the `Sabnzbd`
client in Settings > Download Clients — but it will be re-created on the
next restart; unset `SABNZBD_API_KEY` (compose will fail fast — by design,
so prefer deleting via UI only for temporary testing) or stop the container
to keep it gone.

### qBittorrent download client (auto-seeded)

On every (re)start, alongside the Sabnzbd seeder, the entrypoint idempotently
upserts a second download client named `QBittorrent` (only when
`RADARR_API_KEY` and `QBT_WEBUI_PASSWORD` are set):

* Built from the `GET /api/v3/downloadclient/schema` template
  (`implementation == "QBittorrent"`); matched by name for the existing id,
  `POST` (create) or `PUT /{id}` (update) with `?forceSave=true`.
* Connection: host `qbittorrent`, port `8085`, `useSsl=false`, username from
  `QBT_WEBUI_USERNAME`, password from `QBT_WEBUI_PASSWORD` (user/pass auth —
  qBittorrent has no API-key mode).
* Category `movies` (field `movieCategory`; qBittorrent auto-creates the
  category on first use); priorities left at template defaults;
  `enable=true`, `protocol=torrent`, `priority=2` (usenet stays preferred at
  `1`), `removeCompletedDownloads`/`removeFailedDownloads=true`, `tags=[]`.

`forceSave=true` skips connection validation so the seed never blocks startup
(e.g. when qBittorrent is not up yet); Radarr re-tests on use. Like the
Sabnzbd client, this upsert runs on every start, so a rotated
`QBT_WEBUI_PASSWORD` converges on restart. To disable: delete the
`QBittorrent` client in Settings > Download Clients — but it will be
re-created on the next restart; unset `QBT_WEBUI_PASSWORD` (compose will fail
fast — by design, so prefer deleting via UI only for temporary testing) or
stop the container to keep it gone.

### Prowlarr Application (auto-registered)

On every (re)start, alongside the download-client seeders (after Radarr is
confirmed up), the entrypoint registers Radarr as an Application inside
Prowlarr (only when `RADARR_API_KEY` and `PROWLARR_API_KEY` are set):

* Direction: Prowlarr pushes indexers into Radarr as Newznab/Torznab entries
  (this is Servarr's supported topology — Radarr has no native Prowlarr
  indexer implementation).
* Built from the `GET /api/v1/applications/schema` template
  (`implementation == "Radarr"`); matched by name (`Radarr`) for the existing
  id, `POST` (create) or `PUT /{id}` (update).
* Fields: `prowlarrUrl=http://prowlarr:9696`, `baseUrl=http://radarr:7878`,
  `apiKey` from `RADARR_API_KEY`, movie Newznab categories
  `[2000,2010,2020,2030,2040,2045,2050,2060,2070,2080]`,
  `syncLevel=fullSync`, `enable=true`, `tags=[]`. A best-effort
  `POST /api/v1/applications/sync` follows (failures ignored).

`fullSync` overwrites Radarr-side edits to synced indexers on the next sync —
make indexer changes in Prowlarr, not in Radarr. Like the download clients,
the upsert runs on every start, so a rotated key converges on restart. To
disable: delete the `Radarr` Application in Prowlarr Settings > Apps.

## Access paths

### Through nginx-proxy (UI + API)

nginx-proxy routes `radarr.<BASE_DOMAIN>` to the container. The UI is available
at `https://radarr.<BASE_DOMAIN>`; the API at
`https://radarr.<BASE_DOMAIN>/api/v3/<...>` with `X-Api-Key: <RADARR_API_KEY>`.

### Direct container-to-container (API)

Other containers on the same network reach Radarr at
`http://radarr:7878`, authenticated with the `X-Api-Key` header:

```sh
curl -H "X-Api-Key: $RADARR_API_KEY" http://radarr:7878/api/v3/system/status
```
