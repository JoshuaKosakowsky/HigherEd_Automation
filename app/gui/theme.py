"""Mines digital palette and shared Qt presentation primitives."""

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QFrame, QVBoxLayout

DARK_BLUE = "#21314D"
BLASTER_BLUE = "#09396C"
LIGHT_BLUE = "#879EC3"
COLORADO_RED = "#CC4628"
PALE_BLUE = "#CFDCE9"
WHITE = "#FFFFFF"
LIGHT_GRAY = "#AEB3B8"
SILVER = "#81848A"
DARK_GRAY = "#75757D"
EARTH_BLUE = "#0272DE"
MUTED_BLUE = "#57A2BD"
ENERGY_YELLOW = "#F0F600"
GOLDEN_TECH = "#F1B91A"
ENVIRONMENT_GREEN = "#80C342"
RED_FLANNEL = "#B42024"
PAGE = "#F4F6F9"
CARD = WHITE
TEXT = DARK_BLUE
MUTED = "#526078"
SUCCESS = BLASTER_BLUE
WARNING = COLORADO_RED
ERROR = RED_FLANNEL


def label(text: str, role: str = "", *, wrap: bool = True) -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(wrap)
    if role:
        widget.setObjectName(role)
    return widget


def button(text: str, callback, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    widget.setMinimumHeight(38)
    if role:
        widget.setObjectName(role)
    widget.clicked.connect(callback)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(24, 22, 24, 22)
    layout.setSpacing(12)
    return frame, layout


def apply_theme(application: QApplication) -> None:
    """Use a consistent light workspace, including on dark-mode desktops."""
    application.setStyle("Fusion")
    application.setFont(QFont("Segoe UI" if sys.platform == "win32" else "Arial", 11))
    palette = QPalette()
    for role, color in (
        (QPalette.ColorRole.Window, PAGE),
        (QPalette.ColorRole.WindowText, TEXT),
        (QPalette.ColorRole.Base, WHITE),
        (QPalette.ColorRole.AlternateBase, PAGE),
        (QPalette.ColorRole.Text, TEXT),
        (QPalette.ColorRole.Button, WHITE),
        (QPalette.ColorRole.ButtonText, TEXT),
        (QPalette.ColorRole.Highlight, BLASTER_BLUE),
        (QPalette.ColorRole.HighlightedText, WHITE),
        (QPalette.ColorRole.ToolTipBase, WHITE),
        (QPalette.ColorRole.ToolTipText, TEXT),
    ):
        palette.setColor(role, QColor(color))
    application.setPalette(palette)
    application.setStyleSheet(f"""
        QWidget {{ color: {TEXT}; }}
        QMainWindow, QScrollArea, QWidget#page {{ background: {PAGE}; }}
        QScrollArea {{ border: none; }}
        QLabel {{ background: transparent; }}
        QLabel#title {{ font-size: 28px; font-weight: 700; }}
        QLabel#section {{ font-size: 18px; font-weight: 700; }}
        QLabel#eyebrow {{ color: {BLASTER_BLUE}; font-size: 11px; font-weight: 700; }}
        QLabel#muted {{ color: {MUTED}; }}
        QLabel#field {{ font-weight: 600; }}
        QLabel#warning {{ color: {COLORADO_RED}; background: {WHITE};
            border-left: 3px solid {COLORADO_RED}; padding: 12px; }}
        QLabel#error {{ color: {RED_FLANNEL}; padding: 4px 0; }}
        QLabel#status {{ background: {PALE_BLUE}; border-radius: 8px; padding: 14px; }}
        QFrame#card {{ background: {WHITE}; border: 1px solid {PALE_BLUE}; border-radius: 12px; }}
        QFrame#sidebar {{ background: {DARK_BLUE}; }}
        QFrame#sidebar QLabel {{ color: {PALE_BLUE}; }}
        QFrame#sidebar QLabel#brand {{ color: {WHITE}; font-size: 25px; font-weight: 800; }}
        QFrame#sidebar QLabel#brandLogo {{ background: {WHITE}; border-radius: 6px; }}
        QFrame#sidebar QLabel#sideTitle {{ color: {WHITE}; font-size: 16px; font-weight: 600; }}
        QFrame#sidebar QLabel#institution {{ font-size: 10px; }}
        QPushButton {{ background: {WHITE}; border: 1px solid {LIGHT_BLUE};
            border-radius: 7px; padding: 8px 14px; font-weight: 600; }}
        QPushButton:hover {{ background: {PALE_BLUE}; border-color: {BLASTER_BLUE}; }}
        QPushButton:focus {{ border: 2px solid {EARTH_BLUE}; }}
        QPushButton:disabled {{ color: {DARK_GRAY}; background: {PAGE}; border-color: {PALE_BLUE}; }}
        QPushButton#primary {{ background: {BLASTER_BLUE}; color: {WHITE}; border: 1px solid {BLASTER_BLUE}; }}
        QPushButton#primary:hover {{ background: {DARK_BLUE}; }}
        QPushButton#primary:disabled {{ background: {LIGHT_GRAY}; border-color: {LIGHT_GRAY}; }}
        QPushButton#nav {{ background: transparent; color: {PALE_BLUE}; border: none;
            text-align: left; padding: 12px; }}
        QPushButton#nav:hover, QPushButton#nav:checked {{ background: {BLASTER_BLUE}; color: {WHITE}; }}
        QPushButton#nav:focus {{ border: 1px solid {LIGHT_BLUE}; }}
        QLineEdit, QPlainTextEdit, QComboBox {{
            background: {WHITE}; color: {TEXT}; border: 1px solid {LIGHT_BLUE};
            border-radius: 6px; padding: 9px; selection-background-color: {BLASTER_BLUE};
            selection-color: {WHITE}; }}
        QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{ border: 2px solid {BLASTER_BLUE}; }}
        QLineEdit[invalid="true"], QPlainTextEdit[invalid="true"] {{ border: 2px solid {RED_FLANNEL}; }}
        QFrame#fileInput {{ border: 1px dashed {LIGHT_BLUE}; border-radius: 8px; background: {PAGE}; }}
        QFrame#fileInput[dragging="true"] {{ border: 2px solid {BLASTER_BLUE}; background: {PALE_BLUE}; }}
        QTableWidget {{ background: {WHITE}; alternate-background-color: {PAGE};
            border: 1px solid {PALE_BLUE}; border-radius: 8px; gridline-color: {PALE_BLUE};
            selection-background-color: {PALE_BLUE}; selection-color: {DARK_BLUE}; }}
        QHeaderView::section {{ background: {PALE_BLUE}; color: {DARK_BLUE};
            padding: 12px 8px; border: none; font-weight: 600; }}
        QTableWidget::item {{ padding: 8px; }}
        QProgressBar {{ background: {PALE_BLUE}; border: none; border-radius: 4px; max-height: 7px; }}
        QProgressBar::chunk {{ background: {BLASTER_BLUE}; border-radius: 4px; }}
        QCheckBox {{ spacing: 9px; padding: 7px 0; }}
        QScrollBar:vertical {{ width: 12px; background: {PAGE}; }}
        QScrollBar::handle:vertical {{ background: {LIGHT_BLUE}; min-height: 30px; border-radius: 5px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
    """)
