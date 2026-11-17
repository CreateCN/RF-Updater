"""Small accessible Qt widgets and code-drawn spaceflight artwork."""
from __future__ import annotations

from email.utils import parsedate_to_datetime

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from ..i18n import t
from . import theme


def label(text="", role=None, *, wrap=False) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text, name, *, variant=None) -> QPushButton:
    widget = QPushButton(text)
    widget.setObjectName(name)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if variant:
        widget.setProperty("variant", variant)
    return widget


def restyle(widget, key, value):
    if widget.property(key) != value:
        widget.setProperty(key, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


def size_text(value) -> str:
    if value is None:
        return t("gui.size_unknown")
    value = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return ""


def build_text(release) -> str:
    if not release:
        return t("gui.build_unchecked")
    modified = release.get("modified") if isinstance(release, dict) else release.modified
    if modified:
        try:
            return parsedate_to_datetime(modified).astimezone().strftime("%Y-%m-%d %H:%M")
        except (ValueError, TypeError, OverflowError):
            pass
    if isinstance(release, dict):
        from ..models import Release
        release = Release(**release)
    return t("gui.build_id", id=release.identity[:8]) if release.comparable else t("gui.build_no_identity")


class Panel(QFrame):
    def __init__(self, parent=None, *, padding=22):
        super().__init__(parent)
        self.setProperty("panel", True)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(padding, padding, padding, padding)
        self.box.setSpacing(12)


class Details(QWidget):
    def __init__(self, key="gui.details", name="details", parent=None):
        super().__init__(parent)
        self.key = key
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.toggle = button(t(key), name, variant="quiet")
        self.toggle.setCheckable(True)
        self.toggle.setAccessibleDescription(t("gui.details_access"))
        self.toggle.clicked.connect(self._toggle)
        box.addWidget(self.toggle, 0, Qt.AlignmentFlag.AlignLeft)
        self.body = QPlainTextEdit()
        self.body.setObjectName(name + "_text")
        self.body.setReadOnly(True)
        self.body.setFixedHeight(108)
        self.body.setAccessibleName(t(key))
        self.body.hide()
        box.addWidget(self.body)

    @property
    def collapsed_text(self):
        return t(self.key)

    def _toggle(self, checked):
        self.body.setVisible(checked)
        self.toggle.setText(t("gui.details_collapse") if checked else t(self.key))

    def set_text(self, text):
        if self.body.toPlainText() != text:
            self.body.setPlainText(text)

    def retranslate(self):
        self.toggle.setAccessibleDescription(t("gui.details_access"))
        self.body.setAccessibleName(t(self.key))
        self.toggle.setText(t("gui.details_collapse") if self.toggle.isChecked() else t(self.key))


def flight_icon(kind="play", color=theme.TEXT) -> QIcon:
    pixmap = QPixmap(256, 256)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(4, 4)
    painter.setPen(QPen(QColor(color), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    if kind == "play":
        painter.setBrush(QColor(color))
        path = QPainterPath(QPointF(23, 15))
        path.lineTo(47, 32)
        path.lineTo(23, 49)
        path.closeSubpath()
        painter.drawPath(path)
    elif kind == "game":
        painter.drawEllipse(QRectF(12, 12, 40, 40))
        painter.drawArc(QRectF(4, 24, 56, 16), 20 * 16, 300 * 16)
        painter.setBrush(QColor(color))
        painter.drawEllipse(QPointF(46, 18), 4, 4)
    elif kind == "manage":
        for x, y in ((17, 24), (32, 40), (47, 20)):
            painter.drawLine(x, 13, x, 51)
            painter.setBrush(QColor(theme.BG))
            painter.drawEllipse(QPointF(x, y), 5, 5)
    elif kind == "info":
        painter.drawEllipse(QRectF(12, 12, 40, 40))
        painter.drawLine(32, 29, 32, 44)
        painter.drawPoint(32, 21)
    else:
        painter.drawEllipse(QRectF(8, 8, 48, 48))
        path = QPainterPath(QPointF(32, 3))
        path.lineTo(43, 39)
        path.lineTo(32, 32)
        path.lineTo(21, 39)
        path.closeSubpath()
        painter.setBrush(QColor(color))
        painter.drawPath(path)
    painter.end()
    return QIcon(pixmap)


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(45, 45)
        self.icon = flight_icon("brand", theme.ACCENT)
        self.setAccessibleName(t("gui.brand_access"))

    def retranslate(self):
        self.setAccessibleName(t("gui.brand_access"))

    def paintEvent(self, event):
        painter = QPainter(self)
        self.icon.paint(painter, self.rect())
        painter.end()


class OrbitArtwork(QWidget):
    """Quiet schematic of a craft on an elliptical Earth orbit, with no animation."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(220, 110)
        self.setAccessibleName(t("gui.orbit_access"))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def retranslate(self):
        self.setAccessibleName(t("gui.orbit_access"))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width() / 256, self.height() / 150)
        painter.translate((self.width() - 256 * scale) / 2, (self.height() - 150 * scale) / 2)
        painter.scale(scale, scale)
        painter.setPen(QPen(QColor("#254357"), 1))
        for x, y in ((14, 29), (238, 17), (207, 134), (51, 116), (220, 47), (106, 12)):
            painter.drawLine(x-2, y, x+2, y)
            painter.drawLine(x, y-2, x, y+2)
        painter.translate(144, 81)
        painter.rotate(-21)
        painter.setPen(QPen(QColor(theme.BORDER), 1, Qt.PenStyle.DashLine))
        painter.drawEllipse(QRectF(-113, -53, 226, 106))
        painter.setPen(QPen(QColor("#477B92"), 1.3))
        painter.drawArc(QRectF(-113, -53, 226, 106), 40 * 16, 160 * 16)
        painter.rotate(21)
        light = QLinearGradient(-35, -30, 30, 35)
        light.setColorAt(0, QColor("#72AAC6"))
        light.setColorAt(.48, QColor("#3D718F"))
        light.setColorAt(1, QColor("#1F3A52"))
        painter.setBrush(light)
        painter.setPen(QPen(QColor("#638FA9"), 1))
        painter.drawEllipse(QPointF(0, 0), 36, 36)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#8DB7CC"), .7))
        painter.drawEllipse(QRectF(-19, -36, 38, 72))
        painter.drawArc(QRectF(-36, -14, 72, 28), 0, 180*16)
        painter.drawArc(QRectF(-36, -25, 72, 50), 180*16, 180*16)
        painter.drawLine(-34, 0, 34, 0)
        painter.translate(-86, -21)
        painter.rotate(39)
        craft = QPainterPath(QPointF(0, -14))
        craft.lineTo(7, 9)
        craft.lineTo(0, 5)
        craft.lineTo(-7, 9)
        craft.closeSubpath()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.TEXT))
        painter.drawPath(craft)
        painter.setPen(QPen(QColor(theme.ACCENT), 2))
        painter.drawLine(0, 11, 0, 19)
        painter.end()


PHASES = {"prepare": "task.phase.prepare", "download": "task.phase.download", "verify": "task.phase.verify",
          "extract": "task.phase.extract", "activate": "task.phase.activate", "verify_files": "task.phase.verify_files",
          "complete": "task.phase.complete", "storage_scan": "task.phase.storage_scan", "retry": "task.phase.retry"}

PREPARE_TITLES = {"install": "task.prepare.install", "verify": "task.prepare.verify", "rollback": "task.prepare.rollback",
                  "launch": "task.prepare.launch", "storage_scan": "task.prepare.storage_scan",
                  "directory": "task.prepare.directory", "cleanup": "task.prepare.cleanup"}


class TaskPanel(Panel):
    def __init__(self, parent=None):
        super().__init__(parent, padding=18)
        self.setObjectName("task_panel")
        row = QHBoxLayout()
        self.title = label(t("task.idle_title"), "section")
        self.title.setObjectName("task_title")
        row.addWidget(self.title, 1)
        self.percent = label("", "caption")
        row.addWidget(self.percent)
        self.cancel = button(t("task.cancel"), "cancel_task")
        self.cancel.hide()
        row.addWidget(self.cancel)
        self.retry = button(t("task.retry"), "retry_task")
        self.retry.hide()
        row.addWidget(self.retry)
        self.log_button = button(t("task.open_log"), "open_log")
        self.log_button.hide()
        row.addWidget(self.log_button)
        self.box.addLayout(row)
        self.description = label(t("task.idle_desc"), "muted", wrap=True)
        self.description.setObjectName("task_description")
        self.box.addWidget(self.description)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 1000)
        self.bar.setValue(0)
        self.bar.setAccessibleName(t("task.progress_access"))
        self.bar.hide()
        self.box.addWidget(self.bar)
        phases = QWidget()
        line = QHBoxLayout(phases)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(18)
        self.stages = {}
        for phase in ("download", "verify", "extract", "complete"):
            item = label(t(f"task.stage.{phase}"), "caption")
            self.stages[phase] = item
            line.addWidget(item)
        line.addStretch()
        self.metrics = label("", "caption")
        line.addWidget(self.metrics)
        self.phases = phases
        self.phases.hide()
        self.box.addWidget(phases)
        self.details = Details("task.error_details", "task_details")
        self.details.hide()
        self.box.addWidget(self.details)

    def retranslate(self):
        self.cancel.setText(t("task.cancel"))
        self.retry.setText(t("task.retry"))
        self.log_button.setText(t("task.open_log"))
        self.bar.setAccessibleName(t("task.progress_access"))
        for phase, item in self.stages.items():
            item.setText(t(f"task.stage.{phase}"))
        self.details.retranslate()

    def render(self, controller):
        self.cancel.setVisible(controller.busy and controller.operation in {"install", "verify", "storage_scan"})
        self.cancel.setEnabled(not controller.cancelling and not controller.closing)
        self.cancel.setText(t("task.cancelling") if controller.cancelling else t("task.cancel"))
        self.retry.hide()
        self.log_button.hide()
        self.details.hide()
        self.phases.hide()
        self.bar.hide()
        self.percent.clear()
        restyle(self.title, "tone", "")
        self.metrics.clear()
        if controller.closing:
            self.title.setText(t("task.closing_title"))
            self.description.setText(t("task.closing_desc"))
            self.cancel.hide()
            return
        if controller.busy:
            progress = controller.progress
            title = t(PHASES[progress.phase]) if progress.phase != "prepare" else t(PREPARE_TITLES[controller.operation])
            self.title.setText(title)
            self.description.setText(t("task.cancel_wait") if controller.cancelling else t("task.background"))
            if controller.operation in {"install", "verify"}:
                self.bar.show()
                if progress.phase == "retry":
                    self.bar.setRange(0, 0)
                    self.metrics.setText(t("task.retry_metrics", attempt=progress.done))
                elif progress.total:
                    self.bar.setRange(0, 1000)
                    self.bar.setValue(min(1000, round(progress.done / progress.total * 1000)))
                    self.percent.setText(f"{min(100, progress.done / progress.total * 100):.0f}%")
                    if progress.phase != "activate":
                        self.metrics.setText(f"{size_text(progress.done)} / {size_text(progress.total)}")
                else:
                    self.bar.setRange(0, 0)
                if progress.speed:
                    self.metrics.setText(self.metrics.text() + f"  ·  {size_text(progress.speed)}/s")
                if controller.operation == "install":
                    self.phases.show()
                    active_phase = "complete" if progress.phase == "activate" else progress.phase
                    for phase, item in self.stages.items():
                        restyle(item, "tone", "success" if phase == active_phase else "")
            return
        notice = controller.notice
        if notice:
            self.title.setText(notice.title)
            restyle(self.title, "tone", notice.tone)
            if notice.retry:
                description = {
                    "storage_scan": t("task.retry_desc.storage_scan"),
                    "directory": t("task.retry_desc.directory"),
                    "cleanup": t("task.retry_desc.cleanup"),
                }.get(notice.operation)
                self.description.setText(description or (t("task.retry_desc.installed") if controller.active else t("task.retry_desc.default")))
                self.details.set_text(notice.detail)
                self.details.show()
                self.retry.setText(t("task.retry_continue") if notice.tone == "warning" and notice.operation == "install" else
                                   t("task.retry_repair") if notice.operation == "verify" and notice.retry == "reinstall" else
                                   t("task.retry_refresh_list") if notice.retry == "scan_storage" and notice.operation != "storage_scan" else
                                   t("task.retry_rescan") if notice.retry == "scan_storage" else t("task.retry"))
                self.retry.setEnabled(not controller.checking and not controller.closing)
                self.retry.show()
            else:
                self.description.setText(notice.detail)
                if notice.operation in {"install", "verify"}:
                    self.bar.show()
                    self.bar.setRange(0, 1000)
                    self.bar.setValue(1000)
                    self.percent.setText("100%")
                if notice.operation == "launch":
                    self.log_button.show()
            return
        if controller.state_error or controller.check_error:
            self.title.setText(t("task.state_error_title") if controller.state_error else t("task.check_error_title"))
            restyle(self.title, "tone", "error")
            self.description.setText(t("task.state_error_desc") if controller.state_error else t("task.check_error_desc"))
            self.details.set_text(controller.state_error or controller.check_error)
            self.details.show()
            self.retry.setEnabled(not controller.checking)
            self.retry.show()
        elif controller.checking:
            self.title.setText(t("task.checking_title"))
            self.description.setText(t("task.checking_desc_installed") if controller.active else t("task.checking_desc"))
        else:
            self.title.setText(t("task.ready_title") if controller.active else t("task.idle_title"))
            self.description.setText(t("task.ready_desc") if controller.active else t("task.idle_desc2"))
