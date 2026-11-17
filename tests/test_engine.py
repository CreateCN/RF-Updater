import dataclasses
import io
import os
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from rf_updater.engine import Engine, exclusive, _process_image
from rf_updater.models import Cancelled, UpdaterError, atomic_json
from tests.support import Server, linux_package, zip_package


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "updater"
        self.cancel = threading.Event()

    def test_full_install_update_verify_rollback(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            self.assertEqual(engine.verify(self.cancel), 2)
            server.data, server.etag = linux_package(b"#!/bin/sh\necho v2\n"), '"build-2"'
            second = engine.install(server.release(), self.cancel)
            self.assertNotEqual(first["generation"], second["generation"])
            self.assertEqual(engine.state()["previous"], first)
            self.assertTrue(engine.payload(first).exists())
            self.assertEqual(engine.verify(self.cancel), 2)
            self.assertEqual(engine.rollback(), first)
            self.assertEqual(engine.state()["active"], first)
            self.assertEqual(engine.state()["previous"], second)
            self.assertEqual(engine.verify(self.cancel), 2)

    def test_check_compares_official_build_identifiers(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            # Keep the real HTTP transport, only substitute the fixture endpoint.
            with patch.object(engine.network, "probe", side_effect=lambda target: original(target, server.url)):
                original = type(server.network).probe.__get__(server.network)
                release, status = engine.check()
                self.assertEqual(status, "available")
                engine.install(release, self.cancel)
                self.assertEqual(engine.check()[1], "current")
                server.etag = '"v2"'
                # With a publisher digest, identical bytes are the same build.
                self.assertEqual(engine.check()[1], "current")
                server.data = linux_package(b"#!/bin/sh\necho changed\n")
                self.assertEqual(engine.check()[1], "available")

    def test_unknown_identity_does_not_claim_current(self):
        with Server() as server:
            server.send_validators = server.digest = False
            engine = Engine(self.root, "linux", server.network)
            release = server.release()
            engine.install(release, self.cancel)
            with patch.object(engine.network, "probe", return_value=release):
                self.assertEqual(engine.check()[1], "unknown")

    def test_corrupt_update_preserves_active_install(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            server.data, server.etag = b"corrupt-gzip", '"broken"'
            with self.assertRaises(UpdaterError):
                engine.install(server.release(), self.cancel)
            self.assertEqual(engine.state()["active"], first)
            self.assertEqual(engine.verify(self.cancel), 2)
            self.assertEqual(len(list((self.root / "installs").iterdir())), 1)

    def test_cancelled_update_preserves_current(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            self.cancel.set()
            with self.assertRaises(Cancelled):
                engine.install(server.release(), self.cancel)
            self.assertEqual(engine.state()["active"], first)

    def test_failed_activation_preserves_previous_pointer(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            original = atomic_json
            def fail_state(path, value):
                if path == engine.state_path:
                    raise OSError("simulated disk failure")
                original(path, value)
            with patch("rf_updater.engine.atomic_json", side_effect=fail_state):
                with self.assertRaises(OSError):
                    engine.install(server.release(), self.cancel)
            self.assertEqual(engine.state()["active"], first)
            self.assertTrue(engine.payload(first).exists())

    def test_tamper_and_missing_file_detected(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            installation = engine.install(server.release(), self.cancel)
            binary = engine.payload(installation) / installation["executable"]
            data = binary.read_bytes()
            binary.write_bytes(b"X" + data[1:])
            with self.assertRaisesRegex(UpdaterError, "已修改"):
                engine.verify(self.cancel)
            binary.unlink()
            with self.assertRaisesRegex(UpdaterError, "缺失"):
                engine.verify(self.cancel)

    def test_interrupted_commit_does_not_remove_the_active_generation(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            original = atomic_json
            def interrupt_after_commit(path, value):
                original(path, value)
                if path == engine.state_path:
                    raise KeyboardInterrupt
            with patch("rf_updater.engine.atomic_json", side_effect=interrupt_after_commit):
                with self.assertRaises(KeyboardInterrupt):
                    engine.install(server.release(), self.cancel)
            self.assertTrue(engine.payload(engine.state()["active"]).exists())
            self.assertEqual(engine.verify(self.cancel), 2)

    def test_does_not_delete_old_generations_or_game_created_data(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            save = engine.payload(first) / "my-save.json"
            save.write_text('{"world":"fixture"}')
            for n in range(2):
                server.data = linux_package(f"#!/bin/sh\necho {n}\n".encode())
                engine.install(server.release(), self.cancel)
            self.assertTrue(save.exists())
            self.assertEqual(len(list((self.root / "installs").iterdir())), 3)

    def test_simultaneous_process_is_locked_out(self):
        code = "from pathlib import Path; from rf_updater.engine import exclusive; import sys;\nwith exclusive(Path(sys.argv[1])): pass"
        with exclusive(self.root):
            result = subprocess.run([sys.executable, "-c", code, str(self.root)], capture_output=True,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("另一个更新器".encode(), result.stderr)
        with exclusive(self.root):
            pass

    def test_untrusted_state_cannot_escape_install_directory(self):
        self.root.mkdir()
        atomic_json(self.root / "state.json", {"schema": 1, "active": {"generation": "../../escape", "executable": "a", "release": {}}, "previous": None})
        with self.assertRaises(UpdaterError):
            Engine(self.root, "linux").state()

    def test_mac_and_windows_install_archives(self):
        for target in ("windows", "macos"):
            with self.subTest(target=target), Server(zip_package(target)) as server:
                engine = Engine(self.root / target, target, server.network)
                installation = engine.install(server.release(target), self.cancel)
                self.assertEqual(installation["release"]["platform"], target)
                self.assertGreater(engine.verify(self.cancel), 0)

    def test_mismatched_platform_is_rejected(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            with self.assertRaisesRegex(UpdaterError, "平台"):
                engine.install(dataclasses.replace(server.release(), platform="windows"), self.cancel)

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux fixture launch")
    def test_launch_real_fixture_game_and_log(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            engine.install(server.release(), self.cancel)
            pid = engine.launch()
            self.assertGreater(pid, 0)
            # Join the actual reaper, avoiding sleeps or timing assumptions.
            for thread in threading.enumerate():
                if thread.name.endswith("(wait)"):
                    thread.join(timeout=5)
            self.assertIn("fixture-game", (self.root / "logs/game.log").read_text())


    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process fixtures")
    def test_game_running_detection_and_operation_guards(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            engine.install(server.release(), self.cancel)
            # The sleep build must be the active generation: launch() starts active.
            server.data, server.etag = linux_package(b"#!/bin/sh\nsleep 30\n"), '"build-2"'
            engine.install(server.release(), self.cancel)
            pid = engine.launch()
            def stop():
                try:
                    os.kill(pid, 15)
                except ProcessLookupError:
                    pass
            self.addCleanup(stop)
            deadline = time.monotonic() + 5
            while engine.game_running() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            session = engine.game_running()
            self.assertIsNotNone(session)
            self.assertEqual(session["generation"], engine.state()["active"]["generation"])
            with self.assertRaisesRegex(UpdaterError, "运行"):
                engine.install(server.release(), self.cancel)
            with self.assertRaisesRegex(UpdaterError, "运行"):
                engine.rollback()
            stop()
            for thread in threading.enumerate():
                if thread.name.endswith("(wait)"):
                    thread.join(timeout=5)
            self.assertIsNone(engine.game_running())
            self.assertIsNotNone(engine.rollback())

    def test_reused_pid_with_other_executable_is_not_running(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            installation = engine.install(server.release(), self.cancel)
            executable = (engine.payload(installation) / installation["executable"]).resolve()
            atomic_json(self.root / "game-session.json", {
                "pid": os.getpid(), "executable": str(executable),
                "command": [str(executable)], "generation": installation["generation"]})
            self.assertIsNone(engine.game_running())

    def test_matching_live_session_is_running(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            installation = engine.install(server.release(), self.cancel)
            atomic_json(self.root / "game-session.json", {
                "pid": os.getpid(), "executable": _process_image(os.getpid()) or str(Path(sys.executable).resolve()),
                "command": [sys.executable], "generation": installation["generation"]})
            self.assertIsNotNone(engine.game_running())

    def test_transient_download_interrupt_retries_and_resumes(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            original = engine.network.download
            calls = []
            def flaky(release, cache, cancel, progress):
                calls.append(1)
                server.truncate = len(calls) == 1
                return original(release, cache, cancel, progress)
            with patch.object(engine.network, "download", side_effect=flaky), \
                 patch("rf_updater.engine.RETRY_DELAYS", (0, 0, 0)):
                engine.install(server.release(), self.cancel)
            self.assertEqual(len(calls), 2)
            self.assertEqual(engine.verify(self.cancel), 2)
            self.assertIn("download_retry", (self.root / "logs/updater.log").read_text(encoding="utf-8"))

    def test_retry_budget_exhausted_preserves_active_install(self):
        with Server() as server:
            engine = Engine(self.root, "linux", server.network)
            first = engine.install(server.release(), self.cancel)
            server.data, server.etag = linux_package(b"#!/bin/sh\necho v2\n"), '"build-2"'
            server.truncate = True
            with patch("rf_updater.engine.RETRY_DELAYS", (0, 0, 0)):
                with self.assertRaises(UpdaterError):
                    engine.install(server.release(), self.cancel)
            self.assertEqual(engine.state()["active"], first)
            self.assertIn("install_failed", (self.root / "logs/updater.log").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
