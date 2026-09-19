# SABnzbd (Alpine)

A minimal Alpine-based SABnzbd image for the `media-dl` compose project.

Alpine does not package SABnzbd (and cannot ship the non-free `unrar`), so the
image installs the official SABnzbd source release into a Python virtualenv and
copies `unrar` from the LinuxServer `unrar` build. The final image is pure
Alpine.

`par2cmdline-turbo` (the faster ParPar-based fork) is used for PAR2 repair. It
is not in the Alpine 3.24 stable repos, so it is installed from `edge/testing`
with the repo passed inline (never persisted in the image); the build arg
`PAR2_TURBO_VERSION` pins the version.

## Build

The image is built by `../docker-compose.yml`:

```sh
cd ..
# edit .env first (required by compose)
docker compose build sabnzbd
```

`SABNZBD_VERSION` is a required build arg (`Dockerfile` default: `5.1.3`).

## Runtime

| Item | Value |
| --- | --- |
| Port | `8080` (HTTP, exposed to the internal network only) |
| Config volume | `sabnzbd-config` → `/config` (holds `sabnzbd.ini`, logs, admin) |
| Data volume | `sabnzbd-data` → `/data` (incomplete + complete downloads, config/db backups) |
| Entrypoint | `/usr/local/bin/entrypoint.sh` (drops privileges, seeds config) |

The container does not publish ports to the host. It joins the external
`nginx-proxy` network and is reached through the existing `nginx-proxy` /
Let's Encrypt sidecar using `VIRTUAL_HOST`.

### Environment variables

| Variable | Purpose |
| --- | --- |
| `PUID` / `PGID` | UID/GID that files and the process run as (default `1000:1000`) |
| `TZ` | Container timezone |
| `VIRTUAL_HOST` | Public hostname routed by nginx-proxy, derived from `DOMAIN` in `.env` as `sabnzbd.<DOMAIN>` |
| `VIRTUAL_PORT` | Container port the proxy forwards to (`8080`) |
| `LETSENCRYPT_HOST` / `LETSENCRYPT_EMAIL` | Certificate request details |
| `SABNZBD_HOST` | Public hostname (`sabnzbd.<DOMAIN>`), seeded into `host_whitelist` on first run |
| `SABNZBD_HOST_WHITELIST` | Extra accepted Host headers (default `sabnzbd`), seeded into `host_whitelist` |
| `SABNZBD_API_KEY` | API key (access token), seeded into `api_key` and shared with other services |
| `SABNZBD_NZB_KEY` | NZB key for direct download links, seeded into `nzb_key` (optional) |

### Startup behaviour

On first start, if `/config/sabnzbd.ini` does not exist, the entrypoint writes a
minimal config:

```ini
[misc]
download_dir = /data/incomplete
complete_dir = /data/complete
backup_dir = /data/backup
host_whitelist = <SABNZBD_HOST>, <SABNZBD_HOST_WHITELIST>
api_key = <SABNZBD_API_KEY>
nzb_key = <SABNZBD_NZB_KEY>
```

The `host_whitelist` line is written only when at least one hostname is known;
with the defaults it becomes e.g. `sabnzbd.example.com, sabnzbd`. The `api_key`
and `nzb_key` lines are written only when set. Seeding the API key keeps it
stable across restarts and config reseeds, so subsequent containers can consume
it as `${SABNZBD_API_KEY}` instead of scraping the auto-generated value.

Incomplete and complete downloads share the `/data` volume so finished jobs can
be moved with an atomic rename and hardlinked. Existing configs are never
overwritten.

## Access paths

SABnzbd applies two independent gates to every request:

1. **Host check** (`check_hostname`) — the `Host` header must be localhost, an
   IP literal, `*.local`, or in `host_whitelist`.
2. **Local-IP check** (`check_access`) — with the default `inet_exposure = 0`,
   only requests whose client IP is loopback/private are allowed. When
   `verify_xff_header = 1` (5.x default) and the request carries
   `X-Forwarded-For`, every IP in that header must also be private/loopback.

Both required paths are configured for and verified against these gates:

### Through nginx-proxy (UI + REST API)

nginx-proxy forwards the public `Host` header and the real client IP in
`X-Forwarded-For`. The container whitelists `SABNZBD_HOST`, so the Host check
passes.

This project keeps SABnzbd's **local-network-only** posture:

* **LAN / VPN clients** — the forwarded client IP is private, so the local-IP
  check passes. UI and API work at `https://<SABNZBD_HOST>`.
