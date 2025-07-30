from qgis.utils import iface
from PyQt5.QtWidgets import QInputDialog, QMessageBox

# Get the active layer
layer = iface.activeLayer()

if not layer:
    QMessageBox.warning(None, "No Layer", "No active layer found.")
else:
    # Prompt for field name
    field_name, ok = QInputDialog.getText(None, "Field Extractor", "Enter field name:")
    
    if ok and field_name:
        # Check if field exists
        if field_name not in [field.name() for field in layer.fields()]:
            QMessageBox.critical(None, "Field Error", f"Field '{field_name}' not found in layer.")
        else:
            selected_features = layer.selectedFeatures()
            if not selected_features:
                QMessageBox.information(None, "No Selection", "No features selected.")
            else:
                values = [str(f[field_name]) for f in selected_features if f[field_name] is not None]
                result = ", ".join(values)
                QMessageBox.information(None, "Field Values", result)
