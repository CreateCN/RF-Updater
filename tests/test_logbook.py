import json
import tempfile
import unittest
from pathlib import Path

from rf_updater import logbook


class LogbookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rf-logbook-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_records_json_lines_with_timestamps(self):
        logbook.record(self.root, "event_a", value=1)
        logbook.record(self.root, "event_b", detail="中文")
        entries = [json.loads(line) for line in logbook.log_path(self.root).read_text(encoding="utf-8").splitlines()]
        self.assertEqual([entry["event"] for entry in entries], ["event_a", "event_b"])
        self.assertEqual(entries[0]["value"], 1)
        self.assertEqual(entries[1]["detail"], "中文")
        self.assertTrue(all("time" in entry for entry in entries))

    def test_rotation_keeps_bounded_backups(self):
        path = logbook.log_path(self.root)
        path.parent.mkdir(parents=True)
        path.write_text("x" * (logbook.MAX_BYTES + 1), encoding="utf-8")
        logbook.record(self.root, "after_rotation")
        self.assertTrue(path.with_name("updater.log.1").exists())
        self.assertIn("after_rotation", path.read_text(encoding="utf-8"))
        self.assertLess(path.stat().st_size, logbook.MAX_BYTES)

    def test_disconnected_root_is_not_recreated(self):
        missing = self.root / "missing"
        logbook.record(missing, "event")
        self.assertFalse(missing.exists())

    def test_unwritable_location_does_not_raise(self):
        logbook.record(Path("/proc/rf-updater-nonexistent"), "event")


if __name__ == "__main__":
    unittest.main()
