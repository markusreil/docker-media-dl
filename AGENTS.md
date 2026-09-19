# AGENTS.md

Guidance for agents working in this repository. Read this before making changes;
it captures the project requirements and the non-obvious design decisions that
are easy to break accidentally.

## Project

`media-dl` is a collection of Docker containers for media download, archival and
playback, deployed as a single `docker compose` project named `media-dl`.

Core requirements (from the original spec):

* Single compose file for all containers.
* One compose project, cluster name `media-dl`.
* Integrates with an existing external nginx-proxy (reverse proxy + Let's
  Encrypt companion) on a shared docker network.
* ALL configuration lives in `.env`; compose must fail fast if a required
  variable is missing or empty.
* Base image for every container is Alpine; extra build steps per container are
  acceptable.
* Standard docker volumes so container configuration survives restarts and
  rebuilds.

Services:

| Service | Role | Public hostname | Internal port |
| --- | --- | --- | --- |
| `sabnzbd` | Usenet downloader | `sabnzbd.<DOMAIN>` | 8080 |
| `prowlarr` | Indexer manager | `prowlarr.<DOMAIN>` | 9696 |

## Layout

```
docker-compose.yml     single compose file (services, hosts, networks, volumes)
.env                   all configuration (secrets) — tracked in git
.env.example           template; copy to .env first
sabnzbd/               Alpine SABnzbd image: Dockerfile, entrypoint.sh, README
prowlarr/              Alpine Prowlarr image: Dockerfile, entrypoint.sh, README
```

Each service directory has a README with build details, environment variables,
and the reasoning behind security choices. Keep those in sync when behavior
changes.

To scaffold a NEW compose project from scratch, follow
[`COMPOSE.md`](COMPOSE.md) — the generic recipe this repo was built from.

## Build / run / verify

```sh
cp .env.example .env   # then edit .env
docker compose config  # sanity check; fails fast on missing vars
docker compose build
docker compose up -d
docker compose ps
```

To update a service after bumping its version variable in `.env`:

```sh
docker compose build sabnzbd prowlarr
docker compose up -d
```

There is no test suite; verification is `docker compose config` (checks
variable interpolation) plus building images and checking the containers start
and serve their UIs.

## Conventions and invariants (do not break)

* **Variable interpolation is the validation mechanism.** Every required
  `.env` var is referenced with `${VAR:?...}` in `docker-compose.yml` so
  compose errors out on missing/empty values. Never replace these with silent
  defaults for required config (secrets, versions, domain, proxy network).
* **Hostnames are anchored once.** `x-hosts` at the top of
  `docker-compose.yml` defines `sabnzbd.${DOMAIN}` and `prowlarr.${DOMAIN}`;
  both services reference the anchors via `*sabnzbd-host` / `*prowlarr-host`
  for `VIRTUAL_HOST`, `LETSENCRYPT_HOST`, and app-level hostname env vars.
  Changing `DOMAIN` in `.env` moves the whole stack. Keep adding new services
  on the same pattern.
* **Services attach to an external network**, `nginx-proxy` (name from
  `NGINX_PROXY_NETWORK`), and publish only via `expose` — no host ports.
* **Both images are built from source in this repo** on Alpine. No
  LinuxServer/third-party images; that is a deliberate spec choice.
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
* **`.env` is tracked in git** in this repo. Do not "help" by gitignoring it
  or by committing secrets elsewhere.

## SABnzbd specifics (`sabnzbd/`)

* No env-var override exists for SABnzbd's folders, so the entrypoint seeds
  `download_dir` (incomplete) and `complete_dir` (complete) into `sabnzbd.ini`.
  Incomplete and complete share the `/data` volume so finished jobs move via
  atomic rename/hardlink; a dedicated `backup_dir` keeps backups out of
  `complete`.
* **DNS-rebinding protection**: SABnzbd rejects requests whose `Host` header is
  not localhost, an IP, `*.local`, or in `host_whitelist`. Two paths must pass:
  the public hostname forwarded by nginx-proxy (`SABNZBD_HOST`, seeded) and the
  internal `http://sabnzbd:8080` name used by other containers
  (`SABNZBD_HOST_WHITELIST`, defaults to `sabnzbd`).
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

## Testing / review checklist

Before finishing a change:

1. `docker compose config` passes with a fresh `.env` copy.
2. Variable interpolation still fails fast on missing vars (no silent
   defaults for required ones).
3. New/changed env vars are documented in `.env.example`, `README.md`, and the
   service README.
4. Seeding logic only runs on first start; existing configs are untouched.
5. `PUID`/`PGID` chown behavior is preserved (no recursive chown on `/data`).