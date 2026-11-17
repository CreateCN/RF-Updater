"""Qt widget/worker acceptance against real local HTTP and synthetic packages."""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
except ImportError as exc:
    raise unittest.SkipTest("Install the declared PySide6 dependency for desktop tests") from exc

from rf_updater.engine import Engine, _process_image
from rf_updater.gui import App
from rf_updater.network import CHUNK
from rf_updater.ui.theme import apply_theme
from tests.support import Server, linux_package


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)
        apply_theme(cls.application)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rf-qt-qa-")
        self.preferences_patch = patch('rf_updater.preferences.preferences_path', return_value=Path(self.temp.name)/'settings/directories.json')
        self.preferences_patch.start()
        # Pin the GUI language so assertions hold on any CI machine locale.
        from rf_updater import preferences
        preferences.save_settings({"language": "zh-CN"})
        self.server = Server()
        self.server.__enter__()
        self.engine = Engine(Path(self.temp.name), "linux", self.server.network)
        original = self.engine.network.probe
        self.engine.network.probe = lambda target, url=None: original(target, url or self.server.url)
        self.window = None
        self.gates = []

    def tearDown(self):
        for gate in self.gates:
            gate.set()
        if self.window:
            self.window.close()
            self.wait_until(lambda: not self.window.controller.jobs)
            self.window.close()
            self.window.deleteLater()
            QApplication.processEvents()
        self.server.__exit__()
        self.temp.cleanup()
        self.preferences_patch.stop()
        from rf_updater import i18n
        i18n.use("zh-CN")

    def gate(self):
        result = threading.Event()
        self.gates.append(result)
        return result

    def open_window(self):
        self.window = App(self.engine, auto_check=False)
        self.window.show()
        if QApplication.platformName() != "offscreen":
            self.window.windowHandle().requestActivate()
        QTest.qWait(60)
        return self.window, self.window.controller

    def wait_until(self, condition, timeout=12):
        deadline = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= deadline:
                self.fail("Qt operation timed out")
            QTest.qWait(10)
        QApplication.processEvents()

    def idle(self):
        self.wait_until(lambda: not self.window.controller.jobs)

    def click(self, widget):
        self.assertTrue(widget.isEnabled(), widget.objectName())
        self.assertTrue(widget.isVisible(), widget.objectName())
        for scroll in self.window.pages.values():
            if scroll.widget().isAncestorOf(widget):
                scroll.ensureWidgetVisible(widget, 12, 12)
                QTest.qWait(20)
        self.assertFalse(widget.visibleRegion().isEmpty(), widget.objectName())
        QTest.mouseClick(widget, Qt.MouseButton.LeftButton)

    def capture(self, name):
        folder = os.environ.get("RF_QA_SCREENSHOTS")
        if folder:
            QTest.qWait(80)
            path = Path(folder)
            path.mkdir(parents=True, exist_ok=True)
            self.assertTrue(self.window.grab().save(str(path / f"{name}.png")))

    def install_first(self):
        return self.engine.install(self.server.release(), threading.Event())

    def test_complete_desktop_flow_and_layout(self):
        window, c = self.open_window()
        self.capture("home")
        self.click(window.primary)
        self.idle()
        self.assertEqual(window.primary.text(), "安装游戏")
        self.click(window.primary)
        self.idle()
        self.assertIsNotNone(c.active)
        self.assertEqual(window.primary.text(), "启动游戏")
        self.assertEqual(window.task_panel.bar.value(), 1000)
        self.capture("installed")
        self.click(window.nav["manage"])
        self.capture("manage")
        self.click(window.verify_button)
        self.idle()
        self.assertEqual(c.notice.title, "游戏文件校验通过")
        self.assertEqual(window.page, "manage")
        self.server.data, self.server.etag = linux_package(b"#!/bin/sh\necho version-2\n"), '"build-2"'
        self.click(window.nav["home"])
        self.click(window.check_button)
        self.idle()
        self.assertTrue(window.update_button.isVisible())
        self.assertEqual(window.primary.text(), "启动游戏")
        self.capture("update-available")
        self.click(window.update_button)
        self.idle()
        second = c.active
        self.click(window.nav["manage"])
        with patch.object(window, "confirm", return_value=True) as confirm:
            self.click(window.rollback_button)
            self.idle()
            confirm.assert_called_once()
        self.assertEqual(c.previous, second)
        self.assertIsNone(c.release)
        with patch.object(window, "confirm", return_value=True):
            self.click(window.reinstall_button)
            self.idle()
        self.assertEqual(c.remote_status, "current")
        self.click(window.findChild(QPushButton, "copy_data_path"))
        self.assertEqual(QApplication.clipboard().text(), str(self.engine.root))
        window.show_page("home")
        window.task_panel.details.toggle.setChecked(False)
        window.task_panel.details._toggle(False)
        self.wait_until(lambda: window.pages['home'].verticalScrollBar().maximum() == 0)
        for width, height in ((1120, 760), (900, 640)):
            window.resize(width, height)
            QTest.qWait(80)
            for name in ("home", "manage", "about"):
                self.click(window.nav[name])
                QTest.qWait(50)
                self.assertEqual(window.pages[name].horizontalScrollBar().maximum(), 0)
                self.assertFalse(window.task_panel.visibleRegion().isEmpty())
                if name == "home":
                    window.pages[name].verticalScrollBar().setValue(0)
                    self.assertFalse(window.primary.visibleRegion().isEmpty())
                    self.assertEqual(window.orbit.isVisible(), width >= 1040)
                self.capture(f"{'small-' if width == 900 else ''}{name}-final")

    def test_check_does_not_block_launch_and_offline_launch_remains_available(self):
        self.install_first()
        window, c = self.open_window()
        entered, release = self.gate(), self.gate()
        original = self.engine.check
        def blocked_check():
            entered.set()
            if not release.wait(30):
                raise RuntimeError("test gate timeout")
            return original()
        with patch.object(self.engine, "check", side_effect=blocked_check), patch.object(self.engine, "launch", return_value=12345) as launch:
            self.click(window.check_button)
            self.wait_until(entered.is_set)
            self.assertTrue(c.checking)
            self.assertTrue(window.primary.isEnabled())
            self.click(window.primary)
            self.wait_until(lambda: c.notice is not None and c.notice.operation == "launch")
            self.assertTrue(c.checking)
            self.assertEqual(c.notice.title, "已发送启动请求")
            launch.assert_called_once()
            release.set()
            self.idle()
        self.server.head_status = 503
        self.click(window.check_button)
        self.idle()
        self.assertIsNotNone(c.check_error)
        self.assertTrue(window.primary.isEnabled())
        self.assertEqual(window.primary.text(), "启动游戏")
        self.assertTrue(window.connection_details.isVisible())
        self.capture("offline-installed")
        with patch.object(self.engine, "launch", return_value=12345) as launch:
            self.click(window.primary)
            self.idle()
            launch.assert_called_once()
        self.server.head_status = 200
        self.click(window.check_button)
        self.idle()
        self.assertIsNone(c.check_error)

    def test_cancel_download_page_switch_and_real_range_resume(self):
        self.server.data = linux_package(b"#!/bin/sh\n" + os.urandom(CHUNK * 6))
        window, c = self.open_window()
        self.click(window.primary)
        self.idle()
        entered, release = self.gate(), self.gate()
        original = self.engine.install
        def held_install(build, cancel, progress):
            def report(phase, done, total):
                progress(phase, done, total)
                if phase == "download" and done >= CHUNK and not entered.is_set():
                    entered.set()
                    if not release.wait(30):
                        raise RuntimeError("download gate timed out")
            return original(build, cancel, report)
        with patch.object(self.engine, "install", side_effect=held_install):
            self.click(window.primary)
            # Progress signals are coalesced to 10 Hz; the first written chunk
            # can be held before the next nonzero sample is forwarded to Qt.
            self.wait_until(lambda: entered.is_set() and c.progress.phase == "download")
            self.click(window.nav["manage"])
            self.assertTrue(c.busy)
            self.assertEqual(window.page, "manage")
            self.assertFalse(window.verify_button.isEnabled())
            self.assertTrue(window.task_panel.cancel.isVisible())
            self.capture("download")
            self.click(window.task_panel.cancel)
            release.set()
            self.idle()
        self.assertEqual(c.notice.tone, "warning")
        part = self.engine.root / "cache" / f"{c.release.identity}.part"
        self.assertGreater(part.stat().st_size, 0)
        self.assertLess(part.stat().st_size, len(self.server.data))
        self.capture("cancelled")
        self.click(window.task_panel.retry)
        self.idle()
        self.assertIsNotNone(c.active)
        self.assertEqual(window.page, "manage")
        self.assertTrue(any(method == "GET" and "Range" in headers for method, _, headers in self.server.requests))
        self.assertEqual(self.engine.verify(threading.Event()), 2)

    def test_failed_update_preserves_install_and_retry_recovers(self):
        first = self.install_first()
        self.server.data, self.server.etag = b"broken-gzip", '"broken"'
        window, c = self.open_window()
        self.click(window.check_button)
        self.idle()
        self.click(window.update_button)
        self.idle()
        self.assertEqual(c.active, first)
        self.assertEqual(c.notice.tone, "error")
        self.assertTrue(window.primary.isEnabled())
        self.click(window.task_panel.details.toggle)
        self.assertIn("解压", window.task_panel.details.body.toPlainText())
        self.capture("error")
        self.server.data = linux_package(b"#!/bin/sh\necho fixed\n")
        self.server.etag = '"fixed"'
        self.click(window.check_button)
        self.idle()
        self.click(window.task_panel.retry)
        self.idle()
        self.assertEqual(c.notice.tone, "success")
        self.assertNotEqual(c.active, first)

    def test_close_waits_for_check_thread(self):
        window, c = self.open_window()
        entered, release = self.gate(), self.gate()
        original = self.engine.check
        def blocked():
            entered.set()
            release.wait(30)
            return original()
        with patch.object(self.engine, "check", side_effect=blocked):
            self.click(window.primary)
            self.wait_until(entered.is_set)
            window.close()
            self.assertTrue(window.isVisible())
            self.assertTrue(c.closing)
            self.assertFalse(window.primary.isEnabled())
            release.set()
            self.wait_until(lambda: not c.jobs and not window.isVisible())

    def test_close_cancels_install_without_damaging_existing_data(self):
        first = self.install_first()
        window, c = self.open_window()
        entered, release = self.gate(), self.gate()
        original = self.engine.install
        def blocked(build, cancel, progress):
            entered.set()
            release.wait(30)
            return original(build, cancel, progress)
        self.click(window.check_button)
        self.idle()
        with patch.object(window, "confirm", return_value=True), patch.object(self.engine, "install", side_effect=blocked):
            window.reinstall()
            self.wait_until(entered.is_set)
            window.close()
            self.assertTrue(c.closing)
            self.assertTrue(window.isVisible())
            release.set()
            self.wait_until(lambda: not c.jobs and not window.isVisible())
        self.assertEqual(self.engine.state()["active"], first)

    def test_old_results_cannot_replace_new_check_and_text_is_plain(self):
        window, c = self.open_window()
        self.click(window.primary)
        old_id = c.check_id
        self.idle()
        expected = c.release
        entered, release = self.gate(), self.gate()
        original = self.engine.check
        def blocked():
            entered.set()
            release.wait(30)
            return original()
        with patch.object(self.engine, "check", side_effect=blocked):
            self.click(window.check_button)
            self.wait_until(entered.is_set)
            c._result(old_id, (None, "unknown"))
            c._error(old_id, RuntimeError("stale error"))
            self.assertTrue(c.checking)
            self.assertEqual(c.release, expected)
            release.set()
            self.idle()
        c.check_error = "<b>network error</b>\nhttps://example.invalid/?a=<tag>"
        window.refresh()
        window.connection_details.toggle.click()
        self.assertIn("<b>", window.connection_details.body.toPlainText())
        self.assertEqual(window.remote_label.textFormat(), Qt.TextFormat.PlainText)
        long_path = str(self.engine.root / ("long-directory-name-" * 14))
        window.path_field.setText(long_path)
        self.assertEqual(window.path_field.text(), long_path)
        window.resize(900, 640)
        window.show_page("manage")
        QTest.qWait(80)
        self.assertEqual(window.pages['manage'].horizontalScrollBar().maximum(), 0)
        window.path_field.setFocus()
        QTest.keyClick(window.path_field, Qt.Key.Key_Tab)
        self.assertIs(window.focusWidget(), window.folder_button)
        self.capture("long-path-focus")

    def test_confirmations_can_cancel_without_creating_tasks(self):
        self.install_first()
        window, c = self.open_window()
        with patch.object(window, "confirm", return_value=False):
            window.reinstall()
            window.rollback()
        self.assertFalse(c.jobs)
        self.assertIsNotNone(c.active)


    def test_visual_storage_inventory_and_selected_cleanup(self):
        first = self.install_first()
        for index in (2, 3):
            self.server.etag = f'"build-{index}"'
            self.server.data = linux_package(f'#!/bin/sh\necho {index}\n'.encode())
            self.install_first()
        window, c = self.open_window()
        self.click(window.nav['directories'])
        self.idle()
        page = window.directory_page
        self.assertIsNotNone(c.inventory)
        self.assertGreater(c.inventory.totals['cache'], 0)
        self.assertGreater(c.inventory.totals['active'], 0)
        active_key = 'installs/' + c.active['generation']
        previous_key = 'installs/' + c.previous['generation']
        self.assertFalse(page.rows[active_key].flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(page.rows[previous_key].flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.capture('directory-manager')
        self.click(page.select_cache_button)
        self.assertTrue(page.cleanup_button.isEnabled())
        with patch.object(page, 'confirm_cleanup', return_value=False):
            self.click(page.cleanup_button)
        self.assertTrue(any(item.kind == 'cache' for item in c.inventory.items))
        with patch.object(page, 'confirm_cleanup', return_value=True):
            self.click(page.cleanup_button)
            self.idle()
        self.assertFalse(any(item.kind == 'cache' for item in c.inventory.items))
        old_key = 'installs/' + first['generation']
        page.rows[old_key].setCheckState(0, Qt.CheckState.Checked)
        with patch.object(page, 'confirm_cleanup', return_value=True):
            self.click(page.cleanup_button)
            self.idle()
        self.assertFalse(self.engine.payload(first).parent.exists())
        self.assertTrue(self.engine.payload(c.active).exists())
        self.assertTrue(self.engine.payload(c.previous).exists())
        self.assertIn(active_key, page.rows)
        for width, height in ((1120, 760), (900, 640)):
            window.resize(width, height)
            QTest.qWait(60)
            self.assertEqual(window.pages['directories'].horizontalScrollBar().maximum(), 0)
            self.capture(f'directory-{width}')
        self.engine = c.engine

    def test_directory_picker_switch_persistence_and_return(self):
        from rf_updater import preferences
        self.install_first()
        before = self.engine.state_path.read_bytes()
        other = tempfile.TemporaryDirectory(prefix='rf-directory-choice-')
        self.addCleanup(other.cleanup)
        destination = Path(other.name).resolve()
        (destination / 'unrelated.txt').write_text('keep')
        window, c = self.open_window()
        self.click(window.nav['directories'])
        self.idle()
        page = window.directory_page
        with patch('rf_updater.ui.directories.QFileDialog.getExistingDirectory', return_value=str(destination)):
            with patch.object(page, 'confirm_switch', return_value=False):
                self.click(page.choose_button)
            self.assertEqual(c.engine.root, self.engine.root)
            self.assertIsNone(preferences.saved_root())
            with patch.object(page, 'confirm_switch', return_value=True):
                self.click(page.choose_button)
                self.idle()
        self.assertEqual(c.engine.root, destination)
        self.assertEqual(window.engine.root, destination)
        self.assertEqual(page.path_field.text(), str(destination))
        self.assertEqual(window.path_field.text(), str(destination))
        self.assertEqual(preferences.saved_root(), destination)
        self.assertEqual(Engine(target='linux').root, destination)
        self.assertEqual((destination / 'unrelated.txt').read_text(), 'keep')
        self.assertEqual(self.engine.state_path.read_bytes(), before)
        self.assertIsNone(c.active)
        page.combo.setCurrentIndex(page.combo.findData(str(self.engine.root)))
        with patch.object(page, 'confirm_switch', return_value=True):
            self.click(page.switch_button)
            self.idle()
        self.assertEqual(c.engine.root, self.engine.root)
        self.assertIsNotNone(c.active)
        self.assertEqual(window.primary.text(), '启动游戏')
        self.assertEqual(c.notice.title, '已切换下载目录')
        self.capture('directory-switch')

    def test_unavailable_saved_directory_can_be_replaced_visually(self):
        from rf_updater import storage
        import shutil
        other = tempfile.TemporaryDirectory(prefix='rf-external-choice-')
        self.addCleanup(other.cleanup)
        destination = Path(other.name).resolve()
        self.engine = storage.switch_directory(self.engine, destination)
        shutil.rmtree(destination)
        window, c = self.open_window()
        self.assertIsNotNone(c.state_error)
        self.assertFalse(window.primary.isEnabled())
        self.click(window.nav['directories'])
        self.idle()
        page = window.directory_page
        replacement_temp = tempfile.TemporaryDirectory(prefix='rf-replacement-choice-')
        self.addCleanup(replacement_temp.cleanup)
        replacement = Path(replacement_temp.name).resolve()
        with patch('rf_updater.ui.directories.QFileDialog.getExistingDirectory', return_value=str(replacement)), patch.object(page, 'confirm_switch', return_value=True):
            self.click(page.choose_button)
            self.idle()
        self.assertEqual(c.engine.root, replacement)
        self.assertIsNone(c.state_error)
        self.assertFalse(destination.exists())

    def test_old_install_cleanup_dialog_requires_backup_checkbox(self):
        from rf_updater.storage import StorageItem
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMessageBox
        window, c = self.open_window()
        window.show_page('directories')
        self.idle()
        item = StorageItem('installs/old', '旧安装', 'old', '待清理', 10, self.engine.root / 'old', True)
        observed = []
        timer = QTimer(window)
        timer.setSingleShot(True)
        def inspect_dialog():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QMessageBox):
                accept = next(button for button in dialog.buttons() if button.text() == '确认清理')
                observed.append(not accept.isEnabled())
                checkbox = dialog.checkBox()
                checkbox.setChecked(True)
                observed.append(accept.isEnabled())
                dialog.reject()
        timer.timeout.connect(inspect_dialog)
        timer.start(50)
        self.assertFalse(window.directory_page.confirm_cleanup([item]))
        self.assertEqual(observed, [True, True])


    def test_directory_scan_can_cancel_and_disables_directory_changes(self):
        from rf_updater import storage
        window, c = self.open_window()
        entered, release = self.gate(), self.gate()
        original = storage.scan
        def held(engine, cancel, progress):
            entered.set()
            release.wait(30)
            return original(engine, cancel, progress)
        with patch('rf_updater.ui.controller.storage.scan', side_effect=held):
            self.click(window.nav['directories'])
            self.wait_until(entered.is_set)
            self.assertFalse(window.directory_page.choose_button.isEnabled())
            self.assertFalse(window.directory_page.refresh_button.isEnabled())
            self.assertTrue(window.task_panel.cancel.isVisible())
            self.click(window.task_panel.cancel)
            release.set()
            self.idle()
        self.assertEqual(c.notice.tone, 'warning')
        self.assertEqual(c.notice.operation, 'storage_scan')
        self.assertTrue(window.directory_page.choose_button.isEnabled())
        self.click(window.task_panel.retry)
        self.idle()
        self.assertIsNotNone(c.inventory)


    def test_game_running_disables_update_rollback_and_old_cleanup(self):
        from rf_updater.models import atomic_json
        first = self.install_first()
        for index in (2, 3):
            self.server.etag = f'"build-{index}"'
            self.server.data = linux_package(f'#!/bin/sh\necho {index}\n'.encode())
            self.install_first()
        atomic_json(self.engine.root / 'game-session.json', {
            'pid': os.getpid(), 'executable': _process_image(os.getpid()) or str(Path(sys.executable).resolve()),
            'command': [sys.executable], 'generation': self.engine.state()['active']['generation']})
        window, c = self.open_window()
        self.assertTrue(c.game_running)
        self.assertEqual(window.primary.text(), '游戏运行中')
        self.assertFalse(window.primary.isEnabled())
        self.assertEqual(window.status_chip.text(), '运行中')
        self.click(window.nav['manage'])
        self.assertFalse(window.reinstall_button.isEnabled())
        self.assertFalse(window.rollback_button.isEnabled())
        self.assertTrue(window.verify_button.isEnabled())
        self.click(window.nav['directories'])
        self.idle()
        page = window.directory_page
        old_key = 'installs/' + first['generation']
        self.assertFalse(page.rows[old_key].flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.capture('game-running')
        (self.engine.root / 'game-session.json').unlink()
        c.refresh_game_status()
        self.assertFalse(c.game_running)
        self.assertEqual(window.primary.text(), '启动游戏')
        self.assertTrue(window.primary.isEnabled())
        self.assertTrue(window.rollback_button.isEnabled())
        self.assertTrue(page.rows[old_key].flags() & Qt.ItemFlag.ItemIsUserCheckable)

    def test_verify_failure_offers_reinstall_repair(self):
        installation = self.install_first()
        binary = self.engine.payload(installation) / installation['executable']
        binary.write_bytes(b'tampered')
        window, c = self.open_window()
        self.click(window.nav['manage'])
        self.click(window.verify_button)
        self.idle()
        self.assertEqual(c.notice.tone, 'error')
        self.assertEqual(c.notice.retry, 'reinstall')
        self.assertEqual(window.task_panel.retry.text(), '重新安装修复')
        self.assertIn('诊断日志', window.task_panel.details.body.toPlainText())
        with patch.object(window, 'confirm', return_value=True):
            self.click(window.task_panel.retry)
            self.idle()
        self.assertEqual(c.notice.title, '安装完成，准备发射')
        self.assertEqual(self.engine.verify(threading.Event()), 2)

    def test_settings_persist_periodic_check_and_notifications(self):
        from rf_updater import preferences
        window, c = self.open_window()
        self.click(window.nav['about'])
        self.assertTrue(window.periodic_checkbox.isChecked())
        self.assertTrue(window.notify_checkbox.isChecked())
        self.assertTrue(window.periodic_timer.isActive())
        window.periodic_checkbox.setChecked(False)
        self.assertFalse(preferences.load_settings()['periodic_check'])
        self.assertFalse(window.periodic_timer.isActive())
        window.notify_checkbox.setChecked(False)
        self.assertFalse(preferences.load_settings()['notifications'])
        window.periodic_checkbox.setChecked(True)
        with patch.object(c, 'check') as check:
            window._periodic_check()
            check.assert_called_once()
        window.periodic_checkbox.setChecked(False)
        with patch.object(c, 'check') as check:
            window._periodic_check()
            check.assert_not_called()
        class FakeTray:
            def __init__(self):
                self.messages = []
            def showMessage(self, *args):
                self.messages.append(args)
        fake = FakeTray()
        window.tray = fake
        window.settings['notifications'] = True
        with patch.object(window, 'isActiveWindow', return_value=False):
            window.notify('标题', '详情', True)
        self.assertEqual(len(fake.messages), 1)
        window.settings['notifications'] = False
        with patch.object(window, 'isActiveWindow', return_value=False):
            window.notify('标题', '详情', True)
        self.assertEqual(len(fake.messages), 1)
        window.tray = None


    def test_language_switch_persistence_and_no_raw_keys(self):
        from rf_updater import preferences
        from PySide6.QtWidgets import QLabel, QPushButton, QCheckBox
        window, c = self.open_window()
        self.click(window.nav['about'])
        combo = window.language_combo
        combo.setCurrentIndex(combo.findData('en'))
        QTest.qWait(50)
        self.assertEqual(window.primary.text(), 'Check for updates')
        self.assertEqual(window.nav['home'].text(), 'Game')
        self.assertIn('Updater', window.windowTitle())
        self.assertEqual(preferences.load_settings()['language'], 'en')
        for widget in window.findChildren(QLabel) + window.findChildren(QPushButton) + window.findChildren(QCheckBox):
            self.assertNotRegex(widget.text(), r'^(gui|task|dir|engine|net|archive|storage|prefs|cli)\.')
        combo.setCurrentIndex(combo.findData('zh-TW'))
        QTest.qWait(50)
        self.assertEqual(window.primary.text(), '檢查更新')
        self.assertEqual(window.nav['home'].text(), '遊戲')
        self.assertEqual(preferences.load_settings()['language'], 'zh-TW')
        window.close()
        self.wait_until(lambda: not window.controller.jobs)
        window.deleteLater()
        QApplication.processEvents()
        self.window = App(self.engine, auto_check=False)
        self.window.show()
        QTest.qWait(60)
        self.assertEqual(self.window.primary.text(), '檢查更新')

    def test_initialization_follows_machine_locale(self):
        from rf_updater import preferences
        preferences.save_settings({"language": None})
        for detected, expected in (("en", "Check for updates"), ("zh-TW", "檢查更新"), ("zh-CN", "检查更新")):
            with patch.object(App, "_system_language", return_value=detected):
                window = App(self.engine, auto_check=False)
                window.show()
                QTest.qWait(60)
                self.assertEqual(window.primary.text(), expected)
                window.close()
                QTest.qWait(60)
                window.deleteLater()
                QApplication.processEvents()
        self.window = None

    def test_locale_change_event_follows_system_only_in_auto_mode(self):
        from rf_updater import preferences, i18n
        from PySide6.QtCore import QEvent
        preferences.save_settings({"language": None})
        with patch.object(App, "_system_language", return_value="zh-CN"):
            window = App(self.engine, auto_check=False)
            window.show()
            QTest.qWait(60)
            self.assertEqual(window.primary.text(), "检查更新")
            with patch.object(App, "_system_language", return_value="en"):
                QApplication.sendEvent(window, QEvent(QEvent.Type.LocaleChange))
                QTest.qWait(50)
                self.assertEqual(window.primary.text(), "Check for updates")
            window.settings["language"] = "zh-TW"
            i18n.use("zh-TW")
            with patch.object(App, "_system_language", return_value="en"):
                QApplication.sendEvent(window, QEvent(QEvent.Type.LocaleChange))
                QTest.qWait(50)
                self.assertEqual(i18n.current(), "zh-TW")
            window.close()
            QTest.qWait(60)
            window.deleteLater()
            QApplication.processEvents()
        self.window = None

    def test_english_layout_at_minimum_size(self):
        from rf_updater import preferences
        from PySide6.QtWidgets import QWidget
        preferences.save_settings({"language": "en"})
        window, c = self.open_window()
        window.resize(900, 640)
        QTest.qWait(80)
        for name in ("home", "manage", "directories", "about"):
            self.click(window.nav[name])
            QTest.qWait(50)
            maximum = window.pages[name].horizontalScrollBar().maximum()
            if maximum:
                wide = [(child.minimumSizeHint().width(), child.metaObject().className(), child.objectName())
                        for child in window.pages[name].widget().findChildren(QWidget)
                        if child.isVisible() and child.minimumSizeHint().width() > 250]
                app_font = QApplication.font()
                button_font = window.primary.font()
                self.fail(f"{name}: horizontal overflow {maximum}px; wide children: {wide}; "
                          f"app font={app_font.family()}/{app_font.pixelSize()}px, "
                          f"button font={button_font.family()}/{button_font.pixelSize()}px, "
                          f"dpr={window.devicePixelRatioF()}, dpi={QApplication.instance().primaryScreen().logicalDotsPerInch()}")
        self.capture("english-small")


if __name__ == '__main__':
    unittest.main()
