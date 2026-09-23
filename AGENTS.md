# AGENTS.md

Guidance for agents working in this repository. Read this before making changes;
it captures the project requirements and the non-obvious design decisions that
are easy to break accidentally.

## Project

`media-dl` is a collection of Docker containers for media download, archival and
playback, deployed as a single `docker compose` project named `media-dl`.

Core requirements (from the original spec):

* Single compose file for all containers (one documented exception:
  `docker-compose.media-archived.yml`, an optional overlay that adds the
  archived-library volume/mounts — compose has no conditional mounts, so
  optionality needs a second file, registered by adding it to `COMPOSE_FILE`
  in `.env`).
* One compose project, cluster name `media-dl`.
* Integrates with an existing external nginx-proxy (reverse proxy + ACME
  companion) on a shared docker network.
* ALL configuration lives in `.env` (hidden, gitignored, copied via
  `cp env.example .env`); the tracked template is `env.example`. Compose must
  fail fast if a required variable is missing or empty.
* Base image for every container is Alpine; extra build steps per container are
  acceptable.
* Standard docker volumes so container configuration survives restarts and
  rebuilds.

Services:

| Service | Role | Public hostname | Internal port |
| --- | --- | --- | --- |
| `sabnzbd` | Usenet downloader | `sabnzbd.<BASE_DOMAIN>` | 8080 |
| `prowlarr` | Indexer manager | `prowlarr.<BASE_DOMAIN>` | 9696 |
| `radarr` | Movie manager | `radarr.<BASE_DOMAIN>` | 7878 |
| `sonarr` | TV series manager | `sonarr.<BASE_DOMAIN>` | 8989 |
| `qbittorrent` | BitTorrent client | `qbittorrent.<BASE_DOMAIN>` | 8085 |
| `jellyfin` | Media server | `jellyfin.<BASE_DOMAIN>` | 8096 |

## Build / run / verify

```sh
# edit .env first (copied via `cp env.example .env`; defaults and comments live in env.example)
docker compose config  # sanity check; fails fast on missing vars
docker compose build
docker compose up -d
docker compose ps
```

To update a service after bumping its version variable in `.env`:

```sh
docker compose build sabnzbd prowlarr qbittorrent
docker compose up -d
```

There is no test suite; verification is `docker compose config` (checks
variable interpolation) plus building images and checking the containers start
and serve their UIs.

## Conventions and invariants (do not break)

* **Variable interpolation is the validation mechanism.** Every required
  `.env` var is referenced with `${VAR:?...}` in `docker-compose.yml` so
  compose errors out on missing/empty values. Never replace these with silent
  defaults for required config (secrets, versions, domain). `NGINX_PROXY_NETWORK`
  is the one optional exception: it has the spec default `web-proxy`
  (`${NGINX_PROXY_NETWORK:-web-proxy}`).
* **Hostnames are anchored once.** `x-hosts` at the top of
  `docker-compose.yml` defines `<service>.${BASE_DOMAIN}` for every service;
  services reference the anchors via `*sabnzbd-host` / `*prowlarr-host` /
  `*radarr-host` / `*sonarr-host` / `*qbittorrent-host` / `*jellyfin-host`
  for `VIRTUAL_HOST`, `ACME_HOST`, and app-level hostname env vars; the
  derived `*-href` URL anchors feed the Homepage dashboard labels
  (`homepage.href`). Changing `BASE_DOMAIN` in `.env` moves the whole stack. Keep
  adding new services on the same pattern.
* **Complete downstream proxy contract, variant-agnostic.** Every proxied
  service declares `VIRTUAL_HOST`, `VIRTUAL_PORT`, `ACME_HOST`, and
  `GEN_SELF_SIGNED_CERT` (wired from `<SERVICE>_GEN_SELF_SIGNED_CERT`, default
  `false`). The proxy variant decides which TLS opt-in applies (internet-facing
  honours `ACME_HOST`; LAN/self-signed honours `GEN_SELF_SIGNED_CERT`); the
  service must not know or care. Never use the deprecated `LETSENCRYPT_*`
  spellings (use `ACME_*`; the sole exception is `LETSENCRYPT_TEST` for the
  staging CA) and never set `HTTPS_METHOD` — TLS behaviour is cluster policy.
* **Services attach to an external network**, `nginx-proxy` (name from
  `NGINX_PROXY_NETWORK`), and publish only via `expose` — no host ports. The
  single exception is qbittorrent, which publishes the bittorrent peer port
  (`QBT_BT_PORT`, default 6881, TCP+UDP) to the host for inbound connections;
  that is the stack's only host-port exception.
