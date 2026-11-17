"""Visual directory choices, space breakdown, and explicitly selected cleanup."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QRectF, Qt, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QHBoxLayout, QHeaderView, QLineEdit,
    QMessageBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..i18n import t
from ..models import default_root
from ..preferences import choices
from . import theme
from .widgets import Details, Panel, button, label, restyle, size_text

CATEGORIES = (("active", "dir.cat.active", theme.ACCENT), ("previous", "dir.cat.previous", theme.SUCCESS),
              ("old", "dir.cat.old", theme.WARNING), ("cache", "dir.cat.cache", "#8DADF0"),
              ("other", "dir.cat.other", theme.MUTED))


class UsageBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(12)
        self.totals = {}
        self.setAccessibleName(t("dir.usage_access"))

    def set_totals(self, totals):
        self.totals = totals
        self.setAccessibleDescription(t("gui.list_separator").join(f"{t(key)} {size_text(totals.get(cat, 0))}" for cat, key, _ in CATEGORIES))
        self.update()

    def retranslate(self):
        self.setAccessibleName(t("dir.usage_access"))
        self.set_totals(self.totals)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.BORDER))
        total = sum(self.totals.values())
        if total:
            x = 0.0
            for cat, _, color in CATEGORIES:
                width = self.width() * self.totals.get(cat, 0) / total
                painter.fillRect(QRectF(x, 0, width, self.height()), QColor(color))
                x += width
        painter.end()


class DirectoryPage(QWidget):
    request_scan = Signal()
    request_change = Signal(object)
    request_cleanup = Signal(object, bool)
    open_path = Signal(object)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.revision = -1
        self.choice_root = None
        self.running_state = None
        self.rows = {}
        self._static = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(16)
        directory = Panel(padding=16)
        directory.box.setSpacing(8)
        directory.box.addWidget(self._stat("dir.location_title", "section"))
        directory.box.addWidget(self._stat("dir.location_desc", "caption", wrap=True))
        self.path_field = QLineEdit()
        self.path_field.setReadOnly(True)
        self.path_field.setObjectName("storage_current_path")
        self.path_field.setAccessibleName(t("dir.current_path_access"))
        directory.box.addWidget(self.path_field)
        paths = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setObjectName("storage_locations")
        self.combo.setAccessibleName(t("dir.locations_access"))
        self.combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self.combo.currentIndexChanged.connect(self._selection_changed)
        paths.addWidget(self.combo, 1)
        self.switch_button = self._button("dir.switch", "switch_storage_root")
        self.switch_button.clicked.connect(self.switch_selected)
        paths.addWidget(self.switch_button)
        self.choose_button = self._button("dir.choose", "choose_storage_root")
        self.choose_button.clicked.connect(self.choose_directory)
        paths.addWidget(self.choose_button)
        self.default_button = self._button("dir.default", "default_storage_root", variant="quiet")
        self.default_button.clicked.connect(lambda: self.change_to(default_root()))
        paths.addWidget(self.default_button)
        directory.box.addLayout(paths)
        self.space_label = label(t("dir.not_scanned"), "muted", wrap=True)
        self.space_label.setObjectName("storage_space")
        directory.box.addWidget(self.space_label)
        self.usage_bar = UsageBar()
        directory.box.addWidget(self.usage_bar)
        legend = QHBoxLayout()
        self.legend = {}
        for cat, key, color in CATEGORIES:
            item = label(f"{t(key)} —", "caption", wrap=True)
            item.setStyleSheet(f"color: {color};")
            legend.addWidget(item, 1)
            self.legend[cat] = item
        directory.box.addLayout(legend)
        directory.box.addWidget(self._stat("dir.size_note", "caption", wrap=True))
        self.warnings = Details("dir.warnings", "storage_warnings")
        self.warnings.hide()
        directory.box.addWidget(self.warnings)
        box.addWidget(directory)
        content = Panel(padding=16)
        content.box.setSpacing(8)
        actions = QHBoxLayout()
        actions.addWidget(self._stat("dir.content_title", "section"), 1)
        self.refresh_button = self._button("dir.refresh", "refresh_storage")
        self.refresh_button.clicked.connect(self.request_scan)
        actions.addWidget(self.refresh_button)
        self.open_button = self._button("dir.open", "open_storage")
        self.open_button.clicked.connect(self.open_selected)
        actions.addWidget(self.open_button)
        content.box.addLayout(actions)
        self.tree = QTreeWidget()
        self.tree.setObjectName("storage_items")
        self.tree.setAccessibleName(t("dir.tree_access"))
        self.tree.setHeaderLabels([t("dir.col.item"), t("dir.col.status"), t("dir.col.size")])
        self.tree.setColumnCount(3)
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setMinimumHeight(155)
        self.tree.setMaximumHeight(245)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.itemChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda item, column: self.open_selected())
        content.box.addWidget(self.tree)
        self.empty_label = label(t("dir.empty_initial"), "caption", wrap=True)
        content.box.addWidget(self.empty_label)
        self.feedback = label("", "caption", wrap=True)
        self.feedback.hide()
        content.box.addWidget(self.feedback)
        tools = QHBoxLayout()
        self.select_cache_button = self._button("dir.select_cache", "select_storage_cache", variant="quiet")
        self.select_cache_button.clicked.connect(self.select_caches)
        tools.addWidget(self.select_cache_button)
        self.clear_selection_button = self._button("dir.clear_selection", "clear_storage_selection", variant="quiet")
        self.clear_selection_button.clicked.connect(self.clear_selection)
        tools.addWidget(self.clear_selection_button)
        tools.addStretch()
        self.cleanup_button = self._button("dir.cleanup", "cleanup_storage")
        self.cleanup_button.clicked.connect(self.cleanup_selected)
        tools.addWidget(self.cleanup_button)
        content.box.addLayout(tools)
        content.box.addWidget(self._stat("dir.cleanup_note", "caption", wrap=True))
        box.addWidget(content)

    def _stat(self, key, role=None, *, wrap=False):
        widget = label(t(key), role, wrap=wrap)
        self._static.append((widget, key))
        return widget

    def _button(self, key, name, *, variant=None):
        widget = button(t(key), name, variant=variant)
        self._static.append((widget, key))
        return widget

    def retranslate(self):
        for widget, key in self._static:
            widget.setText(t(key))
        self.path_field.setAccessibleName(t("dir.current_path_access"))
        self.combo.setAccessibleName(t("dir.locations_access"))
        self.tree.setAccessibleName(t("dir.tree_access"))
        self.tree.setHeaderLabels([t("dir.col.item"), t("dir.col.status"), t("dir.col.size")])
        self.usage_bar.retranslate()
        self.warnings.retranslate()
        # Rebuild rows so group names, statuses and legends pick up the language.
        self.revision = -1
        self.running_state = None

    def choose_directory(self):
        selected = QFileDialog.getExistingDirectory(self, t("dir.choose_title"), str(self.controller.engine.root),
                                                    QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontUseNativeDialog)
        if selected:
            self.change_to(Path(selected))

    def confirm_switch(self, path):
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("dir.switch_title"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(t("dir.switch_text", path=path))
        accept = dialog.addButton(t("dir.switch_accept"), QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(t("gui.cancel"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        dialog.exec()
        return dialog.clickedButton() is accept

    def change_to(self, path):
        if self.controller.storage_unlocked and self.confirm_switch(path):
            self.request_change.emit(Path(path))

    def switch_selected(self):
        selected = self.combo.currentData()
        if selected:
            self.change_to(Path(selected))

    def selected_items(self):
        inventory = self.controller.inventory
        if not inventory:
            return []
        by_key = {item.key: item for item in inventory.items}
        return [by_key[key] for key, row in self.rows.items() if row.checkState(0) == Qt.CheckState.Checked and key in by_key]

    def confirm_cleanup(self, selected):
        old = any(item.kind == "old" for item in selected)
        dialog = QMessageBox(self)
        dialog.setWindowTitle(t("dir.cleanup_title"))
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(t("dir.cleanup_text", count=len(selected), size=size_text(sum(item.size for item in selected))))
        dialog.setDetailedText("\n".join(str(item.path) for item in selected))
        accept = dialog.addButton(t("dir.cleanup_accept"), QMessageBox.ButtonRole.AcceptRole)
        cancel = dialog.addButton(t("gui.cancel"), QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(cancel)
        if old:
            acknowledgement = QCheckBox(t("dir.backup_ack"))
            dialog.setCheckBox(acknowledgement)
            accept.setEnabled(False)
            acknowledgement.toggled.connect(accept.setEnabled)
        dialog.exec()
        return dialog.clickedButton() is accept

    def cleanup_selected(self):
        selected = self.selected_items()
        if self.controller.game_running and any(item.kind == "old" for item in selected):
            return
        if self.controller.storage_unlocked and selected and self.confirm_cleanup(selected):
            self.request_cleanup.emit([item.key for item in selected], any(item.kind == "old" for item in selected))

    def open_selected(self):
        row = self.tree.currentItem()
        key = row.data(0, Qt.ItemDataRole.UserRole) if row else None
        inventory = self.controller.inventory
        item = next((item for item in inventory.items if item.key == key), None) if inventory else None
        self.open_path.emit(item.path if item and item.path.is_dir() else item.path.parent if item else self.controller.engine.root)

    def select_caches(self):
        inventory = self.controller.inventory
        if inventory:
            for item in inventory.items:
                if item.kind == "cache" and item.deletable:
                    self.rows[item.key].setCheckState(0, Qt.CheckState.Checked)

    def clear_selection(self):
        for row in self.rows.values():
            if row.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                row.setCheckState(0, Qt.CheckState.Unchecked)

    def _selection_changed(self, *args):
        selected = self.selected_items()
        unlocked = self.controller.storage_unlocked
        self.cleanup_button.setEnabled(bool(selected) and unlocked)
        self.cleanup_button.setText(t("dir.cleanup_count", count=len(selected)) if selected else t("dir.cleanup"))
        self.cleanup_button.setToolTip(t("dir.cleanup_tooltip", size=size_text(sum(item.size for item in selected))))
        selected_root = self.combo.currentData()
        self.switch_button.setEnabled(unlocked and bool(selected_root) and Path(selected_root) != self.controller.engine.root)
        self.path_field.setVisible(bool(selected_root) and Path(selected_root) != self.controller.engine.root)

    def render(self):
        controller = self.controller
        root = controller.engine.root
        if self.choice_root != root:
            self.choice_root = root
            self.path_field.setText(str(root))
            self.path_field.setCursorPosition(0)
            with QSignalBlocker(self.combo):
                self.combo.clear()
                for path in choices(root):
                    self.combo.addItem(str(path), str(path))
        unlocked = controller.storage_unlocked
        for item in (self.choose_button, self.default_button, self.combo, self.refresh_button,
                     self.select_cache_button, self.clear_selection_button):
            item.setEnabled(unlocked)
        self.tree.setEnabled(not controller.busy and not controller.closing)
        self.open_button.setEnabled(not controller.closing)
        notice = controller.notice
        self.feedback.setVisible(bool(notice and not controller.busy))
        restyle(self.feedback, "tone", notice.tone if notice else "")
        self.feedback.setText((t("dir.scan_failed_note") if notice and notice.operation == "storage_scan" and notice.tone != "success" and controller.inventory else notice.title if notice else ""))
        if self.revision != controller.storage_revision:
            self.revision = controller.storage_revision
            self.running_state = None
            self._populate(controller.inventory)
        running = controller.game_running
        if self.running_state != running:
            self.running_state = running
            kinds = {item.key: item.kind for item in controller.inventory.items} if controller.inventory else {}
            for key, row in self.rows.items():
                if kinds.get(key) == "old":
                    flags = row.flags()
                    if running:
                        row.setCheckState(0, Qt.CheckState.Unchecked)
                        flags &= ~Qt.ItemFlag.ItemIsUserCheckable
                    else:
                        flags |= Qt.ItemFlag.ItemIsUserCheckable
                    row.setFlags(flags)
        self._selection_changed()

    def _populate(self, inventory):
        self.rows.clear()
        with QSignalBlocker(self.tree):
            self.tree.clear()
            if not inventory:
                self.space_label.setText(t("dir.not_scanned_hint"))
                self.usage_bar.set_totals({})
                for cat, key, _ in CATEGORIES:
                    self.legend[cat].setText(f"{t(key)} —")
                self.empty_label.setText(t("dir.empty_scope"))
                self.empty_label.show()
                self.warnings.hide()
                return
            totals = inventory.totals
            self.space_label.setText(t("dir.space_summary", managed=size_text(sum(totals.values())),
                                       free=size_text(inventory.disk_free), total=size_text(inventory.disk_total)))
            self.usage_bar.set_totals(totals)
            for cat, key, _ in CATEGORIES:
                self.legend[cat].setText(f"{t(key)} {size_text(totals[cat])}")
            self.warnings.setVisible(bool(inventory.warnings))
            self.warnings.set_text("\n".join(inventory.warnings))
            groups = {}
            for key, name in (("cache", t("dir.group.cache")), ("installs", t("dir.group.installs"))):
                group = QTreeWidgetItem([name])
                group.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.tree.addTopLevelItem(group)
                groups[key] = group
            for item in inventory.items:
                row = QTreeWidgetItem([item.name, item.status, size_text(item.size) + ("" if item.complete else "+")])
                flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                if item.deletable:
                    flags |= Qt.ItemFlag.ItemIsUserCheckable
                    row.setCheckState(0, Qt.CheckState.Unchecked)
                row.setFlags(flags)
                row.setData(0, Qt.ItemDataRole.UserRole, item.key)
                row.setToolTip(0, html.escape(str(item.path)))
                if item.kind in {"active", "previous"}:
                    row.setForeground(1, QColor(theme.SUCCESS))
                elif item.kind == "old":
                    row.setForeground(1, QColor(theme.WARNING))
                groups[item.key.split("/")[0]].addChild(row)
                self.rows[item.key] = row
            self.tree.expandAll()
            self.empty_label.setText(t("dir.empty_none") if not inventory.items else t("dir.empty_hint"))
            self.empty_label.setVisible(not inventory.items)
