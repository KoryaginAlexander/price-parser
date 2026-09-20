"""DB browser: filter/search captured rows and delete records by hand.
Not part of the original ТЗ file list, but a natural addition on top of
storage.py's existing upsert/query functions."""
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

import storage
from config_io import load_config

CLASS_LABELS = {"hunter": "Охотник", "mage": "Маг", "warrior": "Воин"}

CLASS_OPTIONS = [("", "Все класс"), ("hunter", "Охотник"), ("mage", "Маг"), ("warrior", "Воин")]
TIER_OPTIONS = [("", "Все тиры")] + [(str(t), f"Тир {t}") for t in range(4, 9)] + [("-1", "? (не определён)")]
ENCHANT_OPTIONS = [("", "Все зачарования")] + [(str(e), str(e)) for e in range(0, 4)]

COLUMN_TITLES = ["ID", "Класс", "Предмет", "Тир", "Зач.", "Цена", "Проверка", "Обновлено", ""]


class DbEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("База данных — просмотр и редактирование")
        self.resize(920, 520)

        config = load_config()
        self.db_path = storage.resolve_db_path(config["db_path"])
        storage.init_db(self.db_path)

        layout = QVBoxLayout(self)

        filter_row = QHBoxLayout()

        self.class_combo = QComboBox()
        for value, label in CLASS_OPTIONS:
            self.class_combo.addItem(label, value)
        self.class_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.class_combo)

        self.tier_combo = QComboBox()
        for value, label in TIER_OPTIONS:
            self.tier_combo.addItem(label, value)
        self.tier_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.tier_combo)

        self.enchant_combo = QComboBox()
        for value, label in ENCHANT_OPTIONS:
            self.enchant_combo.addItem(label, value)
        self.enchant_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.enchant_combo)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("поиск по названию, например: мант")
        self.name_edit.textChanged.connect(self.refresh)
        filter_row.addWidget(self.name_edit, 1)

        layout.addLayout(filter_row)

        self.table = QTableWidget(0, len(COLUMN_TITLES))
        self.table.setHorizontalHeaderLabels(COLUMN_TITLES)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.hideColumn(0)  # id is kept for deletion, not shown
        layout.addWidget(self.table)

        bottom_row = QHBoxLayout()
        self.count_label = QLabel("")
        bottom_row.addWidget(self.count_label)
        bottom_row.addStretch(1)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        bottom_row.addWidget(close_btn)
        layout.addLayout(bottom_row)

        self.refresh()

    def refresh(self):
        item_class = self.class_combo.currentData() or None
        tier_raw = self.tier_combo.currentData()
        tier = int(tier_raw) if tier_raw else None
        enchant_raw = self.enchant_combo.currentData()
        enchant = int(enchant_raw) if enchant_raw not in (None, "") else None
        name_query = self.name_edit.text()

        rows = storage.fetch_filtered(
            self.db_path,
            item_class=item_class,
            tier=tier,
            enchant=enchant,
            name_query=name_query,
        )
        self._populate(rows)

    def _populate(self, rows):
        self.table.setRowCount(0)
        for row in rows:
            r = self.table.rowCount()
            self.table.insertRow(r)
            tier_display = str(row["tier"]) if row["tier"] >= 0 else "?"
            values = [
                str(row["id"]),
                CLASS_LABELS.get(row["class"], row["class"]),
                row["item_name"],
                tier_display,
                str(row["enchant"]),
                str(row["price"]) if row["price"] else "—",
                "да" if row["needs_review"] else "",
                row["updated_at"],
            ]
            for c, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(r, c, item)

            delete_btn = QPushButton("Удалить")
            delete_btn.clicked.connect(lambda _, item_id=row["id"]: self._delete(item_id))
            self.table.setCellWidget(r, len(values), delete_btn)

        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.count_label.setText(f"Найдено: {len(rows)}")

    def _delete(self, item_id: int):
        confirm = QMessageBox.question(
            self, "Удалить запись", "Удалить эту запись из базы?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            storage.delete_by_id(self.db_path, item_id)
            self.refresh()


def open_db_editor(parent=None) -> None:
    dialog = DbEditorDialog(parent)
    dialog.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    open_db_editor()
