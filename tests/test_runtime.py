import os
import unittest
from unittest.mock import patch

from rf_updater.runtime import external_environment


class RuntimeTests(unittest.TestCase):
    def test_source_preserves_environment(self):
        with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/user/libs"}, clear=True):
            self.assertEqual(external_environment(), {"LD_LIBRARY_PATH": "/user/libs"})

    def test_frozen_linux_restores_original_libraries_without_mutating_parent(self):
        bundle = os.path.abspath(os.path.join("test-bundle", "_internal"))
        user_bin = os.path.abspath(os.path.join("user", "bin"))
        with patch("sys.frozen", True, create=True), patch("sys.platform", "linux"), patch("sys._MEIPASS", bundle, create=True):
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": f"{bundle}:/user/libs", "LD_LIBRARY_PATH_ORIG": "/user/libs", "PATH": os.pathsep.join([os.path.join(bundle, "tools"), user_bin])}, clear=True):
                env = external_environment()
                self.assertEqual(env["LD_LIBRARY_PATH"], "/user/libs")
                self.assertEqual(env["PATH"], user_bin)
                self.assertNotIn("LD_LIBRARY_PATH_ORIG", env)
                self.assertIn(bundle, os.environ["LD_LIBRARY_PATH"])

    def test_frozen_linux_removes_injected_libraries_if_no_original(self):
        with patch("sys.frozen", True, create=True), patch("sys.platform", "linux"):
            with patch.dict(os.environ, {"LD_LIBRARY_PATH": "/app/_internal"}, clear=True):
                self.assertNotIn("LD_LIBRARY_PATH", external_environment())

    def test_frozen_qt_paths_are_removed_without_losing_user_paths(self):
        bundle = os.path.abspath(os.path.join("test-bundle", "_internal"))
        plugins = os.path.join(bundle, "PySide6", "Qt", "plugins")
        user_plugins = os.path.abspath("user-qt-plugins")
        with patch("sys.frozen", True, create=True), patch("sys._MEIPASS", bundle, create=True):
            with patch.dict(os.environ, {"QT_PLUGIN_PATH": os.pathsep.join([plugins, user_plugins]),
                                         "QT_QPA_PLATFORM_PLUGIN_PATH": plugins,
                                         "QML_IMPORT_PATH": os.path.join(bundle, "qml"),
                                         "QT_QPA_PLATFORMTHEME": "user-theme"}, clear=True):
                cleaned = external_environment()
                self.assertEqual(cleaned["QT_PLUGIN_PATH"], user_plugins)
                self.assertNotIn("QT_QPA_PLATFORM_PLUGIN_PATH", cleaned)
                self.assertNotIn("QML_IMPORT_PATH", cleaned)
                self.assertEqual(cleaned["QT_QPA_PLATFORMTHEME"], "user-theme")
                self.assertIn(plugins, os.environ["QT_PLUGIN_PATH"])


if __name__ == "__main__":
    unittest.main()
