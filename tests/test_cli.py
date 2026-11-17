"""CLI language selection through machine locale identifiers."""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class CliLanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rf-cli-lang-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "data"

    def run_cli(self, *args, env=None):
        environment = {**os.environ, **(env or {})}
        return subprocess.run([sys.executable, "-m", "rf_updater", "--root", str(self.root), *args],
                              capture_output=True, text=True, timeout=60,
                              env={**environment, "PYTHONIOENCODING": "utf-8"})

    def test_explicit_override_wins(self):
        result = self.run_cli("verify", env={"RF_UPDATER_LANG": "en", "LC_ALL": "zh_CN.UTF-8"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("Error:", result.stderr)
        self.assertIn("Install the game first.", result.stderr)

    def test_traditional_chinese(self):
        result = self.run_cli("verify", env={"RF_UPDATER_LANG": "zh-TW"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("錯誤：", result.stderr)
        self.assertIn("請先安裝遊戲。", result.stderr)

    def test_lc_all_is_used_without_override(self):
        env = {"LC_ALL": "en_US.UTF-8"}
        for variable in ("RF_UPDATER_LANG", "LC_MESSAGES", "LANG"):
            env[variable] = ""
        result = self.run_cli("verify", env=env)
        self.assertIn("Install the game first.", result.stderr)

    def test_unset_locale_keeps_source_language(self):
        env = {variable: "" for variable in ("RF_UPDATER_LANG", "LC_ALL", "LC_MESSAGES", "LANG")}
        result = self.run_cli("verify", env=env)
        self.assertIn("错误：", result.stderr)
        self.assertIn("请先安装游戏。", result.stderr)

    def test_help_description_is_localized(self):
        result = self.run_cli("--help", env={"RF_UPDATER_LANG": "en"})
        self.assertEqual(result.returncode, 0)
        self.assertIn("Rocket Foundry community desktop updater", result.stdout)


if __name__ == "__main__":
    unittest.main()
