"""Shared design tokens for the launcher and its standard Qt dialogs."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from .. import i18n

BG = "#111D2C"
PANEL = "#1A2B3D"
TEXT = "#EDF4FC"
MUTED = "#9FB0C4"
ACCENT = "#58C4E5"
BORDER = "#30465D"
SUCCESS = "#8BCBB9"
WARNING = "#E4B26B"
ERROR = "#F0A7A7"


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    families = set(QFontDatabase.families())
    language = i18n.current()
    if language == "zh-TW":
        candidates = ("Microsoft JhengHei UI", "PingFang TC", "Noto Sans CJK TC", "WenQuanYi Micro Hei")
    elif language == "zh-CN":
        candidates = ("Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei")
    else:
        candidates = ()
    family = next((name for name in candidates if name in families), app.font().family())
    font = QFont(family)
    font.setPointSizeF(10.5)
    app.setFont(font)
    palette = QPalette()
    for role, value in (
        (QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, BG), (QPalette.ColorRole.AlternateBase, PANEL),
        (QPalette.ColorRole.Text, TEXT), (QPalette.ColorRole.Button, PANEL),
        (QPalette.ColorRole.ButtonText, TEXT), (QPalette.ColorRole.Highlight, ACCENT),
        (QPalette.ColorRole.HighlightedText, BG), (QPalette.ColorRole.ToolTipBase, PANEL),
        (QPalette.ColorRole.ToolTipText, TEXT), (QPalette.ColorRole.PlaceholderText, MUTED),
        (QPalette.ColorRole.Link, ACCENT),
    ):
        palette.setColor(role, QColor(value))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#72869C"))
    app.setPalette(palette)
    app.setStyleSheet(STYLE)


STYLE = f"""
QWidget {{ color: {TEXT}; }}
QMainWindow, QWidget#workspace, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QWidget#sidebar {{ background: #0E1926; border-right: 1px solid #24364A; }}
QFrame[panel="true"] {{ background: {PANEL}; border: 1px solid {BORDER}; border-radius: 14px; }}
QLabel {{ background: transparent; border: none; }}
QLabel[role="muted"] {{ color: {MUTED}; }}
QLabel[role="caption"] {{ color: {MUTED}; font-size: 12px; }}
QLabel[role="heading"] {{ font-size: 23px; font-weight: 600; }}
QLabel[role="display"] {{ font-size: 34px; font-weight: 700; }}
QLabel[role="section"] {{ font-size: 17px; font-weight: 600; }}
QLabel[role="brand"] {{ font-size: 18px; font-weight: 700; }}
QLabel[role="chip"] {{ color: {ACCENT}; background: #203A4B; border: 1px solid #345B70; border-radius: 12px; padding: 4px 10px; font-size: 12px; }}
QLabel[tone="success"] {{ color: {SUCCESS}; }}
QLabel[tone="warning"] {{ color: {WARNING}; }}
QLabel[tone="error"] {{ color: {ERROR}; }}
QPushButton {{ background: #22374C; border: 1px solid #3A5066; border-radius: 9px; padding: 9px 15px; min-height: 20px; }}
QPushButton:hover {{ background: #2C455C; border-color: #66839D; }}
QPushButton:pressed {{ background: #1C3045; }}
QPushButton:focus {{ border: 2px solid {ACCENT}; }}
QPushButton:disabled {{ color: #72869C; background: #1B2B3B; border-color: #293D50; }}
QPushButton[variant="primary"] {{ background: {ACCENT}; color: #102131; border: 2px solid {ACCENT}; font-size: 16px; font-weight: 700; padding: 11px 25px; min-height: 24px; }}
QPushButton[variant="primary"]:hover {{ background: #83D8F0; border-color: #83D8F0; }}
QPushButton[variant="primary"]:pressed {{ background: #39ABCD; }}
QPushButton[variant="primary"]:focus {{ border-color: {TEXT}; }}
QPushButton[variant="primary"]:disabled {{ background: #294556; color: #8AA5B6; border-color: #294556; }}
QPushButton[variant="quiet"] {{ background: transparent; border-color: transparent; color: {MUTED}; padding: 7px 9px; }}
QPushButton[variant="quiet"]:hover {{ background: #24384B; color: {TEXT}; }}
QPushButton[variant="quiet"]:focus {{ border-color: {ACCENT}; }}
QPushButton[variant="nav"] {{ background: transparent; color: {MUTED}; border: 1px solid transparent; text-align: left; padding: 12px 15px; }}
QPushButton[variant="nav"]:hover {{ background: #1B2D3F; color: {TEXT}; }}
QPushButton[variant="nav"]:checked {{ background: #203B50; color: {ACCENT}; border-color: #2C536B; }}
QPushButton[variant="nav"]:focus {{ border-color: {ACCENT}; }}
QLineEdit, QPlainTextEdit {{ background: #132233; border: 1px solid {BORDER}; border-radius: 7px; padding: 9px; selection-background-color: {ACCENT}; selection-color: {BG}; }}
QLineEdit:focus, QPlainTextEdit:focus {{ border-color: {ACCENT}; }}
QComboBox {{ background: #132233; border: 1px solid {BORDER}; border-radius: 7px; padding: 9px; min-width: 90px; }}
QComboBox:focus {{ border-color: {ACCENT}; }}
QComboBox:disabled {{ color: #72869C; }}
QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; selection-background-color: #2C455C; }}
QTreeWidget {{ background: #132233; alternate-background-color: #172A3D; border: 1px solid {BORDER}; border-radius: 7px; padding: 3px; selection-background-color: #2C455C; selection-color: {TEXT}; }}
QTreeWidget::item {{ padding: 7px 5px; }}
QHeaderView::section {{ background: #203449; color: {MUTED}; border: none; padding: 8px; text-align: left; }}
QTreeWidget::indicator, QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid #7491AB; border-radius: 3px; background: #132233; }}
QTreeWidget::indicator:checked, QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox {{ spacing: 8px; }}
QProgressBar {{ background: #283F53; border: none; border-radius: 3px; min-height: 6px; max-height: 6px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 3px; }}
QScrollArea {{ border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px 0; }}
QScrollBar::handle:vertical {{ background: #36516A; border-radius: 4px; min-height: 35px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
QToolTip {{ color: {TEXT}; background: {PANEL}; border: 1px solid {BORDER}; padding: 6px; }}
QMessageBox {{ background: {PANEL}; }}
QMessageBox QLabel {{ min-width: 300px; }}
"""
