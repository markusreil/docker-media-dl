# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `GEN_SELF_SIGNED_CERT` opt-in on every proxied service, wired from a new
  optional per-service `.env` variable (`JELLYFIN_GEN_SELF_SIGNED_CERT`,
  `PROWLARR_GEN_SELF_SIGNED_CERT`, `RADARR_GEN_SELF_SIGNED_CERT`,
  `SONARR_GEN_SELF_SIGNED_CERT`, `QBITTORRENT_GEN_SELF_SIGNED_CERT`,
  `SABNZBD_GEN_SELF_SIGNED_CERT`; default `false`) so the proxy variant decides
  between the ACME and self-signed certificate paths.
- `CHANGELOG.md` following [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
- `COMPOSE_FILE` in `.env` / `env.example`, defaulting to the base
  `docker-compose.yml`. Listing the optional archived-library overlay there
  registers it for every compose command, replacing per-command `-f` flags.
- Optional `docker-compose.hwaccel.yml` overlay enabling Jellyfin hardware
  transcoding: passes the host DRM nodes (`/dev/dri/renderD128` for VA-API,
  `/dev/dri/card0` for DRM/Vulkan interop) to `jellyfin` only, registered via
  `COMPOSE_FILE`.
- `JELLYFIN_VIDEO_GID` / `JELLYFIN_RENDER_GID` `.env` variables (host GPU
  group GIDs), required only when the hwaccel overlay is registered.
- Jellyfin entrypoint GPU-group mapping: maps the host GIDs into the
  container's `/etc/group` and adds the `jellyfin` user to them, so the
  unprivileged process can open group-restricted DRM nodes.

### Changed

- Jellyfin entrypoint now execs `gosu jellyfin` (username form) instead of
  `gosu "$PUID:$PGID"`, so the mapped `/etc/group` supplementary groups
  survive the privilege drop (`group_add` is ineffective through `gosu`).

- Proxy contract: replaced the deprecated `LETSENCRYPT_HOST` with the `ACME_HOST`
  spelling on all services (spec-mandated `ACME_*` naming); every service now
  declares its complete, variant-agnostic contract (`VIRTUAL_HOST`,
  `VIRTUAL_PORT`, `ACME_HOST`, `GEN_SELF_SIGNED_CERT`).
- Jellyfin now uses the full TLS contract like the other services and is no
  longer pinned to an HTTP-only variant.
- `NGINX_PROXY_NETWORK` now defaults to `web-proxy` instead of failing fast when
  unset (matches the COMPOSE spec default; still overridable in `.env`).
- Homepage `homepage.href` anchors now use `https://`.
- README, `AGENTS.md`, `env.example`, and the service READMEs synced to the new
  proxy contract.
- Archived-library overlay documented as registered via `COMPOSE_FILE` in
  `.env` instead of per-command `-f` flags.

### Deprecated

### Removed

- `JELLYFIN_HTTPS_METHOD` and Jellyfin's per-vhost `HTTPS_METHOD` override; TLS
  behaviour is cluster policy supplied by the proxy.

### Fixed

### Security
