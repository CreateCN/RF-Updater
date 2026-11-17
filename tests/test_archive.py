import io
import gzip
import os
import stat
import sys
import tarfile
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from rf_updater.archive import extract_package, safe_path
from rf_updater.engine import find_executable
from rf_updater.models import Cancelled, UpdaterError
from tests.support import linux_package, zip_package


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.destination = self.root / "payload"
        self.cancel = threading.Event()

    def extract(self, data, target="linux"):
        self.package.write_bytes(data)
        return extract_package(self.package, self.destination, target, self.cancel)

    def test_tar_extracts_and_records_hashes_and_executable(self):
        records = self.extract(linux_package())
        self.assertEqual(len(records), 2)
        path = find_executable(self.destination, "linux")
        self.assertEqual(path, "RocketFoundry/RocketFoundry")
        if sys.platform != "win32":
            self.assertTrue((self.destination / path).stat().st_mode & stat.S_IXUSR)

    def test_windows_zip_discovers_game(self):
        self.extract(zip_package(), "windows")
        self.assertEqual(find_executable(self.destination, "windows"), "Rocket Foundry/RocketFoundry.exe")

    def test_mac_bundle_discovers_game(self):
        self.extract(zip_package("macos"), "macos")
        self.assertEqual(find_executable(self.destination, "macos"), "Rocket Foundry.app")
        if sys.platform != "win32":
            self.assertTrue((self.destination / "Rocket Foundry.app/Contents/MacOS/RocketFoundry").stat().st_mode & 0o111)

    def test_rejects_absolute_traversal_windows_devices_and_ads(self):
        for name in ("../escape", "/etc/passwd", "C:/escape", "x\\..\\escape", "ok/../../escape", "file:stream", "NUL.txt", "folder/trailing."):
            with self.subTest(name=name), self.assertRaises(UpdaterError):
                safe_path(name)

    def test_tar_path_traversal_is_rejected_before_writing(self):
        info = tarfile.TarInfo("../escape")
        info.size = 4
        with self.assertRaises(UpdaterError):
            self.extract(linux_package(extra=[(info, b"evil")]))
        self.assertFalse((self.root / "escape").exists())
        self.assertFalse(self.destination.exists())

    def test_zip_path_traversal_is_rejected(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("../../escape", b"evil")
        with self.assertRaises(UpdaterError):
            self.extract(buffer.getvalue(), "windows")

    def test_device_file_rejected(self):
        info = tarfile.TarInfo("device")
        info.type = tarfile.CHRTYPE
        with self.assertRaises(UpdaterError):
            self.extract(linux_package(extra=[(info, None)]))

    @unittest.skipIf(os.name == "nt", "Creating symlinks needs Windows developer privileges")
    def test_safe_internal_symlink_is_preserved(self):
        info = tarfile.TarInfo("RocketFoundry/current")
        info.type, info.linkname = tarfile.SYMTYPE, "assets/data.bin"
        records = self.extract(linux_package(extra=[(info, None)]))
        self.assertTrue((self.destination / "RocketFoundry/current").is_symlink())
        self.assertEqual(records[-1]["link"], "assets/data.bin")

    @unittest.skipIf(os.name == "nt", "Creating symlinks needs Windows developer privileges")
    def test_macos_zip_internal_symlink_is_preserved(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("App/Versions/A/library", b"library")
            link = zipfile.ZipInfo("App/Versions/Current")
            link.create_system, link.external_attr = 3, (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "A")
        self.extract(buffer.getvalue(), "macos")
        self.assertEqual((self.destination / "App/Versions/Current/library").read_bytes(), b"library")

    def test_escaping_symlink_rejected(self):
        info = tarfile.TarInfo("RocketFoundry/link")
        info.type, info.linkname = tarfile.SYMTYPE, "../../outside"
        with self.assertRaisesRegex(UpdaterError, "之外"):
            self.extract(linux_package(extra=[(info, None)]))

    def test_hardlink_preserves_content_without_copying(self):
        info = tarfile.TarInfo("RocketFoundry/data-alias")
        info.type, info.linkname = tarfile.LNKTYPE, "RocketFoundry/assets/data.bin"
        self.extract(linux_package(extra=[(info, None)]))
        original = self.destination / info.linkname
        alias = self.destination / info.name
        self.assertEqual(alias.read_bytes(), original.read_bytes())
        self.assertTrue(os.path.samefile(original, alias))

    def test_no_writes_through_symlink_parents(self):
        info = tarfile.TarInfo("RocketFoundry/assets")
        info.type, info.linkname = tarfile.SYMTYPE, "../../outside"
        with self.assertRaisesRegex(UpdaterError, "穿过"):
            self.extract(linux_package(extra=[(info, None)]))
        self.assertFalse(self.destination.exists())

    def test_extraction_budget_rejected_before_writing(self):
        with patch("rf_updater.archive.MAX_UNPACKED", 10):
            with self.assertRaisesRegex(UpdaterError, "限制"):
                self.extract(linux_package())
        self.assertFalse(self.destination.exists())

    def test_cancellation_stops_extraction(self):
        self.cancel.set()
        with self.assertRaises(Cancelled):
            self.extract(linux_package())

    def test_invalid_archive_is_actionable(self):
        with self.assertRaisesRegex(UpdaterError, "解压"):
            self.extract(b"not-a-gzip")

    def test_corrupt_gzip_trailer_is_rejected_before_writing(self):
        package = bytearray(linux_package())
        package[-8] ^= 1
        with self.assertRaisesRegex(UpdaterError, "解压"):
            self.extract(package)
        self.assertFalse(self.destination.exists())

    def test_tar_budget_checked_before_seeking_over_declared_file(self):
        info = tarfile.TarInfo("huge-file")
        info.size = 17 * 1024**3
        data = gzip.compress(info.tobuf() + bytes(1024))
        with self.assertRaisesRegex(UpdaterError, "限制"):
            self.extract(data)
        self.assertFalse(self.destination.exists())

    def test_case_collisions_rejected_on_windows(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("Game/file", b"1")
            archive.writestr("game/FILE", b"2")
        with self.assertRaisesRegex(UpdaterError, "重复"):
            self.extract(buffer.getvalue(), "windows")


if __name__ == "__main__":
    unittest.main()