* **Images are built from source in this repo** on Alpine (Radarr/Sonarr from
  the official musl builds, SABnzbd from source tarball); qBittorrent is
  installed from the Alpine community package `qbittorrent-nox`. No
  LinuxServer/third-party images; that is a deliberate spec choice. One
  documented exception: Jellyfin builds `FROM` the official
  `jellyfin/jellyfin` image (see `jellyfin/README.md`).
* **Entrypoints are write-once config seeders.** Each `entrypoint.sh` seeds a
  minimal config on FIRST start only (`if [ ! -f ... ]`), and never overwrites
  an existing one. Config changes in the entrypoint do not apply to existing
  volumes — reseeding requires removing the service and its volume:
  `docker compose rm -sf <svc>` + `docker volume rm media-dl_<svc>-config`,
  then `up -d`.
* **`PUID`/`PGID` privilege drop.** Entrypoints run as root, create
  user/group with the requested IDs, `chown` correctly, then `su-exec` to the
  unprivileged user. Config dirs are chowned recursively (small); data dirs
  only at the root (potentially huge — new files inherit ownership from the
  running user).
* **`env.example` is the tracked template; `.env` is hidden/ignored.**
  Do not gitignore `env.example`, do not track `.env`.
* **Changelog discipline.** `CHANGELOG.md` follows
  [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); add entries under
  `## [Unreleased]` as changes are made (never batch them). Do not create
  release sections on your own — only when the user asks for a release.
* **`restart: unless-stopped` by default**, and every service carries Homepage
  labels (`homepage.group` / `name` / `icon` / `href` / `description`) so the
  dashboard card renders. See `README.md` and the service READMEs for detail.
* **Shared media volume.** `MEDIA_VOLUME` switches `/media` between
  `media-local` (regular volume, default) and `media-nfs` (NFS mount);
  Jellyfin mounts it read-only (`:ro`), Radarr/Sonarr read-write
  (imports/renames). A second NFS export on the same host,
  `media-archived-nfs` (`:${MEDIA_ARCHIVED_NFS_PATH}`, reusing
  `MEDIA_NFS_HOST`/`MEDIA_NFS_VERS`), is mounted read-only (`:ro`) at
  `/media-archived` in Jellyfin, Radarr and Sonarr — but ONLY via the
  optional `docker-compose.media-archived.yml` overlay (compose cannot
  conditionally omit mounts, so the archive is opt-in per deployment, not
  part of the base file; register it by adding the file to `COMPOSE_FILE` in
  `.env` — no `-f` flags). The archive is served/scanned, never written to. The `/media` + `/media-archived` mount
  strings are anchored once in `x-media` (`*media-ro` / `*media-rw` /
  `*media-archived-ro`) so the `MEDIA_VOLUME` switch lives in one place.
