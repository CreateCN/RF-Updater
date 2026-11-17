from __future__ import annotations

import base64
import hashlib
import http.client
import re
import ssl
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable

from . import __version__
from .i18n import t
from .models import Cancelled, NetworkInterrupted, PLATFORMS, Release, UpdaterError, atomic_json, read_json

MAX_PACKAGE = 12 * 1024**3
CHUNK = 256 * 1024
Progress = Callable[[str, int, int | None], None]


def no_progress(phase: str, done: int, total: int | None) -> None:
    pass


def check_cancel(cancel: threading.Event) -> None:
    if cancel.is_set():
        raise Cancelled(t("net.cancelled"))


class SecureRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, validate):
        super().__init__()
        self.validate = validate

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.validate(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Network:
    def __init__(self, *, allow_local_http: bool = False):
        self.allow_local_http = allow_local_http
        self.opener = urllib.request.build_opener(SecureRedirect(self.validate_url),
                                                 urllib.request.HTTPSHandler(context=tls_context()))

    def validate_url(self, url: str) -> None:
        parsed = urllib.parse.urlsplit(url)
        local = self.allow_local_http and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if not parsed.hostname or parsed.username or parsed.password or (
            parsed.scheme != "https" and not (local and parsed.scheme == "http")
        ):
            raise UpdaterError(t("net.https_required"))

    def open(self, url: str, *, method="GET", headers=None):
        self.validate_url(url)
        req = urllib.request.Request(url, method=method, headers={
            "User-Agent": f"RF-Updater/{__version__} (+https://rocketfoundry.net/)",
            "Accept-Encoding": "identity", **(headers or {}),
        })
        return self.opener.open(req, timeout=25)

    def probe(self, target: str, url: str | None = None) -> Release:
        url = url or PLATFORMS[target][1]
        try:
            try:
                response = self.open(url, method="HEAD")
            except urllib.error.HTTPError as exc:
                exc.close()
                if exc.code not in {405, 501}:
                    raise
                response = self.open(url, headers={"Range": "bytes=0-0"})
            with response:
                h = response.headers
                length = h.get("Content-Length", "")
                content_range = re.fullmatch(r"bytes \d+-\d+/(\d+)", h.get("Content-Range", ""))
                size = int(content_range[1]) if content_range else (int(length) if length.isdigit() else None)
                if size is not None and (size <= 0 or size > MAX_PACKAGE):
                    raise UpdaterError(t("net.invalid_size"))
                return Release(target, url, size, h.get("ETag"), h.get("Last-Modified"), checksum_header(h, partial=response.status == 206))
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise UpdaterError(t("net.check_failed", error=exc)) from exc

    def download(self, release: Release, cache: Path, cancel: threading.Event,
                 progress: Progress = no_progress) -> tuple[Path, str]:
        cache.mkdir(parents=True, exist_ok=True)
        part = cache / f"{release.identity}.part"
        metadata = part.with_suffix(".json")
        validator = release.etag if release.etag and not release.etag.startswith("W/") else release.modified
        saved = read_json(metadata, {})
        if saved != release.to_dict() or not validator:
            part.unlink(missing_ok=True)
        atomic_json(metadata, release.to_dict())
        offset = part.stat().st_size if part.exists() else 0
        if release.size is not None and offset > release.size:
            part.unlink()
            offset = 0
        check_cancel(cancel)
        if offset and offset == release.size:
            return self._verify(part, release, cancel, progress)
        headers = {}
        if offset:
            headers.update({"Range": f"bytes={offset}-", "If-Range": validator})
        elif release.etag and not release.etag.startswith("W/"):
            headers["If-Match"] = release.etag
        try:
            with self.open(release.url, headers=headers) as response:
                h = response.headers
                if h.get("Content-Encoding", "identity").lower() != "identity":
                    raise UpdaterError(t("net.encoding"))
                changed = ((release.etag and h.get("ETag") and release.etag != h["ETag"])
                           or (release.modified and h.get("Last-Modified")
                               and release.modified != h["Last-Modified"]))
                if changed:
                    part.unlink(missing_ok=True)
                    raise UpdaterError(t("net.build_changed"))
                if response.status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", h.get("Content-Range", ""))
                    if not match or int(match[1]) != offset or int(match[2]) < offset:
                        raise UpdaterError(t("net.bad_range"))
                    total = int(match[3])
                    if int(match[2]) != total - 1:
                        raise UpdaterError(t("net.incomplete_range"))
                elif response.status == 200:
                    offset = 0  # Range ignored or If-Range no longer matches: safely restart.
                    length = h.get("Content-Length", "")
                    total = int(length) if length.isdigit() else release.size
                else:
                    raise UpdaterError(t("net.http_status", status=response.status))
                if total and (total > MAX_PACKAGE or (release.size is not None and total != release.size)):
                    raise UpdaterError(t("net.size_changed"))
                done = offset
                with part.open("ab" if offset else "wb") as stream:
                    progress("download", done, total)
                    while True:
                        check_cancel(cancel)
                        chunk = response.read(CHUNK)
                        if not chunk:
                            break
                        done += len(chunk)
                        if done > MAX_PACKAGE or (total is not None and done > total):
                            raise UpdaterError(t("net.oversize"))
                        stream.write(chunk)
                        progress("download", done, total)
                    stream.flush()
                if total is not None and done != total:
                    raise NetworkInterrupted(t("net.interrupted_partial"))
        except urllib.error.HTTPError as exc:
            exc.close()
            if exc.code in {412, 416}:
                part.unlink(missing_ok=True)
                raise UpdaterError(t("net.package_changed")) from exc
            raise UpdaterError(t("net.http_failed", code=exc.code)) from exc
        except (OSError, urllib.error.URLError, http.client.HTTPException) as exc:
            raise NetworkInterrupted(t("net.interrupted", error=exc)) from exc
        return self._verify(part, release, cancel, progress)

    def _verify(self, path: Path, release: Release, cancel: threading.Event, progress: Progress):
        digest = hashlib.sha256()
        total = path.stat().st_size
        done = 0
        with path.open("rb") as stream:
            while chunk := stream.read(CHUNK):
                check_cancel(cancel)
                digest.update(chunk)
                done += len(chunk)
                progress("verify", done, total)
        value = digest.hexdigest()
        if release.sha256 and value != release.sha256:
            path.unlink(missing_ok=True)
            raise UpdaterError(t("net.checksum_mismatch"))
        return path, value


def checksum_header(headers, *, partial=False) -> str | None:
    value = headers.get("X-Checksum-Sha256", "").strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", value):
        return value
    # Content-Digest on a 206 response hashes only that response's range.
    # Repr-Digest describes the complete representation, including for ranges.
    digest = headers.get("Repr-Digest", "") or ("" if partial else (headers.get("Content-Digest", "") or headers.get("Digest", "")))
    match = re.search(r"(?:^|,\s*)sha-256=(:?[A-Za-z0-9+/]+={0,2}:?)(?:,|$)", digest, re.I)
    if match:
        try:
            raw = base64.b64decode(match[1].strip(":"), validate=True)
            if len(raw) == 32:
                return raw.hex()
        except ValueError:
            pass
    return None


def tls_context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    if getattr(sys, "frozen", False):
        # A build machine's OpenSSL CA paths may not exist on the user's machine,
        # especially in macOS bundles. Include public Mozilla roots at build time.
        bundle = Path(sys._MEIPASS) / "ca-bundle.pem"
        if not bundle.is_file():
            raise UpdaterError(t("net.missing_ca"))
        context.load_verify_locations(cafile=str(bundle))
    return context
