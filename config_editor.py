"""Settings UI: edit config.json / aliases.json without touching files by
hand. capture.py and report.py already reload these JSON files fresh on
every action, so saving here takes effect on the very next F8/report —
only the main window's cached hotkeys and hint text need an explicit
refresh, which main.py does right after this dialog closes.
"""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTabWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from config_io import (
    load_aliases, load_config, load_enchant_colors, save_aliases,
    save_config, save_enchant_colors,
)

ENCHANT_LEVELS = ["0", "1", "2", "3", "4"]
ENCHANT_METHODS = [
    ("color", "По цвету зоны (автоматически)"),
    ("manual", "Вручную (F1=0, F2=1, F3=2, F4=3, без зоны)"),
]


class GeneralTab(QWidget):
    def __init__(self, config: dict):
        super().__init__()
        form = QFormLayout(self)

        self.hotkey_capture = QLineEdit(config["hotkey_capture"])
        form.addRow("Хоткей захвата:", self.hotkey_capture)

        self.hotkey_edit_zones = QLineEdit(config["hotkey_edit_zones"])
        form.addRow("Хоткей редактора зон:", self.hotkey_edit_zones)

        self.db_path = QLineEdit(config["db_path"])
        form.addRow("Путь к БД:", self.db_path)

        tess_row = QHBoxLayout()
        self.tesseract_path = QLineEdit(config["tesseract_path"])
        tess_browse = QPushButton("Обзор…")
        tess_browse.clicked.connect(self._browse_tesseract)
        tess_row.addWidget(self.tesseract_path)
        tess_row.addWidget(tess_browse)
        form.addRow("Путь к tesseract.exe:", tess_row)

        self.price_sep = QLineEdit(config["price_thousands_separator"])
        self.price_sep.setMaxLength(1)
        self.price_sep.setFixedWidth(50)
        self.price_sep.setAlignment(Qt.AlignmentFlag.AlignCenter)
        form.addRow("Разделитель тысяч в цене (например «,» для 12,345):", self.price_sep)

        report_row = QHBoxLayout()
        self.report_dir = QLineEdit(config["report_output_dir"])
        report_browse = QPushButton("Обзор…")
        report_browse.clicked.connect(self._browse_report_dir)
        report_row.addWidget(self.report_dir)
        report_row.addWidget(report_browse)
        form.addRow("Папка отчётов:", report_row)

        self.enchant_method = QComboBox()
        for value, label in ENCHANT_METHODS:
            self.enchant_method.addItem(label, value)
        idx = self.enchant_method.findData(config.get("enchant_detection_method", "color"))
        self.enchant_method.setCurrentIndex(max(idx, 0))
        form.addRow("Метод определения зачарования:", self.enchant_method)

    def _browse_tesseract(self):
        path, _ = QFileDialog.getOpenFileName(self, "Выберите tesseract.exe", "", "Executable (*.exe)")
        if path:
            self.tesseract_path.setText(path)

    def _browse_report_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Выберите папку для отчётов")
        if path:
            self.report_dir.setText(path)

    def collect(self) -> dict:
        return {
            "hotkey_capture": self.hotkey_capture.text().strip() or "F8",
            "hotkey_edit_zones": self.hotkey_edit_zones.text().strip() or "ctrl+F8",
            "db_path": self.db_path.text().strip(),
            "tesseract_path": self.tesseract_path.text().strip(),
            "price_thousands_separator": self.price_sep.text() or ",",
            "report_output_dir": self.report_dir.text().strip() or "./reports",
            "enchant_detection_method": self.enchant_method.currentData(),
        }


class AliasesTab(QWidget):
    """alias (text in brackets in the item tooltip) -> tier."""

    def __init__(self, aliases: dict):
        super().__init__()
        layout = QVBoxLayout(self)

        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Alias (текст в скобках)", "Тир"])
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.setColumnWidth(0, 260)
        layout.addWidget(self.table)

        for alias, tier in sorted(aliases.items(), key=lambda kv: kv[1]):
            self._add_row(alias, tier)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Добавить строку")
        add_btn.clicked.connect(lambda: self._add_row("", 4))
        remove_btn = QPushButton("Удалить выбранную")
        remove_btn.clicked.connect(self._remove_selected)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(remove_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

    def _add_row(self, alias: str, tier: int):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(alias))
        tier_spin = QSpinBox()
        tier_spin.setRange(1, 8)
        tier_spin.setValue(tier)
        self.table.setCellWidget(r, 1, tier_spin)

    def _remove_selected(self):
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            self.table.removeRow(r)

    def collect(self) -> dict:
        result = {}
        for r in range(self.table.rowCount()):
            name_item = self.table.item(r, 0)
            alias = (name_item.text().strip().lower() if name_item else "")
            if not alias:
                continue
            tier_spin = self.table.cellWidget(r, 1)
            result[alias] = tier_spin.value()
        return result


class EnchantColorsTab(QWidget):
    """Reference HSV color per enchant level, sampled from the solid color
    bar under the item icon. Calibrated from real captures — see
    detect_enchant_debug() in capture.py for how these are matched."""

    def __init__(self, colors: dict):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Эталонные HSV-цвета полосы зачарования (H: 0-179, S/V: 0-255).\n"
            "Меняйте, только если распознавание реально ошибается — "
            "текущие значения сняты с живых скриншотов."
        ))

        self.table = QTableWidget(len(ENCHANT_LEVELS), 4)
        self.table.setHorizontalHeaderLabels(["Уровень", "H", "S", "V"])
        for row, level in enumerate(ENCHANT_LEVELS):
            level_item = QTableWidgetItem(level)
            level_item.setFlags(level_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, level_item)
            ref = colors.get(level, {"h": 0, "s": 0, "v": 0})
            for col, key, max_val in ((1, "h", 179), (2, "s", 255), (3, "v", 255)):
                spin = QSpinBox()
                spin.setRange(0, max_val)
                spin.setValue(int(round(ref.get(key, 0))))
                self.table.setCellWidget(row, col, spin)
        layout.addWidget(self.table)

    def collect(self) -> dict:
        result = {}
        for row, level in enumerate(ENCHANT_LEVELS):
            h_spin = self.table.cellWidget(row, 1)
            s_spin = self.table.cellWidget(row, 2)
            v_spin = self.table.cellWidget(row, 3)
            result[level] = {"h": h_spin.value(), "s": s_spin.value(), "v": v_spin.value()}
        return result


class ConfigEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.resize(640, 460)
        self.changed = False

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        self.general_tab = GeneralTab(load_config())
        self.aliases_tab = AliasesTab(load_aliases())
        self.enchant_tab = EnchantColorsTab(load_enchant_colors())
        tabs.addTab(self.general_tab, "Основные")
        tabs.addTab(self.aliases_tab, "Алиасы → тиры")
        tabs.addTab(self.enchant_tab, "Цвета зачарования")
        layout.addWidget(tabs)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Сохранить")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("Отмена")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch(1)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

    def _save(self):
        save_config(self.general_tab.collect())
        save_aliases(self.aliases_tab.collect())
        save_enchant_colors(self.enchant_tab.collect())
        self.changed = True
        QMessageBox.information(self, "Готово", "Настройки сохранены и применяются сразу — перезапуск не нужен.")
        self.accept()


def open_config_editor(parent=None) -> bool:
    """Returns True if settings were saved (so the caller can refresh
    anything it caches, like registered hotkeys)."""
    dialog = ConfigEditorDialog(parent)
    dialog.exec()
    return dialog.changed


if __name__ == "__main__":
    app = QApplication(sys.argv)
    open_config_editor()