* **Shared downloads volume.** One top-level `downloads` volume is mounted at
  identical `/data` paths in sabnzbd, qbittorrent, radarr, AND sonarr
  (radarr/sonarr read-write — they hardlink/import; `/media` unchanged).
  SABnzbd uses
  `/data/usenet/{incomplete,complete,backup}`, qBittorrent uses
  `/data/torrents/{incomplete,complete}`; per-client subdirs avoid the
  sabnzbd/torrent `/data/complete` name clash. Identical paths let Radarr see
  the exact downloader paths (no RemotePathMappings, Servarr "directory does
  not appear to exist" health check stays green) and keep hardlinks on one
  filesystem. Migration: reseed sabnzbd/qbittorrent configs (write-once
  seeders); old `sabnzbd-data`/`qbittorrent-data` volumes become orphans.

## SABnzbd specifics (`sabnzbd/`)

* No env-var override exists for SABnzbd's folders, so the entrypoint seeds
  `download_dir` (`/data/usenet/incomplete`), `complete_dir`
  (`/data/usenet/complete`), and `backup_dir` (`/data/usenet/backup`) into
  `sabnzbd.ini`. Incomplete and complete share the `/data/usenet` subdir of the
  shared `downloads` volume so finished jobs move via
  atomic rename/hardlink; a dedicated `backup_dir` keeps backups out of
  `complete`.
* **DNS-rebinding protection**: SABnzbd rejects requests whose `Host` header is
  not localhost, an IP, `*.local`, or in `host_whitelist`. Two paths must pass:
  the public hostname forwarded by nginx-proxy (`SABNZBD_HOST`) and the
  internal `http://sabnzbd:8080` name used by other containers. The entrypoint
  seeds `host_whitelist` from `SABNZBD_HOST` merged with the hardcoded
  `SABNZBD_HOST_WHITELIST` in compose (`sabnzbd, sabnzbd.<BASE_DOMAIN>`),
  de-duplicated so the public hostname appears once.
* `SABNZBD_API_KEY` / `SABNZBD_NZB_KEY` are seeded when provided so downstream
  containers share stable credentials.
* LAN-only posture: SABnzbd rejects non-private client IPs with 403 by design;
  do not add auth that fights the reverse-proxy setup.

## Prowlarr specifics (`prowlarr/`)

* The API key has no env/CLI override, so it is seeded into `config.xml`
  (always `Port 9696`).
* `AllowedHosts = *` disables the Host-header check so any forwarded hostname
  is accepted (no per-domain config).
* `AuthenticationMethod = External` — this is the supported "proxy-delegated"
  no-login mode and is intentional for the LAN-only posture:
  * `None` is deprecated/invalid in Servarr 2.x.
  * Prowlarr deliberately ignores the local-address bypass when an
    `X-Forwarded-For` header is present (anti-spoofing), so
    `DisabledForLocalAddresses` alone would force logins behind nginx-proxy.
  * The REST API is still protected by the API key; use Forms auth if the
    proxy is ever exposed beyond the LAN.
* `AuthenticationRequired = DisabledForLocalAddresses` — NOT `Disabled`.
  Verifiied empirically: `Disabled` must be Disabled and crashes Prowlarr
  2.6.5 with a DryIoc `InvalidCastException` (500 on every request).
* If changing these values, confirm behavior against the actual Prowlarr
  release used, not docs alone.

## qBittorrent specifics (`qbittorrent/`)

* No env-var/CLI override exists for WebUI credentials, so the entrypoint seeds
  `WebUI\Username` and `WebUI\Password_PBKDF2` into
  `config/qBittorrent/config/qBittorrent.conf` (config lives under the
  `config/` subdir of the profile dir — verified empirically on 5.2.1).
* `WebUI\Password_PBKDF2` format = `"@ByteArray(<b64salt>:<b64hash>)"` with
  PBKDF2-HMAC-SHA512 (16-byte salt, 100000 iterations, 64-byte key), generated
  in the entrypoint with python3; matches what qBittorrent itself writes.
* INI keys use single backslashes (`WebUI\Port`); double backslashes break key
  matching (QSettings) — do not "fix" the escaping.
* qBittorrent has NO anonymous/no-login mode (unlike SABnzbd/Prowlarr) — by
  default login is always required; the stack uses seeded `QBT_WEBUI_USERNAME` /
  `QBT_WEBUI_PASSWORD`. The one deliberate exception is `QBT_AUTH_SUBNET_WHITELIST`
  (CIDR list, default empty): when set, the entrypoint seeds
  `WebUI\AuthSubnetWhitelistEnabled=true` so clients from those subnets skip
  login. It is checked against the socket peer IP (not `X-Forwarded-For`), so
  only genuinely on-subnet clients are affected; set it to the `NGINX_PROXY_NETWORK`
  subnet to open the WebUI behind the proxy.
* `WebUI\HostHeaderValidation=true` stays on; `WebUI\ServerDomains` is seeded
  with the public hostname merged with the hardcoded `QBT_HOST_WHITELIST` in
  compose (`qbittorrent;qbittorrent.<BASE_DOMAIN>`), de-duplicated
  (SABnzbd-style anti-DNS-rebinding).
* `WebUI\Port=8085` (internal), `BitTorrent\Session\Port=6881` (fixed internal
  peer port); host peer port `QBT_BT_PORT` is published as
  `${QBT_BT_PORT}:6881` — `QBT_BT_PORT` is only the host-side port, the
  container always listens on 6881.
* Healthcheck `GET /` returns 200 unauthenticated.
* Write-once seeding, same reseed procedure as the other services.

## Testing / review checklist

Before finishing a change:

1. `docker compose config` passes with a fresh `.env` copy.
2. Variable interpolation still fails fast on missing vars (no silent
   defaults for required ones).
3. New/changed env vars are documented in `env.example` (with defaults and comments)
   and in `README.md` / the service README. There is no `.env.example` to
   update.
4. Seeding logic only runs on first start; existing configs are untouched.
5. `PUID`/`PGID` chown behavior is preserved (no recursive chown on `/data`).