* **Public-internet clients** — the forwarded client IP is public, so SABnzbd
  answers `403 External internet access denied` by design. This is intentional;
  see below to change it.

### Uploads through the proxy (413 Request Entity Too Large)

nginx's default `client_max_body_size` is `1m`, so larger NZB uploads are
rejected by the proxy with `413` before they reach SABnzbd (the UI then shows
"Failed to upload file"). Add a per-vhost override in the nginx-proxy project:

```ini
# nginx-proxy/vhost.d/sabnzbd.localhost
client_max_body_size 100m;
```

and mount that directory in the nginx-proxy compose:

```yaml
volumes:
  - ./vhost.d:/etc/nginx/vhost.d:ro
```

### Direct container-to-container (REST API)

Other containers on the same network reach SABnzbd at `http://sabnzbd:8080`.
They send `Host: sabnzbd:8080`, which is not a loopback/IP/`.local` name, so the
service name `sabnzbd` is whitelisted by default via `SABNZBD_HOST_WHITELIST`.
Their source IP is private, so the local-IP check passes. API calls still need
the SABnzbd API key.

If you rename the compose service or reach it under another name, add that
name to `SABNZBD_HOST_WHITELIST` (comma-separated). Using the container IP
(`http://<ip>:8080`) also works because IP literals always pass the Host check.

### Allowing public-internet access (optional)

If you later want the proxy to serve public clients, choose one and document the
trade-off:

* **With login (official/recommended):** set `username` and `password` in
  `Config > General` and `inet_exposure = 5`. External UI then requires a login
  while the API key continues to work. Note that setting credentials also
  disables the Host check.
* **Without login (not recommended):** set `verify_xff_header = 0`, which makes
  SABnzbd trust nginx-proxy's IP instead of inspecting `X-Forwarded-For`. Anyone
  who can reach the proxy gets full access.

For LAN-only setups none of this is needed.

## Hostname verification (and reverse proxies)

SABnzbd runs an anti-DNS-rebinding check. Every request's `Host` header must be
one of:

* `localhost`, an IPv4/IPv6 literal, or a `*.local` name, **or**
* a hostname listed in `[misc] host_whitelist`, **or**
* any request at all when both `username` and `password` are set.

Behind nginx-proxy the browser sends the public hostname (for example
`sabnzbd.example.com`), which is none of the first group, so SABnzbd answers
`403 Access denied - Hostname verification failed` until it is whitelisted.

### Answers to the common questions

**Can the hostname be set in `sabnzbd.ini`?**
Yes. The setting is:

```ini
[misc]
host_whitelist = sabnzbd.example.com
```

Multiple hosts are comma-separated:

```ini
host_whitelist = sabnzbd.example.com, sab.example.org
```

Values are lower-cased. There are **no wildcards** — `*.example.com` and `*` are
treated as literal strings and do not match. The container seeds this from
`SABNZBD_HOST` plus `SABNZBD_HOST_WHITELIST` on first run (see above). `host` /
`port` (or `--server`) only control which interface SABnzbd binds to; they do
not affect the Host check.

**Can hostname verification be disabled altogether?**
There is no supported switch, and `host_whitelist = *` does not work. The
supported options are:

1. **Whitelist the proxy hostname** (recommended) — set `host_whitelist` as
   above. This is what the container does automatically.
2. **Require authentication** — setting `username` and `password` in
   `Config > General` short-circuits the check and allows any `Host`. Only do
   this if you actually want HTTP auth.
3. **Access by IP or `localhost`** — always allowed, which is why the container
   healthcheck works.

`api_warnings = 0` only suppresses the warning text; the request is still
refused.

### Changing it on an existing install

The entrypoint only seeds a new config, so if you already have a
`sabnzbd.ini` you must add the hostnames yourself:

* **GUI:** `Config > Special > Host whitelist` — add the public hostname **and**
  `sabnzbd` (for container-to-container access).
* **File:** edit `/config/sabnzbd.ini` (in the `sabnzbd-config` volume) and add
  the `host_whitelist` line under `[misc]`, then restart the container. Example:

  ```ini
  host_whitelist = sabnzbd.example.com, sabnzbd
  ```

## Configuration reference

`sabnzbd.ini.example` in this directory is a complete, commented reference of
the SABnzbd 5.x configuration (every `[misc]` option, logging, notification
agents, and example `[servers]` / `[categories]` / `[rss]` / `[sorters]`
sections). It is documentation only — it is neither copied into the image nor
read at runtime. Use the GUI (`Config`) for day-to-day changes; SABnzbd rewrites
the real `/config/sabnzbd.ini` itself.
