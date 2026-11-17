import base64
import dataclasses
import hashlib
import os
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch
from pathlib import Path

from rf_updater.models import Cancelled, NetworkInterrupted, UpdaterError, atomic_json
from rf_updater.network import CHUNK, Network, SecureRedirect, checksum_header, tls_context
from tests.support import Server


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cache = Path(self.temp.name)
        self.cancel = threading.Event()

    def seed_partial(self, server, release, length=21):
        (self.cache / f"{release.identity}.part").write_bytes(server.data[:length])
        atomic_json(self.cache / f"{release.identity}.json", release.to_dict())

    def test_transport_interrupt_is_retryable_type(self):
        with Server() as server:
            server.truncate = True
            release = server.release()
            with self.assertRaises(NetworkInterrupted):
                server.network.download(release, self.cache, self.cancel)
            self.assertTrue((self.cache / f"{release.identity}.part").exists())

    def test_redirect_probe_and_download_with_publisher_checksum(self):
        with Server() as server:
            release = server.release()
            self.assertEqual(release.size, len(server.data))
            package, digest = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)
            self.assertEqual(digest, release.sha256)
            self.assertTrue(any(r[1] == "/package" for r in server.requests))

    def test_resume_uses_range_and_if_range(self):
        with Server() as server:
            release = server.release()
            self.seed_partial(server, release)
            package, _ = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)
            request = next(r for r in server.requests if r[0] == "GET")
            self.assertEqual(request[2]["Range"], "bytes=21-")
            self.assertEqual(request[2]["If-Range"], release.etag)

    def test_ignored_range_restarts_instead_of_appending(self):
        with Server() as server:
            server.range_mode = "ignore"
            release = server.release()
            self.seed_partial(server, release)
            package, _ = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)

    def test_invalid_range_never_appends(self):
        with Server() as server:
            server.range_mode = "wrong"
            release = server.release()
            self.seed_partial(server, release)
            with self.assertRaisesRegex(UpdaterError, "续传位置"):
                server.network.download(release, self.cache, self.cancel)
            self.assertEqual((self.cache / f"{release.identity}.part").stat().st_size, 21)

    def test_head_unsupported_uses_one_byte_range(self):
        with Server() as server:
            server.head_status = 405
            release = server.release()
            self.assertEqual(release.size, len(server.data))
            self.assertEqual(server.requests[-1][2]["Range"], "bytes=0-0")

    def test_changed_build_rejected_and_partial_discarded(self):
        with Server() as server:
            release = server.release()
            self.seed_partial(server, release)
            server.etag = '"build-2"'
            with self.assertRaisesRegex(UpdaterError, "已更新"):
                server.network.download(release, self.cache, self.cancel)
            self.assertFalse((self.cache / f"{release.identity}.part").exists())

    def test_if_match_prevents_new_build_download(self):
        with Server() as server:
            release = server.release()
            server.etag = '"build-2"'
            with self.assertRaisesRegex(UpdaterError, "已改变"):
                server.network.download(release, self.cache, self.cancel)

    def test_checksum_mismatch_discards_package(self):
        with Server() as server:
            release = dataclasses.replace(server.release(), sha256="0" * 64)
            with self.assertRaisesRegex(UpdaterError, "SHA-256"):
                server.network.download(release, self.cache, self.cancel)
            self.assertFalse((self.cache / f"{release.identity}.part").exists())

    def test_truncated_body_keeps_partial_and_can_resume(self):
        with Server(os.urandom(CHUNK * 2)) as server:
            release = server.release()
            server.truncate = True
            with self.assertRaises(UpdaterError):
                server.network.download(release, self.cache, self.cancel)
            self.assertGreater((self.cache / f"{release.identity}.part").stat().st_size, 0)
            server.truncate = False
            package, _ = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)

    def test_cancel_and_resume(self):
        with Server(os.urandom(CHUNK * 3)) as server:
            release = server.release()
            def progress(phase, done, total):
                if phase == "download" and done >= CHUNK:
                    self.cancel.set()
            with self.assertRaises(Cancelled):
                server.network.download(release, self.cache, self.cancel, progress)
            self.cancel.clear()
            package, _ = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)

    def test_no_validators_does_not_resume_and_is_not_comparable(self):
        with Server() as server:
            server.digest, server.send_validators = False, False
            release = server.release()
            self.assertFalse(release.comparable)
            self.seed_partial(server, release)
            package, _ = server.network.download(release, self.cache, self.cancel)
            self.assertEqual(package.read_bytes(), server.data)
            self.assertNotIn("Range", next(r for r in server.requests if r[0] == "GET")[2])

    def test_plain_http_is_rejected_by_default(self):
        with self.assertRaises(UpdaterError):
            Network().validate_url("http://api.rocketfoundry.net/download/linux")

    def test_tls_keeps_hostname_and_certificate_verification_enabled(self):
        context = tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_frozen_bundle_requires_its_ca_file(self):
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", str(self.cache), create=True):
            with self.assertRaisesRegex(UpdaterError, "证书文件"):
                tls_context()

    def test_https_downgrade_redirect_rejected(self):
        with self.assertRaises(UpdaterError):
            SecureRedirect(Network().validate_url).redirect_request(
                None, None, 302, "redirect", {}, "http://example.com/payload")

    def test_digest_headers(self):
        raw = hashlib.sha256(b"fixture").digest()
        encoded = base64.b64encode(raw).decode()
        for name, value in (("Digest", f"sha-256={encoded}"), ("Content-Digest", f"sha-256=:{encoded}:")):
            self.assertEqual(checksum_header({name: value}), raw.hex())
        self.assertIsNone(checksum_header({"Digest": "sha-256=bad"}))
        self.assertIsNone(checksum_header({"Content-Digest": f"sha-256=:{encoded}:"}, partial=True))
        self.assertEqual(checksum_header({"Repr-Digest": f"sha-256=:{encoded}:"}, partial=True), raw.hex())


if __name__ == "__main__":
    unittest.main()
