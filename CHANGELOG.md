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

### Changed

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

### Deprecated

### Removed

- `JELLYFIN_HTTPS_METHOD` and Jellyfin's per-vhost `HTTPS_METHOD` override; TLS
  behaviour is cluster policy supplied by the proxy.

### Fixed

### Security
