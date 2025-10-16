from qgis.utils import iface
from PyQt5.QtWidgets import (
    QInputDialog,
    QMessageBox,
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QHBoxLayout,
    QApplication,
    QScrollArea,
)
from PyQt5.QtCore import Qt
import math


def is_effectively_null(val) -> bool:
    """Treat real NULLs, blanks, and common 'NULL' placeholders as empty."""
    if val is None:
        return True
    if isinstance(val, float) and math.isnan(val):
        return True
    s = str(val).strip()
    if s == "":
        return True
    if s.lower() in {"null", "none", "nan"}:
        return True
    return False


class ValuesDialog(QDialog):
    def __init__(self, counts_text, text):
        super().__init__()
        self.setWindowTitle("Field Values")
        self.setModal(True)
        self.resize(500, 300)
        self.raw_text = text  # unwrapped, comma-separated values

        layout = QVBoxLayout(self)

        # Counts header (bold)
        count_label = QLabel(counts_text)
        count_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(count_label)

        # Scrollable, wrapped output
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)

        self.label = QLabel(text)
        self.label.setWordWrap(True)
        self.label.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        scroll.setWidget(self.label)

        layout.addWidget(scroll)

        # Buttons
        btns = QHBoxLayout()
        self.copy_btn = QPushButton("Copy")
        self.ok_btn = QPushButton("OK")
        btns.addWidget(self.copy_btn)
        btns.addWidget(self.ok_btn)
        layout.addLayout(btns)

        self.copy_btn.clicked.connect(self.copy_and_close)
        self.ok_btn.clicked.connect(self.close)

        if not self.raw_text.strip():
            self.copy_btn.setEnabled(False)

    def copy_and_close(self):
        QApplication.clipboard().setText(self.raw_text)
        self.close()


# --- Main script logic ---
layer = iface.activeLayer()

if not layer:
    QMessageBox.warning(None, "No Layer", "No active layer found.")
else:
    field_name, ok = QInputDialog.getText(None, "Field Extractor", "Enter field name:")
    if ok and field_name:
        field_names = [f.name() for f in layer.fields()]
        if field_name not in field_names:
            QMessageBox.critical(None, "Field Error", f"Field '{field_name}' not found in layer.")
        else:
            selected_features = layer.selectedFeatures()
            if not selected_features:
                QMessageBox.information(None, "No Selection", "No features selected.")
            else:
                # Collect non-null/meaningful values only
                values = []
                for feat in selected_features:
                    val = feat[field_name]
                    if not is_effectively_null(val):
                        values.append(str(val))

                total_selected = len(selected_features)
                non_null_count = len(values)
                nulls_skipped = total_selected - non_null_count

                # Comma-separated output (space after comma for nicer wrapping)
                result = ", ".join(values)

                counts_text = (
                    f"Field: “{field_name}” | Selected features: {total_selected} | "
                    f"Values (non-null): {non_null_count} | Nulls skipped: {nulls_skipped}"
                )

                dialog = ValuesDialog(counts_text, result)
                dialog.show()  # or dialog.exec_() if you prefer blocking
