"""Zone calibration UI (ТЗ §5): mark item_name / item_enchant / sell_price
by dragging a rectangle over a transparent full-screen overlay."""
import sys

import mss
from PyQt6.QtCore import QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from config_io import load_config, load_zones, save_zones

ITEM_NAME_ZONE = ("item_name", "Название предмета",
                   "Выделите название предмета целиком, включая alias в скобках")
ITEM_ENCHANT_ZONE = ("item_enchant", "Индикатор зачарования",
                      "Выделите сплошную цветную полосу под ромбиками-пипсами (не сами ромбики)")
SELL_PRICE_ZONE = ("sell_price", "Цена продажи",
                    "Выделите цену первой строки в «Заказы на продажу»")


def get_zone_defs():
    """item_enchant isn't needed in "manual" mode (F1-F4 instead of a
    color zone) — see config's enchant_detection_method."""
    config = load_config()
    if config.get("enchant_detection_method") == "manual":
        return [ITEM_NAME_ZONE, SELL_PRICE_ZONE]
    return [ITEM_NAME_ZONE, ITEM_ENCHANT_ZONE, SELL_PRICE_ZONE]


def _physical_monitors():
    with mss.mss() as sct:
        return list(sct.monitors[1:])  # skip index 0 ("all monitors combined")


def _screen_physical_info(screen):
    """Match a QScreen to mss's own physical-pixel geometry for that same
    monitor, by nearest physical size. Needed because on a multi-monitor
    setup each screen can have its own DPI scale (e.g. 125% + 100%), so a
    single global logical->physical ratio is wrong for at least one of
    them — that mismatch is what made captured zones land on the wrong
    part of the screen (e.g. over an unrelated notification)."""
    geo = screen.geometry()
    dpr = screen.devicePixelRatio()
    phys_w = round(geo.width() * dpr)
    phys_h = round(geo.height() * dpr)
    monitors = _physical_monitors()
    best = min(monitors, key=lambda m: abs(m["width"] - phys_w) + abs(m["height"] - phys_h))
    return geo, dpr, best


def logical_rect_to_physical(rect: QRect) -> dict:
    """Convert a QRect in Qt's logical (device-independent) desktop
    coordinates into the physical-pixel bbox that mss.grab() expects,
    using the specific monitor the rectangle was drawn on."""
    top_left = rect.topLeft()
    screen = QGuiApplication.screenAt(top_left) or QGuiApplication.primaryScreen()
    geo, dpr, phys = _screen_physical_info(screen)
    x = phys["left"] + (top_left.x() - geo.x()) * dpr
    y = phys["top"] + (top_left.y() - geo.y()) * dpr
    w = rect.width() * dpr
    h = rect.height() * dpr
    return {"x": int(round(x)), "y": int(round(y)), "w": int(round(w)), "h": int(round(h))}


class OverlaySelector(QWidget):
    """Fullscreen (all monitors) translucent widget for dragging one rect."""

    selected = pyqtSignal(object)  # dict{x,y,w,h} or None on cancel

    def __init__(self, hint_text: str):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self._hint = hint_text
        self._origin = None
        self._current = None
        self._dragging = False
        self.setGeometry(QGuiApplication.primaryScreen().virtualGeometry())

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        painter.setPen(QPen(QColor(255, 255, 255)))
        painter.drawText(20, 30, f"{self._hint}   (ESC — отмена, ЛКМ — тянуть прямоугольник)")
        if self._origin and self._current:
            rect = QRect(self._origin, self._current).normalized()
            painter.setPen(QPen(QColor(255, 60, 60), 2))
            painter.fillRect(rect, QColor(255, 60, 60, 60))
            painter.drawRect(rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.selected.emit(None)
            self.close()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = True
            self._origin = event.globalPosition().toPoint()
            self._current = self._origin
            self.update()

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._current = event.globalPosition().toPoint()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            rect = QRect(self._origin, self._current).normalized()
            self.close()
            if rect.width() < 3 or rect.height() < 3:
                self.selected.emit(None)
            else:
                self.selected.emit(logical_rect_to_physical(rect))


class ZoneEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Редактирование зон захвата")
        self.setMinimumWidth(420)
        self.zones = load_zones() or {}
        self.zone_defs = get_zone_defs()
        self._overlay = None  # keep a reference so it isn't garbage-collected mid-drag

        layout = QVBoxLayout(self)
        self.row_labels = {}

        for key, title, hint in self.zone_defs:
            row = QHBoxLayout()
            name_label = QLabel(title)
            name_label.setMinimumWidth(190)
            status_label = QLabel(self._status_text(key))
            btn = QPushButton("Разметить")
            btn.clicked.connect(lambda _, k=key, h=hint: self._start_selection(k, h))
            row.addWidget(name_label)
            row.addWidget(status_label, 1)
            row.addWidget(btn)
            layout.addLayout(row)
            self.row_labels[key] = status_label

        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Сохранить")
        self.save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        self._update_save_enabled()

    def _status_text(self, key):
        z = self.zones.get(key)
        if not z:
            return "не задана"
        return f"x={z['x']} y={z['y']} w={z['w']} h={z['h']}"

    def _start_selection(self, key, hint):
        self.hide()
        self._overlay = OverlaySelector(hint)
        self._overlay.selected.connect(lambda rect, k=key: self._on_selected(k, rect))
        self._overlay.showFullScreen()

    def _on_selected(self, key, rect):
        self.show()
        if rect:
            self.zones[key] = rect
            self.row_labels[key].setText(self._status_text(key))
        self._update_save_enabled()

    def _update_save_enabled(self):
        required = [key for key, _, _ in self.zone_defs]
        self.save_btn.setEnabled(all(k in self.zones for k in required))

    def _save(self):
        save_zones(self.zones)
        QMessageBox.information(self, "Готово", "Зоны сохранены.")
        self.accept()


def open_zone_editor(parent=None) -> bool:
    dialog = ZoneEditorDialog(parent)
    return dialog.exec() == QDialog.DialogCode.Accepted


if __name__ == "__main__":
    app = QApplication(sys.argv)
    open_zone_editor()
