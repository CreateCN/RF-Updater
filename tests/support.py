"""Real local HTTP fixtures; never contact or redistribute the game."""
from __future__ import annotations

import hashlib
import io
import plistlib
import tarfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rf_updater.network import Network


def linux_package(content=b"#!/bin/sh\necho fixture-game\n", extra=None):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        entries = [("RocketFoundry/RocketFoundry", content, 0o755),
                   ("RocketFoundry/assets/data.bin", b"fixture-asset" * 1000, 0o644)]
        for name, value, mode in entries:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(value), mode
            archive.addfile(info, io.BytesIO(value))
        for info, value in extra or []:
            archive.addfile(info, io.BytesIO(value) if value is not None else None)
    return buffer.getvalue()


def zip_package(target="windows"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if target == "windows":
            archive.writestr("Rocket Foundry/RocketFoundry.exe", b"fixture-exe")
        else:
            archive.writestr("Rocket Foundry.app/Contents/Info.plist", plistlib.dumps({"CFBundleExecutable": "RocketFoundry"}))
            archive.writestr("Rocket Foundry.app/Contents/MacOS/RocketFoundry", b"fixture-mach-o")
        archive.writestr("assets/data.bin", b"fixture-asset")
    return buffer.getvalue()


class Server:
    def __init__(self, data=None):
        self.data = data or linux_package()
        self.etag = '"build-1"'
        self.modified = "Mon, 16 Nov 2026 01:00:00 GMT"
        self.range_mode = "normal"
        self.head_status = 200
        self.digest = True
        self.send_validators = True
        self.truncate = False
        self.requests = []
        fixture = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                self.serve(True)

            def do_GET(self):
                self.serve(False)

            def serve(self, head):
                fixture.requests.append((self.command, self.path, dict(self.headers)))
                if self.path == "/download":
                    self.send_response(302)
                    self.send_header("Location", "/package")
                    self.end_headers()
                    return
                if head and fixture.head_status != 200:
                    self.send_response(fixture.head_status)
                    self.end_headers()
                    return
                if self.headers.get("If-Match") and self.headers["If-Match"] != fixture.etag:
                    self.send_response(412)
                    self.end_headers()
                    return
                data = fixture.data
                start = 0
                end = len(data) - 1
                range_value = self.headers.get("Range")
                ranged = range_value and fixture.range_mode != "ignore"
                if ranged:
                    first, last = range_value.removeprefix("bytes=").split("-")
                    start = int(first)
                    if last:
                        end = int(last)
                if start >= len(data):
                    self.send_response(416)
                    self.end_headers()
                    return
                self.send_response(206 if ranged else 200)
                self.send_header("Content-Length", str(end - start + 1))
                if fixture.send_validators:
                    self.send_header("ETag", fixture.etag)
                    self.send_header("Last-Modified", fixture.modified)
                if fixture.digest:
                    self.send_header("X-Checksum-Sha256", hashlib.sha256(data).hexdigest())
                if ranged:
                    range_start = start + 1 if fixture.range_mode == "wrong" else start
                    self.send_header("Content-Range", f"bytes {range_start}-{end}/{len(data)}")
                self.end_headers()
                if not head:
                    body = data[start:end+1]
                    if fixture.truncate:
                        body = body[:len(body)//2]
                    try:
                        self.wfile.write(body)
                    except (BrokenPipeError, ConnectionResetError):
                        pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.network = Network(allow_local_http=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/download"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def release(self, target="linux"):
        return self.network.probe(target, self.url)
