"""Qt launcher composition. Installation policy lives in Engine."""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QLocale, QTimer, Qt, QTranslator
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QHBoxLayout, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QScrollArea, QSizePolicy, QStackedWidget,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

import PySide6

from . import __version__, i18n
from .engine import Engine
from .i18n import t
from .models import PLATFORMS
from .preferences import load_settings, save_settings
from .runtime import open_external
from .ui import theme
from .ui.controller import Controller
from .ui.directories import DirectoryPage
from .ui.widgets import BrandMark, Details, OrbitArtwork, Panel, TaskPanel, build_text, button, flight_icon, label, restyle, size_text

LANGUAGE_NAMES = {"zh-CN": "简体中文", "zh-TW": "繁體中文", "en": "English"}
PAGE_KEYS = {"home": "gui.page.home", "manage": "gui.page.manage", "directories": "gui.page.directories", "about": "gui.page.about"}


class App(QMainWindow):
    def __init__(self, engine: Engine, *, auto_check=True):
        super().__init__()
        self.engine = engine
        self.settings = load_settings()
        language = self.settings.get("language")
        i18n.use(language if language in i18n.available() else self._system_language())
        self._qt_translator = None
        self._install_qt_translator()
        self.controller = Controller(engine, self)
        self.page = "home"
        self.storage_pending = False
        self._static = []
        self.setObjectName("rf_updater")
        self.setWindowTitle(t("gui.window_title"))
        self.setWindowIcon(flight_icon("brand", theme.ACCENT))
        self.resize(1120, 760)
        self.setMinimumSize(900, 640)
        self._build()
        self.controller.changed.connect(self.refresh)
        self.controller.idle.connect(self._finish_close)
        self.controller.completed.connect(self._operation_finished)
        self.refresh()
        self.auto_check_timer = QTimer(self)
        self.auto_check_timer.setSingleShot(True)
        self.auto_check_timer.timeout.connect(self._auto_check)
        if auto_check:
            self.auto_check_timer.start(500)
        self.periodic_timer = QTimer(self)
        self.periodic_timer.timeout.connect(self._periodic_check)
        self._apply_periodic()
        self.game_timer = QTimer(self)
        self.game_timer.timeout.connect(self.controller.refresh_game_status)
        self.game_timer.start(2000)
        self.tray = None
        self._setup_tray()

    # ---- language -------------------------------------------------------

    def _system_language(self) -> str:
        locale = QLocale.system()
        if locale.script() == QLocale.Script.TraditionalHanScript:
            return "zh-TW"
        return i18n.match_name(locale.name())

    def _install_qt_translator(self):
        application = QApplication.instance()
        if self._qt_translator is not None:
            application.removeTranslator(self._qt_translator)
            self._qt_translator = None
        qt_locale = {"zh-CN": "zh_CN", "zh-TW": "zh_TW", "en": "en"}[i18n.current()]
        directories = [Path(PySide6.__file__).resolve().parent / "Qt" / "translations"]
        if getattr(sys, "frozen", False):
            directories.insert(0, Path(getattr(sys, "_MEIPASS", "")) / "qt-translations")
        translator = QTranslator(self)
        for directory in directories:
            if translator.load(f"qtbase_{qt_locale}", str(directory)):
                application.installTranslator(translator)
                self._qt_translator = translator
                return

    def _apply_language(self, language: str):
        i18n.use(language)
        self._install_qt_translator()
        theme.apply_theme(QApplication.instance())
        self.retranslate()
        self.refresh()

    def event(self, e):
        # Follow the machine locale live while the user keeps "system" selected.
        if e.type() == QEvent.Type.LocaleChange and self.settings.get("language") is None:
            language = self._system_language()
            if language != i18n.current():
                self._apply_language(language)
                self._fill_language_combo()
        return super().event(e)

    def _fill_language_combo(self):
        from PySide6.QtCore import QSignalBlocker
        with QSignalBlocker(self.language_combo):
            self.language_combo.clear()
            detected = LANGUAGE_NAMES[self._system_language()]
            self.language_combo.addItem(t("gui.language_auto", language=detected), None)
            for code, name in LANGUAGE_NAMES.items():
                self.language_combo.addItem(name, code)
            selected = self.settings.get("language")
            index = self.language_combo.findData(selected)
            self.language_combo.setCurrentIndex(index if index >= 0 else 0)

    def _language_changed(self, index):
        selected = self.language_combo.itemData(index)
        self.settings["language"] = selected
        save_settings(self.settings)
        self._apply_language(selected if selected in i18n.available() else self._system_language())
        self._fill_language_combo()

    def retranslate(self):
        self.setWindowTitle(t("gui.window_title"))
        for widget, key, params in self._static:
            widget.setText(t(key, **params))
        self.heading.setText(t(PAGE_KEYS[self.page]))
        self.brand_mark.retranslate()
        self.orbit.retranslate()
        for details in (self.build_details, self.connection_details, self.install_details):
            details.retranslate()
        self.periodic_checkbox.setText(t("gui.periodic_check", hours=self.settings["check_interval_hours"]))
        self.notify_checkbox.setText(t("gui.notifications"))
        self.task_panel.retranslate()
        self.directory_page.retranslate()
        if self.tray is not None:
            self.tray.setToolTip(t("gui.tray_tooltip"))
            self._build_tray_menu()

    # ---- timers / tray ---------------------------------------------------

    def _auto_check(self):
        if QApplication.activeModalWidget() is not None and not self.controller.closing:
            self.auto_check_timer.start(500)
            return
        if not self.controller.closing:
            self.controller.check()

    def _apply_periodic(self):
        if self.settings["periodic_check"]:
            self.periodic_timer.start(self.settings["check_interval_hours"] * 3600 * 1000)
        else:
            self.periodic_timer.stop()

    def _periodic_check(self):
        if self.controller.closing or QApplication.activeModalWidget() is not None:
            return
        if self.settings["periodic_check"] and not self.controller.busy and not self.controller.checking:
            self.controller.check()

    def _save_settings(self):
        self.settings["periodic_check"] = self.periodic_checkbox.isChecked()
        self.settings["notifications"] = self.notify_checkbox.isChecked()
        save_settings(self.settings)
        self._apply_periodic()

    def _setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(flight_icon("brand", theme.ACCENT), self)
        self.tray.setToolTip(t("gui.tray_tooltip"))
        self._build_tray_menu()
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _build_tray_menu(self):
        menu = QMenu(self)
        menu.addAction(t("gui.tray_show")).triggered.connect(self._restore_window)
        menu.addAction(t("gui.check_updates")).triggered.connect(self.controller.check)
        menu.addSeparator()
        menu.addAction(t("gui.tray_quit")).triggered.connect(self.close)
        self.tray.setContextMenu(menu)

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self._restore_window()

    def _restore_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def notify(self, title, detail, success):
        if not self.settings["notifications"] or self.tray is None or self.isActiveWindow():
            return
        icon = QSystemTrayIcon.MessageIcon.Information if success else QSystemTrayIcon.MessageIcon.Critical
        self.tray.showMessage(title, detail, icon, 5000)

    # ---- layout helpers ---------------------------------------------------

    def _tlabel(self, key, role=None, *, wrap=False, **params):
        widget = label(t(key, **params), role, wrap=wrap)
        self._static.append((widget, key, params))
        return widget

    def _tbutton(self, key, name, *, variant=None, **params):
        widget = button(t(key, **params), name, variant=variant)
        self._static.append((widget, key, params))
        return widget

    def _build(self):
        root = QWidget()
        row = QHBoxLayout(root)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        self.setCentralWidget(root)
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(172)
        nav = QVBoxLayout(sidebar)
        nav.setContentsMargins(16, 27, 16, 22)
        nav.setSpacing(7)
        self.brand_mark = BrandMark()
        nav.addWidget(self.brand_mark)
        nav.addSpacing(5)
        nav.addWidget(label("Rocket\nFoundry", "brand"))
        nav.addWidget(self._tlabel("gui.sidebar_caption", "caption"))
        nav.addSpacing(28)
        self.nav = {}
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for name, icon in (("home", "game"), ("manage", "manage"), ("directories", "manage"), ("about", "info")):
            item = self._tbutton(f"gui.nav.{name}", "nav_" + name, variant="nav")
            item.setCheckable(True)
            item.setIcon(flight_icon(icon, theme.MUTED))
            item.clicked.connect(lambda checked=False, key=name: self.show_page(key))
            self.nav_group.addButton(item)
            nav.addWidget(item)
            self.nav[name] = item
        nav.addStretch()
        site = self._tbutton("gui.website", "open_website", variant="quiet")
        site.clicked.connect(lambda: self.open_destination("https://rocketfoundry.net/"))
        nav.addWidget(site)
        nav.addSpacing(6)
        nav.addWidget(self._tlabel("gui.sidebar_version", "caption", version=__version__))
        row.addWidget(sidebar)
        main = QWidget()
        main.setObjectName("workspace")
        box = QVBoxLayout(main)
        box.setContentsMargins(30, 24, 30, 17)
        box.setSpacing(17)
        header = QHBoxLayout()
        self.heading = label(t(PAGE_KEYS["home"]), "heading")
        header.addWidget(self.heading, 1)
        self.platform_label = label(PLATFORMS[self.engine.target][0], "caption")
        header.addWidget(self.platform_label)
        box.addLayout(header)
        self.stack = QStackedWidget()
        self.stack.setObjectName("pages")
        self.pages = {}
        for name in ("home", "manage", "directories", "about"):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            content = QWidget()
            content.setObjectName(name + "_content")
            content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            layout = QVBoxLayout(content)
            layout.setContentsMargins(0, 0, 5, 0)
            layout.setSpacing(16)
            scroll.setWidget(content)
            self.pages[name] = scroll
            self.stack.addWidget(scroll)
        self._home(self.pages["home"].widget().layout())
        self._manage(self.pages["manage"].widget().layout())
        self.directory_page = DirectoryPage(self.controller)
        self.directory_page.request_scan.connect(self.controller.scan_storage)
        self.directory_page.request_change.connect(self.controller.change_directory)
        self.directory_page.request_cleanup.connect(lambda keys, old: self.controller.clean_storage(keys, allow_old=old))
        self.directory_page.open_path.connect(self.open_destination)
        self.pages["directories"].widget().layout().addWidget(self.directory_page)
        self.pages["directories"].widget().layout().addStretch()
        self._about(self.pages["about"].widget().layout())
        box.addWidget(self.stack, 1)
        self.task_panel = TaskPanel()
        self.task_panel.cancel.clicked.connect(self.controller.cancel_task)
        self.task_panel.retry.clicked.connect(self.retry_task)
        self.task_panel.log_button.clicked.connect(self.open_log)
        box.addWidget(self.task_panel)
        box.addWidget(self._tlabel("gui.credit", "caption"))
        row.addWidget(main, 1)
        self.show_page("home")

    def _home(self, box):
        hero = QWidget()
        hero_row = QHBoxLayout(hero)
        hero_row.setContentsMargins(1, 2, 0, 0)
        hero_row.setSpacing(15)
        copy = QVBoxLayout()
        copy.setSpacing(10)
        copy.addStretch()
        copy.addWidget(label("Rocket Foundry", "display"))
        copy.addWidget(self._tlabel("gui.tagline", "muted", wrap=True))
        copy.addStretch()
        hero_row.addLayout(copy, 1)
        self.orbit = OrbitArtwork()
        hero_row.addWidget(self.orbit)
        box.addWidget(hero)
        launch = Panel(padding=20)
        title_row = QHBoxLayout()
        self.install_title = label(t("gui.install_title"), "section")
        title_row.addWidget(self.install_title, 1)
        self.status_chip = label(t("gui.chip_none"), "chip")
        title_row.addWidget(self.status_chip)
        launch.box.addLayout(title_row)
        self.install_description = label(t("gui.desc_none"), "muted", wrap=True)
        launch.box.addWidget(self.install_description)
        actions = QHBoxLayout()
        actions.setSpacing(12)
        self.primary = button(t("gui.primary_check"), "primary_action", variant="primary")
        self.primary.setMinimumWidth(158)
        self.primary.clicked.connect(self.primary_action)
        actions.addWidget(self.primary)
        self.update_button = self._tbutton("gui.update_game", "update_game")
        self.update_button.clicked.connect(self.install)
        actions.addWidget(self.update_button)
        actions.addStretch()
        launch.box.addLayout(actions)
        box.addWidget(launch)
        builds = Panel(padding=18)
        grid = QHBoxLayout()
        grid.setSpacing(18)
        local = QVBoxLayout()
        local.setSpacing(7)
        local_heading = self._tlabel("gui.local_build", "caption")
        local_heading.setFixedHeight(38)
        local.addWidget(local_heading)
        self.local_label = label(t("gui.not_installed"), wrap=True)
        self.local_label.setObjectName("local_build")
        local.addWidget(self.local_label)
        self.local_date = label(t("gui.launch_after_install"), "caption", wrap=True)
        local.addWidget(self.local_date)
        local.addStretch()
        grid.addLayout(local, 1)
        divider = QFrame()
        divider.setFixedWidth(1)
        divider.setStyleSheet(f"background: {theme.BORDER};")
        grid.addWidget(divider)
        remote = QVBoxLayout()
        remote.setSpacing(7)
        remote_header = QHBoxLayout()
        remote_header.addWidget(self._tlabel("gui.remote_build", "caption"), 1)
        self.check_button = button(t("gui.check_updates"), "check_updates", variant="quiet")
        self.check_button.clicked.connect(self.controller.check)
        remote_header.addWidget(self.check_button)
        remote.addLayout(remote_header)
        self.remote_label = label(t("gui.remote_waiting"), wrap=True)
        self.remote_label.setObjectName("remote_build")
        remote.addWidget(self.remote_label)
        self.remote_note = label(t("gui.remote_https"), "caption", wrap=True)
        remote.addWidget(self.remote_note)
        remote.addStretch()
        grid.addLayout(remote, 1)
        builds.box.addLayout(grid)
        self.build_details = Details("gui.build_details", "build_details")
        builds.box.addWidget(self.build_details)
        self.connection_details = Details("gui.connection_details", "connection_details")
        self.connection_details.hide()
        builds.box.addWidget(self.connection_details)
        box.addWidget(builds)
        box.addStretch()

    def _manage(self, box):
        install = Panel(padding=18)
        install.box.setSpacing(8)
        install.box.addWidget(self._tlabel("gui.manage_install", "section"))
        self.manage_status = label(t("gui.manage_none"), "caption", wrap=True)
        install.box.addWidget(self.manage_status)
        install.box.addWidget(self._tlabel("gui.data_dir", "caption"))
        self.path_field = QLineEdit(str(self.engine.root))
        self.path_field.setReadOnly(True)
        self.path_field.setObjectName("data_path")
        self.path_field.setAccessibleName(t("gui.data_dir_access"))
        self.path_field.setCursorPosition(0)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_field, 1)
        self.folder_button = self._tbutton("gui.open_dir", "open_data_directory")
        self.folder_button.clicked.connect(self.open_folder)
        path_row.addWidget(self.folder_button)
        copy = self._tbutton("gui.copy", "copy_data_path")
        copy.setAccessibleName(t("gui.copy_access"))
        copy.clicked.connect(self.copy_path)
        path_row.addWidget(copy)
        self.copy_feedback = label("", "caption")
        self.copy_timer = QTimer(self)
        self.copy_timer.setSingleShot(True)
        self.copy_timer.timeout.connect(self.copy_feedback.clear)
        path_row.addWidget(self.copy_feedback)
        install.box.addLayout(path_row)
        self.install_details = Details("gui.install_details", "install_details")
        install.box.addWidget(self.install_details)
        box.addWidget(install)
        maintenance = Panel(padding=18)
        maintenance.box.setSpacing(10)
        maintenance.box.addWidget(self._tlabel("gui.maintenance", "section"))
        self.verify_button = self._maintenance_row(maintenance, "gui.verify_title", "gui.verify_desc", "gui.verify_action", "verify_files", self.controller.verify)
        self.reinstall_button = self._maintenance_row(maintenance, "gui.reinstall_title", "gui.reinstall_desc", "gui.reinstall_action", "reinstall_game", self.reinstall)
        self.rollback_button = self._maintenance_row(maintenance, "gui.rollback_title", "gui.rollback_desc", "gui.rollback_action", "rollback_game", self.rollback)
        box.addWidget(maintenance)
        box.addWidget(self._tlabel("gui.manage_note", "caption", wrap=True))
        box.addStretch()

    def _maintenance_row(self, panel, title_key, description_key, action_key, name, callback):
        row = QHBoxLayout()
        copy = QVBoxLayout()
        copy.setSpacing(5)
        copy.addWidget(self._tlabel(title_key))
        copy.addWidget(self._tlabel(description_key, "caption", wrap=True))
        row.addLayout(copy, 1)
        item = self._tbutton(action_key, name)
        item.clicked.connect(callback)
        row.addWidget(item)
        panel.box.addSpacing(4)
        panel.box.addLayout(row)
        return item

    def _about(self, box):
        about = Panel()
        about.box.addWidget(self._tlabel("gui.about_heading", "heading"))
        about.box.addWidget(self._tlabel("gui.about_version", "muted", version=__version__))
        about.box.addWidget(self._tlabel("gui.about_desc", wrap=True))
        site = self._tbutton("gui.about_website", "about_website")
        site.clicked.connect(lambda: self.open_destination("https://rocketfoundry.net/play/"))
        about.box.addWidget(site, 0, Qt.AlignmentFlag.AlignLeft)
        box.addWidget(about)
        support = Panel()
        support.box.addWidget(self._tlabel("gui.platform_title", "section"))
        support.box.addWidget(self._tlabel("gui.platform_line", wrap=True))
        support.box.addWidget(self._tlabel("gui.mobile_line", "muted", wrap=True))
        support.box.addWidget(self._tlabel("gui.identity_line", "muted", wrap=True))
        box.addWidget(support)
        integrity = Panel()
        integrity.box.addWidget(self._tlabel("gui.integrity_title", "section"))
        integrity.box.addWidget(self._tlabel("gui.integrity_1", "muted", wrap=True))
        integrity.box.addWidget(self._tlabel("gui.integrity_2", "muted", wrap=True))
        box.addWidget(integrity)
        automation = Panel()
        automation.box.addWidget(self._tlabel("gui.automation_title", "section"))
        self.periodic_checkbox = QCheckBox(t("gui.periodic_check", hours=self.settings["check_interval_hours"]))
        self.periodic_checkbox.setObjectName("periodic_check")
        self.periodic_checkbox.setChecked(self.settings["periodic_check"])
        self.periodic_checkbox.toggled.connect(self._save_settings)
        automation.box.addWidget(self.periodic_checkbox)
        self.notify_checkbox = QCheckBox(t("gui.notifications"))
        self.notify_checkbox.setObjectName("desktop_notifications")
        self.notify_checkbox.setChecked(self.settings["notifications"])
        self.notify_checkbox.toggled.connect(self._save_settings)
        automation.box.addWidget(self.notify_checkbox)
        automation.box.addWidget(self._tlabel("gui.automation_note", "caption", wrap=True))
        box.addWidget(automation)
        language = Panel()
        language.box.addWidget(self._tlabel("gui.language_title", "section"))
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("language_choice")
        self.language_combo.setAccessibleName(t("gui.language_title"))
        self._fill_language_combo()
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        language.box.addWidget(self.language_combo)
        language.box.addWidget(self._tlabel("gui.language_note", "caption", wrap=True))
        box.addWidget(language)
        box.addWidget(self._tlabel("gui.license", "caption", wrap=True))
        box.addStretch()

    # ---- pages / state ----------------------------------------------------

    def show_page(self, name):
        self.page = name
        self.stack.setCurrentWidget(self.pages[name])
        self.nav[name].setChecked(True)
        self.heading.setText(t(PAGE_KEYS[name]))
        if name == "directories" and self.controller.inventory is None:
            self.storage_pending = True
            self._maybe_scan_storage()
        if hasattr(self, "task_panel"):
            self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "orbit"):
            self.orbit.setVisible(self.width() >= 1040)

    def refresh(self):
        c = self.controller
        self.engine = c.engine
        active, release = c.active, c.release
        running = c.game_running
        self.primary.setEnabled(c.can_launch if active else (not c.busy and not c.checking and not c.closing and not c.state_error))
        self.primary.setText(t("gui.primary_running") if active and running else t("gui.primary_launch") if active else t("gui.primary_checking") if c.checking else t("gui.primary_install") if release else t("gui.primary_recheck") if c.check_error else t("gui.primary_check"))
        self.primary.setIcon(flight_icon("play", "#102131") if active else flight_icon("game", "#102131"))
        self.update_button.setVisible(bool(active and release and c.remote_status == "available"))
        self.update_button.setEnabled(c.can_install)
        self.check_button.setEnabled(not c.checking and not c.busy and not c.closing)
        self.check_button.setText(t("gui.checking") if c.checking else t("gui.recheck") if c.check_error else t("gui.check_updates"))
        available = c.remote_status == "available" and release is not None
        self.install_title.setText(t("gui.installed_title") if active else t("gui.install_title"))
        self.status_chip.setText(t("gui.chip_state_error") if c.state_error else t("gui.chip_running") if active and running else t("gui.chip_update") if active and available else t("gui.chip_installed") if active else t("gui.chip_none"))
        self.install_description.setText(t("gui.desc_running") if active and running else
                                         t("gui.desc_update") if active and available else
                                         t("gui.desc_active") if active else t("gui.desc_none"))
        self.local_label.setText(build_text(active["release"]) if active else t("gui.not_installed"))
        self.local_date.setText(t("gui.installed_on", date=active['installed_at'][:10]) if active else t("gui.launch_after_install"))
        restyle(self.remote_label, "tone", "error" if c.check_error else "")
        if c.checking:
            self.remote_label.setText(t("gui.remote_checking"))
            self.remote_note.setText(t("gui.remote_checking_note"))
        elif c.check_error:
            self.remote_label.setText(t("gui.remote_offline"))
            self.remote_note.setText(t("gui.remote_offline_note"))
        elif release:
            self.remote_label.setText(build_text(release))
            status = {"current": t("gui.remote_current"), "available": t("gui.remote_available"), "unknown": t("gui.remote_unknown")}.get(c.remote_status, t("gui.remote_latest"))
            self.remote_note.setText(t("gui.remote_note_format", status=status, size=size_text(release.size)))
        else:
            self.remote_label.setText(t("gui.remote_waiting"))
            self.remote_note.setText(t("gui.remote_https"))
        detail = self._installation_detail(active)
        if release:
            detail += t("gui.build_details_remote", url=release.url, etag=release.etag or t("gui.not_provided"),
                        modified=release.modified or t("gui.not_provided"), sha256=release.sha256 or t("gui.not_provided"))
        self.build_details.set_text(detail)
        self.connection_details.setVisible(bool(c.check_error))
        self.connection_details.set_text(c.check_error or "")
        self.manage_status.setText(t("gui.manage_status", build=build_text(active['release']), date=active['installed_at'][:10]) if active else t("gui.manage_none") if not c.state_error else t("gui.manage_state_error"))
        self.install_details.set_text(self._installation_detail(active))
        unlocked = not c.busy and not c.checking and not c.closing and not c.state_error
        self.verify_button.setEnabled(bool(active and unlocked))
        self.reinstall_button.setEnabled(unlocked and not running)
        self.rollback_button.setEnabled(bool(c.previous and unlocked and not running))
        self.folder_button.setEnabled(not c.closing)
        if self.path_field.text() != str(self.engine.root):
            self.path_field.setText(str(self.engine.root))
            self.path_field.setCursorPosition(0)
        self.directory_page.render()
        self.task_panel.render(c)
        self.task_panel.setVisible(self.page != "directories" or c.busy or c.checking or c.closing
                                   or bool(c.state_error or c.check_error)
                                   or bool(c.notice and c.notice.tone != "success"))

    def _installation_detail(self, active):
        text = t("gui.detail_root", root=self.engine.root)
        if not active:
            return text + t("gui.detail_none")
        release = active["release"]
        scope = t("gui.scope_official") if active.get("publisher_checksum") else t("gui.scope_local")
        return t("gui.detail_full", root=self.engine.root, payload=self.engine.payload(active),
                 generation=active["generation"], sha=active.get("package_sha256", t("gui.not_provided")),
                 etag=release.get("etag") or t("gui.not_provided"), modified=release.get("modified") or t("gui.not_provided"),
                 scope=scope) + t("gui.detail_note")

    # ---- actions ----------------------------------------------------------

    def primary_action(self):
        if self.controller.active:
            self.controller.launch()
        elif self.controller.release:
            self.install()
        else:
            self.controller.check()

    def install(self):
        self.controller.install()

    def confirm(self, title, text, accept):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(title)
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(text)
        proceed = dialog.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(t("gui.cancel"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is proceed

    def reinstall(self):
        if self.confirm(t("gui.reinstall_confirm_title"), t("gui.reinstall_confirm_text"), t("gui.reinstall_action")):
            self.controller.install(reinstall=True)

    def rollback(self):
        if self.confirm(t("gui.rollback_confirm_title"), t("gui.rollback_confirm_text"), t("gui.rollback_confirm_accept")):
            self.controller.rollback()

    def retry_task(self):
        notice = self.controller.notice
        if notice and notice.retry == "rollback":
            self.rollback()
        elif notice and notice.retry == "reinstall" and notice.tone != "warning":
            self.reinstall()
        else:
            self.controller.retry()

    def copy_path(self):
        QApplication.clipboard().setText(str(self.engine.root))
        self.copy_feedback.setText(t("gui.copied"))
        self.copy_timer.start(2500)

    def open_folder(self):
        try:
            self.engine.root.mkdir(parents=True, exist_ok=True)
            self.open_destination(self.engine.root)
        except OSError as exc:
            self._open_error(str(exc))

    def open_log(self):
        log = self.engine.root / "logs/game.log"
        if log.exists():
            self.open_destination(log)
        else:
            self._open_error(t("gui.no_log"))

    def _open_error(self, text):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("gui.open_error_title"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(text)
        dialog.addButton(t("gui.ok"), QMessageBox.ButtonRole.AcceptRole)
        dialog.exec()

    def open_destination(self, destination: str | Path):
        try:
            open_external(destination)
        except OSError as exc:
            self._open_error(str(exc))

    def closeEvent(self, event: QCloseEvent):
        self.auto_check_timer.stop()
        self.copy_timer.stop()
        self.periodic_timer.stop()
        self.game_timer.stop()
        if self.controller.jobs:
            event.ignore()
            self.controller.shutdown()
        else:
            if self.tray is not None:
                self.tray.hide()
            event.accept()

    def _finish_close(self):
        if self.controller.closing:
            self.close()
        else:
            self._maybe_scan_storage()

    def _operation_finished(self, operation, success):
        if operation == "install" or success and operation in {"rollback", "directory"}:
            self.storage_pending = True
        notice = self.controller.notice
        if notice and operation in {"install", "verify", "rollback", "cleanup"}:
            self.notify(notice.title, notice.detail, success)

    def _maybe_scan_storage(self):
        if self.page == "directories" and self.storage_pending and self.controller.storage_unlocked:
            self.storage_pending = False
            self.controller.scan_storage(preserve_notice=True)


def launch_gui(engine: Engine):
    application = QApplication.instance() or QApplication([sys.argv[0]])
    application.setApplicationName("RF-Updater")
    application.setDesktopFileName("rf-updater-community")
    application.setApplicationVersion(__version__)
    theme.apply_theme(application)
    window = App(engine)
    window.show()
    application.exec()
