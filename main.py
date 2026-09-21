"""Entry point: main window, class selector, hotkey, report button (ТЗ §4)."""
import os
import sys

import keyboard
import winsound
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import (
    QApplication, QButtonGroup, QFileDialog, QHBoxLayout, QLabel,
    QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import capture
import report as report_module
from config_editor import open_config_editor
from config_io import load_config, load_zones, zones_configured
from db_editor import open_db_editor
from paths import resource_path
from zone_editor import open_zone_editor

GUNSHOT_WAV = resource_path(os.path.join("assets", "gunshot.wav"))

CLASS_MAP = {
    "hunter": "Охотник",
    "mage": "Маг",
    "warrior": "Воин",
}


MANUAL_ENCHANT_HOTKEYS = {"F1": 0, "F2": 1, "F3": 2, "F4": 3}


class HotkeyBridge(QObject):
    """`keyboard` fires hotkey callbacks on its own hook thread; signals
    marshal them back onto the Qt main thread safely."""
    capture_triggered = pyqtSignal()
    edit_zones_triggered = pyqtSignal()
    manual_enchant_selected = pyqtSignal(int)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Albion Market Scanner")
        self.setFixedWidth(380)

        self.config = load_config()
        self.selected_class = None
        self.manual_enchant_level = 0

        self.bridge = HotkeyBridge()
        self.bridge.capture_triggered.connect(self.on_capture_hotkey)
        self.bridge.edit_zones_triggered.connect(self.on_edit_zones_hotkey)
        self.bridge.manual_enchant_selected.connect(self.on_manual_enchant_selected)

        central = QWidget()
        layout = QVBoxLayout(central)

        class_row = QHBoxLayout()
        self.class_group = QButtonGroup(self)
        self.class_group.setExclusive(True)
        for key, label in CLASS_MAP.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _, k=key: self.set_class(k))
            class_row.addWidget(btn)
            self.class_group.addButton(btn)
        layout.addLayout(class_row)

        self.zones_status_label = QLabel()
        layout.addWidget(self.zones_status_label)

        self.class_status_label = QLabel("Класс не выбран")
        layout.addWidget(self.class_status_label)

        self.manual_enchant_label = QLabel()
        layout.addWidget(self.manual_enchant_label)
        self._update_manual_enchant_label()

        edit_zones_btn = QPushButton("Редактировать зоны")
        edit_zones_btn.clicked.connect(self.on_edit_zones_clicked)
        layout.addWidget(edit_zones_btn)

        report_btn = QPushButton("Сформировать отчёт")
        report_btn.clicked.connect(self.on_generate_report)
        layout.addWidget(report_btn)

        db_editor_btn = QPushButton("Редактировать БД")
        db_editor_btn.clicked.connect(self.on_edit_db_clicked)
        layout.addWidget(db_editor_btn)

        settings_btn = QPushButton("Настройки")
        settings_btn.clicked.connect(self.on_settings_clicked)
        layout.addWidget(settings_btn)

        self.hotkey_hint_label = QLabel()
        self.hotkey_hint_label.setStyleSheet("color: gray;")
        layout.addWidget(self.hotkey_hint_label)
        self._update_hotkey_hint()

        self.last_result_label = QLabel("")
        self.last_result_label.setWordWrap(True)
        layout.addWidget(self.last_result_label)

        self.setCentralWidget(central)

        self.refresh_zones_status()
        self.register_hotkeys()

        if not zones_configured(load_zones(), self.config.get("enchant_detection_method", "color")):
            self.zones_status_label.setText("Зоны не настроены — откройте редактор зон")
            self.open_zone_editor_dialog()

    def set_class(self, key):
        self.selected_class = key
        self.class_status_label.setText(f"Класс: {CLASS_MAP[key]}")

    def _update_hotkey_hint(self):
        hint = (
            f"Захват: {self.config['hotkey_capture']}    "
            f"Редактор зон: {self.config['hotkey_edit_zones']}"
        )
        if self._manual_mode():
            hint += "    Зачарование: F1-F4"
        self.hotkey_hint_label.setText(hint)

    def _manual_mode(self) -> bool:
        return self.config.get("enchant_detection_method") == "manual"

    def _update_manual_enchant_label(self):
        if self._manual_mode():
            self.manual_enchant_label.setText(f"Зачарование (F1-F4): {self.manual_enchant_level}")
            self.manual_enchant_label.show()
        else:
            self.manual_enchant_label.hide()

    def on_manual_enchant_selected(self, level: int):
        self.manual_enchant_level = level
        self._update_manual_enchant_label()

    def refresh_zones_status(self):
        if zones_configured(load_zones(), self.config.get("enchant_detection_method", "color")):
            self.zones_status_label.setText("Зоны настроены ✓")
        else:
            self.zones_status_label.setText("Зоны НЕ настроены ✗")

    def register_hotkeys(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        keyboard.add_hotkey(self.config["hotkey_capture"], self.bridge.capture_triggered.emit)
        keyboard.add_hotkey(self.config["hotkey_edit_zones"], self.bridge.edit_zones_triggered.emit)
        if self._manual_mode():
            for hotkey, level in MANUAL_ENCHANT_HOTKEYS.items():
                keyboard.add_hotkey(
                    hotkey, lambda lvl=level: self.bridge.manual_enchant_selected.emit(lvl)
                )

    def on_edit_db_clicked(self):
        open_db_editor(self)

    def on_settings_clicked(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        changed = open_config_editor(self)
        if changed:
            self.config = load_config()
            self._update_hotkey_hint()
            self._update_manual_enchant_label()
            self.refresh_zones_status()
        self.register_hotkeys()

    def on_edit_zones_clicked(self):
        self.open_zone_editor_dialog()

    def on_edit_zones_hotkey(self):
        self.open_zone_editor_dialog()

    def open_zone_editor_dialog(self):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        open_zone_editor(self)
        self.register_hotkeys()
        self.refresh_zones_status()

    def on_capture_hotkey(self):
        if not zones_configured(load_zones(), self.config.get("enchant_detection_method", "color")):
            return
        if not self.selected_class:
            self._beep_error()
            self.last_result_label.setText("Не выбран класс предмета — захват отменён")
            return

        self._play_gunshot()

        try:
            result = capture.do_capture(self.selected_class, self.manual_enchant_level)
        except Exception as exc:
            self._beep_error()
            self.last_result_label.setText(f"Ошибка захвата: {exc}")
            return

        if not result.get("ok"):
            self._beep_error()
            self.last_result_label.setText(f"Не удалось распознать: {result.get('reason')}")
            return

        review_note = " (требует проверки)" if result["needs_review"] else ""
        tier = result["tier"] if result["tier"] is not None else "?"
        dbg = result.get("enchant_debug") or {}
        if dbg.get("method") == "manual":
            extra_note = "зачарование задано вручную (F1-F4)"
        else:
            extra_note = f"цвет зоны зачарования: H{dbg.get('h', 0):.0f}/S{dbg.get('s', 0):.0f}/V{dbg.get('v', 0):.0f}"
        self.last_result_label.setText(
            f"{result['item_name']} | тир {tier} | зач. {result['enchant']} "
            f"| цена {result['price']}{review_note}\n"
            f"{extra_note}"
        )

    def _play_gunshot(self):
        try:
            winsound.PlaySound(GUNSHOT_WAV, winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass

    def _beep_error(self):
        try:
            winsound.Beep(400, 250)
        except Exception:
            pass

    def on_generate_report(self):
        try:
            suggested_dir = os.path.expandvars(self.config.get("report_output_dir", "./reports"))
            os.makedirs(suggested_dir, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(
                self, "Сохранить отчёт",
                os.path.join(suggested_dir, "albion_report.xlsx"),
                "Excel Files (*.xlsx)",
            )
            if not path:
                return
            output_path = report_module.generate_report(output_path=path)
            QMessageBox.information(self, "Готово", f"Отчёт сохранён: {output_path}")
            try:
                os.startfile(output_path)
            except Exception:
                pass
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сформировать отчёт: {exc}")

    def closeEvent(self, event):
        try:
            keyboard.unhook_all()
        except Exception:
            pass
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
