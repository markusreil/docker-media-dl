#!/usr/bin/env python3
"""Bulk-import existing on-disk movie folders into Radarr.

This helper scans a folder that lives under a configured Radarr root folder,
resolves each top-level movie folder to a TMDB movie via Radarr's
``/api/v3/movie/lookup`` endpoint, adds the movie (honouring the existing
on-disk path) and finally triggers a ManualImport command so the existing
files are attached to the library entry.

Radarr's metadata backend (Skyhook / ``api.radarr.video``) is known to stall
intermittently.  Every HTTP request therefore goes through a small retry layer
with exponential backoff + jitter.  Folders that cannot be resolved because the
backend is down are recorded as ``unresolved`` and retried cleanly on the next
run (the state file only marks *successful* folders as done).

The script is dry-run by default: it performs all discovery/lookup GETs and
prints the exact payloads it *would* send, but makes zero state-changing POSTs
and writes no state file.  Pass ``--apply`` to actually mutate the library.

TLS: verification is on by default.  Because the real target uses a self-signed
certificate, the first certificate-verification failure triggers a one-time
fallback to an unverified context (with a warning) so a self-signed host works
out of the box.  Use ``--cafile PATH`` to trust the certificate while keeping
verification (and hostname checks) enabled, ``--strict-ssl`` to disable the
fallback entirely, or ``--insecure``/``--no-verify`` to skip verification
up front.  ``--insecure`` and ``--cafile`` are mutually exclusive.  Plain
``http://`` URLs are unaffected.

Only the Python 3 standard library is used.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

DEFAULT_URL = "https://radarr.media-dl.max.home.arpa"
DEFAULT_STATE = "scripts/.radarr-library-import.state.json"
DEFAULT_REPORT = "scripts/.radarr-library-import-report.json"
DEFAULT_SCAN_FOLDER = "/media/movies"

API_PREFIX = "/api/v3"
TERMINAL_COMMAND_STATES = {"completed", "failed", "aborted", "cancelled"}
SUCCESS_STATES = {"imported"}
OUTCOME_ORDER = [
    "imported",
    "added-but-no-file",
    "already-in-library",
    "unresolved",
    "error",
    "would-import",
]

# "Movie Folder (Year)" -- title is non-greedy, year is the last (YYYY) group.
FOLDER_RE = re.compile(r"^(?P<title>.+?)\s*\((?P<year>\d{4})\)$")


# --------------------------------------------------------------------------- #
# Errors / logging
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    """Non-retryable API / configuration error."""


class RetryExhausted(ApiError):
    """Raised when a retryable request failed on every attempt."""


class InvalidJson(Exception):
    """Response body was empty, truncated or not valid JSON (retryable)."""


class Log:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose

    @staticmethod
    def _ts() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def info(self, msg: str) -> None:
        print(f"[{self._ts()}] {msg}", file=sys.stderr)

    def debug(self, msg: str) -> None:
        if self.verbose:
            print(f"[{self._ts()}] {msg}", file=sys.stderr)

    def out(self, msg: str = "") -> None:
        print(msg)


# --------------------------------------------------------------------------- #
# HTTP layer with retry / backoff / throttle
# --------------------------------------------------------------------------- #
def _short(url: str, limit: int = 160) -> str:
    url = url.split("://", 1)[-1]
    return url if len(url) <= limit else url[: limit - 3] + "..."


class HttpClient:
    """Tiny urllib wrapper with retries, backoff, jitter and throttling."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float,
        max_retries: int,
        min_interval: float,
        insecure: bool,
        log: Log,
        cafile: str | None = None,
        strict_ssl: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.min_interval = max(0.0, min_interval)
        self.log = log
        self.insecure = insecure
        self.cafile = cafile
        self.strict_ssl = strict_ssl
        self.host = urllib.parse.urlsplit(self.base_url).hostname or self.base_url
        self._downgraded = False
        self.opener = self._build_opener()
        self._last_request = 0.0

    def _build_opener(self, force_insecure: bool = False):
        """Build an opener that always has an explicit TLS context installed.

        ``force_insecure`` is used by the automatic self-signed fallback; the
        ``insecure`` constructor flag always wins over ``cafile``/defaults.
        """
        if self.insecure or force_insecure:
            context = ssl._create_unverified_context()
        elif self.cafile:
            if not os.path.isfile(self.cafile):
                raise ApiError(f"--cafile file not found: {self.cafile}")
            context = ssl.create_default_context(cafile=self.cafile)
        else:
            context = ssl.create_default_context()
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=context))

    @staticmethod
    def _is_cert_error(exc: urllib.error.URLError) -> bool:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError):
            return True
        if isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason):
            return True
        text = str(reason)
        return "CERTIFICATE_VERIFY_FAILED" in text or "certificate verify failed" in text

    def _cert_error_message(self, exc: urllib.error.URLError) -> str:
        return (
            f"TLS certificate verification failed for {self.host}: {exc.reason}. "
            "Use --cafile <path> to trust the certificate, or --insecure to "
            "disable verification."
        )

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            self._last_request = time.monotonic()
            return
        delta = time.monotonic() - self._last_request
        if delta < self.min_interval:
            time.sleep(self.min_interval - delta)
        self._last_request = time.monotonic()

    def request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        body: dict | None = None,
    ):
        url = self.base_url + path
        if params:
            sep = "&" if "?" in url else "?"
            url = url + sep + urllib.parse.urlencode(params)

        data = None
        headers = {"X-Api-Key": self.api_key, "Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_error: Exception | None = None
        reason = ""
        attempt = 1
        while attempt <= self.max_retries:
            self._throttle()
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            started = time.monotonic()
            retryable = False
            reason = ""
            code = None
            try:
                with self.opener.open(req, timeout=self.timeout) as resp:
                    raw = resp.read()
                    code = resp.getcode()
                elapsed = time.monotonic() - started
                try:
                    parsed = json.loads(raw.decode("utf-8")) if raw else None
                except (ValueError, UnicodeDecodeError) as exc:
                    raise InvalidJson(f"invalid/truncated JSON ({len(raw)} bytes): {exc}") from None
                self.log.debug(
                    f"    attempt {attempt}/{self.max_retries}: {method} {_short(url)} "
                    f"-> HTTP {code} in {elapsed:.1f}s"
                )
                return parsed
            except urllib.error.HTTPError as exc:
                elapsed = time.monotonic() - started
                code = exc.code
                try:
                    err_body = exc.read().decode("utf-8", "replace")
                except Exception:  # pragma: no cover - defensive
                    err_body = ""
                retryable = code == 429 or 500 <= code < 600
                reason = f"HTTP {code}"
                last_error = ApiError(f"HTTP {code} for {method} {path}: {err_body[:300].strip()}")
                self.log.info(
                    f"attempt {attempt}/{self.max_retries}: {method} {_short(url)} "
                    f"-> HTTP {code} in {elapsed:.1f}s"
                    + ("" if retryable else " (non-retryable)")
                )
                if not retryable:
                    raise last_error from None
            except (socket.timeout, TimeoutError) as exc:
                elapsed = time.monotonic() - started
                retryable = True
                last_error = ApiError(f"timeout after {elapsed:.1f}s for {method} {path}")
                self.log.info(
                    f"attempt {attempt}/{self.max_retries}: {method} {_short(url)} "
                    f"-> timeout after {elapsed:.1f}s"
                )
            except urllib.error.URLError as exc:
                elapsed = time.monotonic() - started
                if not self.insecure and self._is_cert_error(exc):
                    if self.strict_ssl or self.cafile:
                        raise ApiError(self._cert_error_message(exc)) from None
                    if self._downgraded:
                        raise ApiError(self._cert_error_message(exc)) from None
                    self.log.info(
                        "warning: TLS certificate verification failed; accepting "
                        "self-signed certificate (retrying with verification disabled). "
                        "Use --cafile <path> to trust it, or --strict-ssl to disable "
                        "this fallback."
                    )
                    self.opener = self._build_opener(force_insecure=True)
                    self._downgraded = True
                    # The downgrade is not a normal retry: do not consume an attempt.
                    continue
                retryable = True
                last_error = ApiError(f"connection error for {method} {path}: {exc.reason}")
                self.log.info(
                    f"attempt {attempt}/{self.max_retries}: {method} {_short(url)} "
                    f"-> connection error ({exc.reason}) after {elapsed:.1f}s"
                )
            except (InvalidJson, OSError) as exc:
                elapsed = time.monotonic() - started
                retryable = True
                last_error = ApiError(f"{exc} for {method} {path}")
                self.log.info(
                    f"attempt {attempt}/{self.max_retries}: {method} {_short(url)} "
                    f"-> {exc} after {elapsed:.1f}s"
                )

            if retryable and attempt < self.max_retries:
                delay = min(60.0, float(2 ** (attempt - 1))) + random.uniform(0.0, 1.0)
                self.log.info(f"    retrying in {delay:.1f}s ...")
                time.sleep(delay)
            attempt += 1

        raise RetryExhausted(
            f"giving up after {self.max_retries} attempts ({reason or 'last error'}) "
            f"for {method} {path}: {last_error}"
        )


# --------------------------------------------------------------------------- #
# Radarr API wrapper
# --------------------------------------------------------------------------- #
class Radarr:
    def __init__(self, http: HttpClient, log: Log) -> None:
        self.http = http
        self.log = log

    def status(self):
        return self.http.request("GET", f"{API_PREFIX}/system/status")

    def quality_profiles(self):
        return self.http.request("GET", f"{API_PREFIX}/qualityprofile")

    def root_folders(self):
        return self.http.request("GET", f"{API_PREFIX}/rootfolder")

    def movies(self):
        return self.http.request("GET", f"{API_PREFIX}/movie")

    def manual_import(self, folder: str):
        return self.http.request(
            "GET",
            f"{API_PREFIX}/manualimport",
            params={"folder": folder, "filterExistingFiles": "true"},
        )

    def lookup(self, term: str):
        return self.http.request("GET", f"{API_PREFIX}/movie/lookup", params={"term": term})

    def add_movie(self, payload: dict):
        return self.http.request("POST", f"{API_PREFIX}/movie", body=payload)

    def start_manual_import(self, files: list, mode: str):
        return self.http.request(
            "POST",
            f"{API_PREFIX}/command",
            body={"name": "ManualImport", "files": files, "importMode": mode},
        )

    def command(self, command_id):
        return self.http.request("GET", f"{API_PREFIX}/command/{command_id}")

    def poll_command(self, command_id, deadline_secs: float, log: Log) -> dict:
        started = time.monotonic()
        delay = 1.0
        while True:
            cmd = self.command(command_id) or {}
            status = cmd.get("status")
            if status in TERMINAL_COMMAND_STATES:
                return cmd
            if time.monotonic() - started > deadline_secs:
                raise ApiError(
                    f"command {command_id} did not reach a terminal state within "
                    f"{deadline_secs:.0f}s (status={status})"
                )
            log.debug(f"    command {command_id} status={status}; polling again")
            time.sleep(min(delay, 5.0))
            delay = min(delay * 1.5, 5.0)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def parse_folder_name(name: str):
    match = FOLDER_RE.match(name.strip())
    if not match:
        return None, None
    return match.group("title").strip(), int(match.group("year"))


def choose_lookup(results: list, year):
    candidates = [r for r in results if r.get("tmdbId") is not None]
    if not candidates:
        candidates = list(results)
    if not candidates:
        return None
    if year is not None:
        exact = [r for r in candidates if r.get("year") == year]
        if exact:
            return exact[0]
    return candidates[0]


def build_add_payload(best: dict, quality_profile_id: int, root_folder: str,
                      path: str, monitored: bool) -> dict:
    year = best.get("year")
    return {
        "tmdbId": int(best["tmdbId"]),
        "title": best.get("title") or "",
        "year": int(year) if year is not None else 0,
        "qualityProfileId": int(quality_profile_id),
        "rootFolderPath": root_folder,
        "path": path,
        "monitored": bool(monitored),
        "minimumAvailability": best.get("minimumAvailability") or "released",
        "addOptions": {"searchForMovie": False},
    }


def build_manual_import_files(items: list, folder_name: str, movie_id) -> list:
    files = []
    for item in items:
        entry = {
            "path": item.get("path"),
            "folderName": item.get("folderName") or folder_name,
            "movieId": movie_id,
            "quality": item.get("quality"),
            "languages": item.get("languages"),
            "indexerFlags": item.get("indexerFlags", 0),
        }
        if item.get("releaseGroup") is not None:
            entry["releaseGroup"] = item["releaseGroup"]
        files.append(entry)
    return files


def chunked(seq: list, size: int):
    size = max(1, size)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def normalize_path(path: str) -> str:
    return path.rstrip("/") or "/"


def resolve_root_folder(roots: list, scan_folder: str, explicit: str | None):
    scan = normalize_path(scan_folder)
    if explicit:
        explicit_norm = normalize_path(explicit)
        for root in roots:
            if normalize_path(root.get("path", "")) == explicit_norm:
                return root
        # Explicit root not in Radarr, but still validate containment below.
        return {"id": None, "path": explicit_norm, "accessible": None}
    for root in roots:
        rp = normalize_path(root.get("path", ""))
        if scan == rp or scan.startswith(rp + "/"):
            return root
    return roots[0] if roots else {"id": None, "path": None, "accessible": None}


def resolve_quality_profile(profiles: list, spec):
    if not profiles:
        raise ApiError("Radarr returned no quality profiles")
    if spec is None:
        return min(profiles, key=lambda p: p.get("id", 0))
    text = str(spec).strip()
    if text.isdigit():
        wanted = int(text)
        for profile in profiles:
            if profile.get("id") == wanted:
                return profile
        available = ", ".join(f"{p.get('id')}={p.get('name')}" for p in profiles)
        raise ApiError(f"quality profile id {wanted} not found; available: {available}")
    for profile in profiles:
        if (profile.get("name") or "").lower() == text.lower():
            return profile
    available = ", ".join(f"{p.get('id')}={p.get('name')}" for p in profiles)
    raise ApiError(f"quality profile '{text}' not found; available: {available}")


def discover_folders(items: list, scan_folder: str):
    """Group manualimport items by top-level movie folder.

    Returns an ordered list of ``(folder_name, folder_path, items)``.
    """
    scan = normalize_path(scan_folder)
    groups: dict[str, list] = {}
    for item in items:
        folder_name = item.get("folderName")
        rel = item.get("relativePath") or ""
        if not folder_name:
            if "/" in rel:
                folder_name = rel.split("/", 1)[0]
            elif rel:
                # A loose file directly inside the scan folder.
                folder_name = ""
            else:
                parent = os.path.dirname(item.get("path") or "")
                folder_name = "" if normalize_path(parent) == scan else os.path.basename(parent)
        groups.setdefault(folder_name, []).append(item)

    folders = []
    for name in sorted(groups):
        path = os.path.join(scan, name) if name else scan
        folders.append((name or os.path.basename(scan), path, groups[name]))
    return folders


# --------------------------------------------------------------------------- #
# State / report
# --------------------------------------------------------------------------- #
def load_state(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("state file is not an object")
        data.setdefault("completed", {})
        return data
    except FileNotFoundError:
        return {"version": 1, "completed": {}}
    except (ValueError, OSError) as exc:
        print(f"warning: ignoring unreadable state file {path}: {exc}", file=sys.stderr)
        return {"version": 1, "completed": {}}


def save_state(path: str, state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, path)


def write_report(json_path: str, records: list, meta: dict) -> str:
    summary = {key: 0 for key in OUTCOME_ORDER}
    for rec in records:
        summary[rec.get("status", "error")] = summary.get(rec.get("status", "error"), 0) + 1

    report = {"generated_at": datetime.now(timezone.utc).isoformat(), **meta,
              "summary": summary, "folders": records}
    parent = os.path.dirname(os.path.abspath(json_path))
    os.makedirs(parent, exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=False)
        fh.write("\n")

    txt_path = os.path.splitext(json_path)[0] + ".txt"
    lines = []
    lines.append("Radarr library import report")
    lines.append("=" * 60)
    lines.append(f"Generated:      {report['generated_at']}")
    lines.append(f"URL:            {meta.get('url')}")
    lines.append(f"Scan folder:    {meta.get('folder')}")
    lines.append(f"Root folder:    {meta.get('root_folder')}")
    lines.append(f"Quality profile:{meta.get('quality_profile_id')} ({meta.get('quality_profile_name')})")
    lines.append(f"Import mode:    {meta.get('import_mode')}")
    lines.append(f"Mode:           {'APPLY' if meta.get('apply') else 'DRY-RUN'}")
    lines.append(f"Limit:          {meta.get('limit')}")
    lines.append("")
    lines.append("Summary (folders):")
    for key in OUTCOME_ORDER:
        lines.append(f"  {key:<20} {summary.get(key, 0)}")
    lines.append(f"  {'skipped (state)':<20} {meta.get('skipped', 0)}")
    lines.append("")
    lines.append("Details:")
    for rec in records:
        lines.append(f"[{rec.get('status')}] {rec.get('folder')}")
        lines.append(f"    reason: {rec.get('reason')}")
        for key in ("movieId", "tmdbId", "title", "year", "hasFile", "pre_existing", "added"):
            if rec.get(key) is not None:
                lines.append(f"    {key}: {rec.get(key)}")
        for file_path in rec.get("files", []):
            lines.append(f"      - {file_path}")
        lines.append("")
    with open(txt_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return txt_path


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="radarr-library-import.py",
        description="Bulk-import existing on-disk movie folders into Radarr (dry-run by default).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--url", default=os.environ.get("RADARR_URL", DEFAULT_URL),
                        help="Radarr base URL (env RADARR_URL)")
    parser.add_argument("--api-key", default=os.environ.get("RADARR_API_KEY", ""),
                        help="Radarr API key (env RADARR_API_KEY; required)")
    parser.add_argument("--folder", default=DEFAULT_SCAN_FOLDER,
                        help="root folder to scan for movie folders")
    parser.add_argument("--root-folder", default=None,
                        help="Radarr root folder path (default: configured root containing --folder, else first root)")
    parser.add_argument("--quality-profile", default=None,
                        help="quality profile name or numeric id (default: lowest id)")
    parser.add_argument("--import-mode", choices=["move", "copy", "hardlink"], default="move",
                        help="ManualImport import mode")
    parser.add_argument("--monitored", action="store_true",
                        help="mark added movies as monitored (default: unmonitored)")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--apply", action="store_true",
                            help="actually POST changes (default: dry-run, no mutations)")
    mode_group.add_argument("--dry-run", action="store_true",
                            help="explicitly run in dry-run mode (the default; no mutations)")
    parser.add_argument("--limit", type=int, default=None,
                        help="maximum number of folders to process")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="files per ManualImport command")
    parser.add_argument("--max-retries", type=int, default=5,
                        help="max attempts per HTTP request")
    parser.add_argument("--timeout", type=float, default=90.0,
                        help="per-request socket timeout in seconds")
    parser.add_argument("--min-interval", type=float, default=0.5,
                        help="minimum seconds between HTTP requests")
    tls_group = parser.add_mutually_exclusive_group()
    tls_group.add_argument("--insecure", "--no-verify", dest="insecure", action="store_true",
                           default=_env_bool("RADARR_INSECURE"),
                           help="skip TLS certificate verification (alias --no-verify; "
                                "env RADARR_INSECURE=1/true/yes)")
    tls_group.add_argument("--cafile", default=os.environ.get("RADARR_CAFILE") or None,
                           help="CA bundle / self-signed certificate to trust while keeping "
                                "verification and hostname checks enabled (env RADARR_CAFILE)")
    parser.add_argument("--strict-ssl", action="store_true",
                        help="disable the automatic acceptance of self-signed certificates; "
                             "TLS verification failures are then fatal")
    parser.add_argument("--verbose", action="store_true",
                        help="print detailed request/discovery logging")
    parser.add_argument("--state", default=DEFAULT_STATE,
                        help="resume state file (apply mode only)")
    parser.add_argument("--report", default=DEFAULT_REPORT,
                        help="report JSON path (a .txt companion is also written)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    log = Log(args.verbose)

    if not args.api_key:
        log.info("error: no API key supplied (use --api-key or set RADARR_API_KEY)")
        return 2
    if args.limit is not None and args.limit < 0:
        log.info("error: --limit must be >= 0")
        return 2

    dry_run = not args.apply
    mode_label = "DRY-RUN (no mutations)" if dry_run else "APPLY"
    log.info(f"mode: {mode_label}")
    log.info(f"target: {args.url}")

    try:
        http = HttpClient(            base_url=args.url,
            api_key=args.api_key,
            timeout=args.timeout,
            max_retries=args.max_retries,
            min_interval=args.min_interval,
            insecure=args.insecure,
            log=log,
            cafile=args.cafile,
            strict_ssl=args.strict_ssl,
        )
    except ApiError as exc:
        log.info(f"error: {exc}")
        return 2
    radarr = Radarr(http, log)

    try:
        status = radarr.status() or {}
    except ApiError as exc:
        log.info(f"error: cannot reach Radarr at {args.url}: {exc}")
        return 3
    log.info(f"connected: Radarr {status.get('version')} ({status.get('instanceName')})")

    try:
        profiles = radarr.quality_profiles() or []
        roots = radarr.root_folders() or []
        movies = radarr.movies() or []
    except ApiError as exc:
        log.info(f"error: preflight failed: {exc}")
        return 3

    profile = resolve_quality_profile(profiles, args.quality_profile)
    root = resolve_root_folder(roots, args.folder, args.root_folder)

    scan = normalize_path(args.folder)
    root_path = normalize_path(root.get("path") or "")
    if args.root_folder or root_path:
        if not (scan == root_path or scan.startswith(root_path + "/")):
            log.info(
                f"error: --folder {args.folder} is not under any known Radarr root folder "
                f"({', '.join(normalize_path(r.get('path','')) for r in roots) or 'none'})"
            )
            return 3
        if root.get("accessible") is False:
            log.info(f"error: Radarr reports root folder {root_path} as inaccessible")
            return 3

    log.info(f"quality profile: {profile.get('id')} ({profile.get('name')})")
    log.info(f"root folder: {root_path}")
    log.info(f"scan folder: {scan}")

    lib_tmdb_to_id = {m.get("tmdbId"): m.get("id") for m in movies if m.get("tmdbId") is not None}
    orig_movie_ids = {m.get("id") for m in movies}
    orig_tmdb = set(lib_tmdb_to_id)

    log.info(f"library: {len(movies)} movies")

    # Discovery
    try:
        items = radarr.manual_import(scan)
    except ApiError as exc:
        log.info(f"error: manualimport discovery failed: {exc}")
        return 3
    items = items or []
    folders = discover_folders(items, scan)
    log.info(f"discovered {len(folders)} folders with {len(items)} candidate files under {scan}")

    if args.verbose:
        for name, path, fitems in folders:
            log.debug(f"    folder: {name} ({len(fitems)} file(s))")

    # Resume state (apply mode only)
    state = {"version": 1, "completed": {}} if dry_run else load_state(args.state)
    completed = state.get("completed", {})
    pending = [(n, p, f) for (n, p, f) in folders if n not in completed]
    skipped = len(folders) - len(pending)
    if skipped:
        log.info(f"skipping {skipped} folder(s) already recorded as done in {args.state}")
    if args.limit is not None:
        pending = pending[: args.limit]
    log.info(f"processing {len(pending)} folder(s)")

    records = []
    interrupted = False
    try:
        for index, (folder_name, folder_path, folder_items) in enumerate(pending, 1):
            log.info(f"--- [{index}/{len(pending)}] {folder_name} ({len(folder_items)} file(s))")
            record = {
                "folder": folder_name,
                "path": folder_path,
                "status": "error",
                "reason": "",
                "files": [item.get("path") for item in folder_items],
                "pre_existing": False,
                "added": False,
                "movieId": None,
                "tmdbId": None,
                "title": None,
                "year": None,
                "hasFile": None,
            }
            try:
                record.update(process_folder(
                    radarr=radarr,
                    folder_name=folder_name,
                    folder_path=folder_path,
                    items=folder_items,
                    profile_id=profile.get("id"),
                    root_path=root_path,
                    monitored=args.monitored,
                    import_mode=args.import_mode,
                    batch_size=args.batch_size,
                    apply=args.apply,
                    lib_tmdb_to_id=lib_tmdb_to_id,
                    orig_movie_ids=orig_movie_ids,
                    orig_tmdb=orig_tmdb,
                    timeout=args.timeout,
                    log=log,
                ))
            except ApiError as exc:
                record["reason"] = f"API error: {exc}"
            except Exception as exc:  # never let one bad folder abort the run
                record["reason"] = f"unexpected error: {exc!r}"
            records.append(record)
            log.info(f"    -> {record['status']}: {record.get('reason')}")

    except KeyboardInterrupt:
        interrupted = True
        log.info("interrupted -- writing state and report for work completed so far")
        if args.apply:
            for prior in records:
                if prior.get("status") in SUCCESS_STATES:
                    completed[prior["folder"]] = {
                        "status": prior["status"],
                        "movieId": prior.get("movieId"),
                        "tmdbId": prior.get("tmdbId"),
                        "at": datetime.now(timezone.utc).isoformat(),
                    }
            state["completed"] = completed
            save_state(args.state, state)

    # Final verification pass (apply only -- dry-run made no changes).
    if not args.apply:
        log.info("dry-run: skipping post-import verification (no changes were made)")
    else:
        log.info("re-fetching library to verify import results ...")
        try:
            final_movies = radarr.movies() or []
        except ApiError as exc:
            log.info(f"warning: verification fetch failed: {exc}")
            final_movies = movies
        by_id = {m.get("id"): m for m in final_movies}
        by_tmdb = {m.get("tmdbId"): m for m in final_movies if m.get("tmdbId") is not None}

        for record in records:
            # unresolved folders have no movie to verify against.
            if record["status"] == "unresolved":
                continue
            # A record may have errored *after* the movie was added; if it has a
            # movie reference, still verify it so a real import is recognized.
            if record.get("movieId") is None and record.get("tmdbId") is None:
                # Genuinely failed before any movie existed; leave as error.
                continue
            if record.get("movieId") is None and record.get("tmdbId") is not None:
                found = by_tmdb.get(record["tmdbId"])
                if found:
                    record["movieId"] = found.get("id")
            movie = None
            if record.get("movieId") is not None:
                movie = by_id.get(record["movieId"])
            if movie is None and record.get("tmdbId") is not None:
                movie = by_tmdb.get(record["tmdbId"])
            if movie is not None:
                record["hasFile"] = bool(movie.get("hasFile"))
                record["movieId"] = movie.get("id")
                if movie.get("title"):
                    record["title"] = movie.get("title")
                if movie.get("year"):
                    record["year"] = movie.get("year")
            if record.get("hasFile"):
                record["status"] = "imported"
                record["reason"] = "hasFile=true"
            elif record.get("pre_existing"):
                record["status"] = "already-in-library"
                if not record.get("reason"):
                    record["reason"] = "movie already existed in library; no file imported"
            else:
                record["status"] = "added-but-no-file"
                if not record.get("reason"):
                    record["reason"] = "added, but Radarr reports hasFile=false"

        # Persist resume state once, after verification: only truly imported
        # folders are marked done so everything else is retried next run.
        for record in records:
            if record.get("status") in SUCCESS_STATES:
                completed[record["folder"]] = {
                    "status": record["status"],
                    "movieId": record.get("movieId"),
                    "tmdbId": record.get("tmdbId"),
                    "at": datetime.now(timezone.utc).isoformat(),
                }
        state["completed"] = completed
        save_state(args.state, state)

    meta = {
        "url": args.url,
        "folder": scan,
        "root_folder": root_path,
        "quality_profile_id": profile.get("id"),
        "quality_profile_name": profile.get("name"),
        "import_mode": args.import_mode,
        "apply": args.apply,
        "limit": args.limit,
        "skipped": skipped,
        "interrupted": interrupted,
    }
    txt_path = write_report(args.report, records, meta)

    summary = {key: 0 for key in OUTCOME_ORDER}
    for record in records:
        summary[record["status"]] = summary.get(record["status"], 0) + 1

    log.out("")
    log.out(f"Radarr library import {'APPLY' if args.apply else 'DRY-RUN'} summary")
    for key in OUTCOME_ORDER:
        log.out(f"  {key:<20} {summary.get(key, 0)}")
    log.out(f"  {'processed':<20} {len(records)}")
    log.out(f"  {'skipped (state)':<20} {skipped}")
    if any(r["status"] in ("unresolved", "error") for r in records):
        log.out("")
        log.out("Some folders were unresolved or errored (metadata backend may have been down).")
        log.out("Re-run the same command to retry them; resolved folders are skipped via the state file.")
    log.out("")
    log.out(f"report: {args.report}")
    log.out(f"        {txt_path}")
    if not args.apply:
        log.out("dry-run: no changes were made and no state was written. Re-run with --apply to execute.")
    else:
        log.out(f"state:  {args.state}")

    return 0


def process_folder(
    *,
    radarr: Radarr,
    folder_name: str,
    folder_path: str,
    items: list,
    profile_id,
    root_path: str,
    monitored: bool,
    import_mode: str,
    batch_size: int,
    apply: bool,
    lib_tmdb_to_id: dict,
    orig_movie_ids: set,
    orig_tmdb: set,
    timeout: float,
    log: Log,
) -> dict:
    record = {
        "folder": folder_name,
        "path": folder_path,
        "status": "error",
        "reason": "",
        "files": [item.get("path") for item in items],
        "pre_existing": False,
        "added": False,
        "movieId": None,
        "tmdbId": None,
        "title": None,
        "year": None,
        "hasFile": None,
    }

    # 1. Movie already known from the manualimport match (local library match).
    matched_movie = next((item.get("movie") for item in items if item.get("movie")), None)
    movie_id = None
    if matched_movie:
        movie_id = matched_movie.get("id")
        tmdb_id = matched_movie.get("tmdbId")
        record.update(movieId=movie_id, tmdbId=tmdb_id,
                      title=matched_movie.get("title"), year=matched_movie.get("year"))
        record["pre_existing"] = movie_id in orig_movie_ids or (
            tmdb_id is not None and tmdb_id in orig_tmdb
        )
        log.debug(f"    local library match: movieId={movie_id} tmdbId={tmdb_id}")
    else:
        title, year = parse_folder_name(folder_name)
        log.debug(f"    parsed folder: title={title!r} year={year!r}")
        try:
            results = radarr.lookup(folder_name)
        except ApiError as exc:
            record["status"] = "unresolved"
            record["reason"] = f"lookup failed (metadata backend): {exc}"
            return record
        results = results or []
        best = choose_lookup(results, year)
        if best is None or best.get("tmdbId") is None:
            record["status"] = "unresolved"
            record["reason"] = "no usable lookup result (metadata backend returned nothing)"
            log.debug(f"    lookup returned {len(results)} result(s); none usable")
            return record

        best_year = best.get("year")
        exact = year is not None and best_year == year
        log.debug(
            f"    lookup chose: title={best.get('title')!r} year={best_year} "
            f"tmdbId={best.get('tmdbId')} (exact-year={exact})"
        )
        tmdb_id = int(best["tmdbId"])
        record.update(tmdbId=tmdb_id, title=best.get("title"), year=best_year)

        if tmdb_id in lib_tmdb_to_id:
            movie_id = lib_tmdb_to_id[tmdb_id]
            record["movieId"] = movie_id
            record["pre_existing"] = True
            record["reason"] = "tmdbId already in library; reusing existing movieId"
            log.debug(f"    tmdbId {tmdb_id} already in library -> movieId={movie_id}")
        else:
            payload = build_add_payload(best, profile_id, root_path, folder_path, monitored)
            if apply:
                created = radarr.add_movie(payload) or {}
                movie_id = created.get("id")
                if movie_id is None:
                    record["status"] = "error"
                    record["reason"] = "POST /api/v3/movie returned no id"
                    return record
                record["movieId"] = movie_id
                record["added"] = True
                lib_tmdb_to_id[tmdb_id] = movie_id  # dedupe within this run
                log.debug(f"    added movie -> movieId={movie_id}")
            else:
                record["would_add"] = payload
                log.out(f"[dry-run] would POST /api/v3/movie ({folder_name}):")
                log.out(json.dumps(payload, indent=2))
                # unknown until the add happens; keep placeholder for the command payload
                movie_id = "<new movieId from add>"

    # 2. ManualImport for the folder's files.
    files = build_manual_import_files(items, folder_name, movie_id)
    if apply:
        if movie_id is None:
            record["status"] = "error"
            record["reason"] = "no movieId available for ManualImport"
            return record
        for batch in chunked(files, batch_size):
            command = radarr.start_manual_import(batch, import_mode) or {}
            command_id = command.get("id")
            if command_id is None:
                record["status"] = "error"
                record["reason"] = "POST /api/v3/command returned no id"
                return record
            log.debug(f"    ManualImport command id={command_id} ({len(batch)} file(s))")
            final = radarr.poll_command(command_id, deadline_secs=max(300.0, timeout * 6), log=log)
            if final.get("status") != "completed":
                record["status"] = "error"
                record["reason"] = (
                    f"ManualImport command {command_id} ended with status "
                    f"{final.get('status')}: {final.get('message') or final.get('exception') or ''}"
                )
                return record
        record["status"] = "imported"
        record["reason"] = "manual import command completed"
    else:
        record["would_import"] = []
        for batch in chunked(files, batch_size):
            payload = {"name": "ManualImport", "files": batch, "importMode": import_mode}
            record["would_import"].append(payload)
            log.out(f"[dry-run] would POST /api/v3/command ({folder_name}):")
            log.out(json.dumps(payload, indent=2))
        record["status"] = "would-import"
        record["reason"] = "dry-run: movie resolved and import payload built"

    return record


if __name__ == "__main__":
    sys.exit(main())
